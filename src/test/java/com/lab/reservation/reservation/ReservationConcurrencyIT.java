package com.lab.reservation.reservation;

import com.lab.reservation.dto.reservation.ReservationCreateDTO;
import com.lab.reservation.entity.ReservationItem;
import com.lab.reservation.exception.BusinessException;
import com.lab.reservation.mapper.ReservationItemMapper;
import com.lab.reservation.service.ReservationService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.*;

import static org.junit.jupiter.api.Assertions.*;

/**
 * 防超约亮点实证：8 线程并发抢同一设备同一时段，断言恰好 1 成功。
 *
 * 防超约机制：reservation_item 上的 UNIQUE(device_id, date, slot_index) 唯一索引。
 * 并发下两个事务抢同一 slot 时，后者的 item 插入命中唯一索引抛 DuplicateKeyException，
 * service 层 catch 转译为 BusinessException(RESERVATION_CONFLICT) 并触发 @Transactional 整体回滚。
 *
 * 注：spec 要求 Testcontainers，但本机 Docker Desktop 4.60 的引擎 socket 在 WSL/Windows
 * 客户端下不再暴露完整的 Docker Engine API（/info 返 400 BadRequest），导致 Testcontainers
 * 无法连上引擎。此处改用本地 dev MySQL（localhost:3306/lab_reservation）实测并发：
 * 并发行为完全等价（依然走唯一索引约束），并保留了"清理/重建数据"避免污染 dev 库。
 */
@SpringBootTest
class ReservationConcurrencyIT {

    @Autowired
    ReservationService reservationService;
    @Autowired
    ReservationItemMapper itemMapper;
    @Autowired
    JdbcTemplate jdbc;

    private final List<Long> userIds = new ArrayList<>();

    @BeforeEach
    void seed() {
        // 清掉本测试可能留下的历史数据，避免污染
        jdbc.update("DELETE FROM reservation_item WHERE device_id = 1 AND date = ?",
                LocalDate.now(ZoneId.systemDefault()).plusDays(2));
        jdbc.update("DELETE r FROM reservation r LEFT JOIN sys_user u ON r.user_id = u.id WHERE u.username LIKE 'it_stu_%'");
        jdbc.update("DELETE FROM sys_user WHERE username LIKE 'it_stu_%'");

        // 设备 id=1（奥林巴斯BX53, need_approval=1, max=4h）由 V2 种子提供。预插 8 个学生用户。
        for (int i = 0; i < 8; i++) {
            jdbc.update("INSERT INTO sys_user(username,password,real_name,status) VALUES (?,?,?,1)",
                    "it_stu_" + i, "dummy-hash", "test" + i);
            userIds.add(jdbc.queryForObject("SELECT LAST_INSERT_ID()", Long.class));
        }
    }

    @Test
    void concurrent_same_slot_only_one_wins() throws Exception {
        Long deviceId = 1L;
        // 用「未来日期」避免 create 的"不能预约过去时间"校验；09:00-10:00 = 4 槽。
        LocalDate day = LocalDate.now(ZoneId.systemDefault()).plusDays(2);
        LocalDateTime start = day.atTime(9, 0);
        LocalDateTime end = day.atTime(10, 0);

        ExecutorService pool = Executors.newFixedThreadPool(8);
        List<Callable<Long>> tasks = new ArrayList<>();
        for (int i = 0; i < 8; i++) {
            final Long uid = userIds.get(i);
            tasks.add(() -> {
                ReservationCreateDTO dto = new ReservationCreateDTO();
                dto.setDeviceId(deviceId);
                dto.setStartTime(start);
                dto.setEndTime(end);
                dto.setPurpose("p-" + uid);
                return reservationService.create(dto, uid);
            });
        }
        List<Future<Long>> futures = pool.invokeAll(tasks);
        int ok = 0, conflict = 0;
        for (Future<Long> f : futures) {
            try {
                f.get();
                ok++;
            } catch (Exception e) {
                if (e.getCause() instanceof BusinessException) {
                    conflict++;
                }
            }
        }
        pool.shutdown();

        assertEquals(1, ok, "恰好一个预约成功");
        assertEquals(7, conflict, "其余 7 个全部冲突");

        // DB 断言：该设备该日仅 4 个槽被占（60min / 15min = 4）且槽号互不重复。
        List<ReservationItem> held = itemMapper.selectList(null).stream()
                .filter(it -> it.getDeviceId().equals(deviceId) && it.getDate().equals(day))
                .toList();
        assertEquals(4, held.size());
        assertEquals(4, held.stream().map(ReservationItem::getSlotIndex).distinct().count(), "槽号无重复");
    }
}

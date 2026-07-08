package com.lab.reservation.ai.tool;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.lab.reservation.ai.dto.ToolExecutionResult;
import com.lab.reservation.dto.device.DeviceQueryDTO;
import com.lab.reservation.entity.enums.ReservationStatus;
import com.lab.reservation.exception.BusinessException;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.service.DeviceCategoryService;
import com.lab.reservation.service.DeviceService;
import com.lab.reservation.vo.device.DeviceCalendarItemVO;
import com.lab.reservation.vo.device.DeviceVO;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;

import java.time.LocalDate;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * 设备相关的 AI 工具集（只读）。
 *
 * <p>提供两个 {@code @Tool} 方法：
 * <ul>
 *   <li>{@code searchDevices} — 按关键词/类别/可用时段筛选设备，组合
 *       {@link DeviceService#search(DeviceQueryDTO)} + {@link DeviceService#calendar(Long, LocalDate, LocalDate)}，
 *       返回在该时段全部空闲的设备列表。</li>
 *   <li>{@code getDeviceDetails} — 设备详情（规格/位置/状态）。</li>
 * </ul>
 *
 * <p>工具说明中角色声明（{@code {roles:...}}）会被 {@link com.lab.reservation.ai.service.ToolRegistry}
 * 自动解析，无需在代码里再过滤角色。
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class DeviceTool {

    private final DeviceService deviceService;
    private final DeviceCategoryService deviceCategoryService;
    private final ToolArgumentValidator validator;

    /**
     * 按关键词 / 类别 / 时段筛选设备。
     *
     * <p>三步组合：
     * <ol>
     *   <li>把用户给的 category 中文名 / 关键词翻译成 {@link DeviceQueryDTO}（含 categoryId 解析）；</li>
     *   <li>调 {@code DeviceService.search(...)} 取第一页 topN 设备；</li>
     *   <li>若给定时段，遍历设备调 {@code DeviceService.calendar(...)}，剔除在该时段存在
     *       PENDING / APPROVED / IN_USE 占用槽位的设备。</li>
     * </ol>
     *
     * @param keyword   设备名模糊关键词（可空；空表示不过滤）
     * @param timeRange 时段，格式 {@code "yyyy-MM-dd,yyyy-MM-dd"} 或单个 {@code "yyyy-MM-dd"}；
     *                  可空，空表示不过滤时段
     * @param category  类别名（中文，匹配 {@code DeviceCategoryNodeVO.name}）；可空
     * @param topN      返回上限（必填，&gt; 0）
     */
    @Tool(name = "searchDevices",
          description = "按关键词/类别/可用时段搜索实验室设备。"
                  + "category 为类别中文名,timeRange 形如 '2026-07-08,2026-07-09' 或单日 '2026-07-08'。"
                  + "返回的设备在该时段内全部空闲。{roles:STUDENT,LAB_ADMIN,SYS_ADMIN}")
    public ToolExecutionResult searchDevices(
            @ToolParam(description = "设备名模糊关键词,可空") String keyword,
            @ToolParam(description = "时段,格式 'yyyy-MM-dd' 或 'yyyy-MM-dd,yyyy-MM-dd',可空") String timeRange,
            @ToolParam(description = "类别中文名,可在设备分类树中找到,可空") String category,
            @ToolParam(description = "返回上限(>0)") Integer topN) {

        if (topN == null || topN <= 0) {
            return ToolExecutionResult.fail("PARAM_INVALID", "topN 必须 > 0");
        }
        // 工具被调时,SecurityContextHolder 应已由 AiAssistantService 注入;
        // 此处不强制要求非空,只用于审计日志。
        Long currentUserId = currentUserIdOrNull();

        try {
            DeviceQueryDTO q = new DeviceQueryDTO();
            q.setKeyword(blankToNull(keyword));
            q.setPage(1L);
            q.setSize(topN.longValue());
            // 类别:按中文名在分类树中查找 id
            if (category != null && !category.isBlank()) {
                Long categoryId = findCategoryIdByName(category.trim());
                q.setCategoryId(categoryId);
            }

            IPage<DeviceVO> page = deviceService.search(q);
            List<DeviceVO> devices = page.getRecords();
            if (devices == null) devices = Collections.emptyList();

            // 时段过滤
            DateRange range = parseRange(timeRange);
            if (range != null && !devices.isEmpty()) {
                devices = filterByAvailability(devices, range);
            }

            // 截断
            if (devices.size() > topN) {
                devices = new ArrayList<>(devices.subList(0, topN));
            }

            log.info("searchDevices user={} keyword='{}' category='{}' range={} topN={} hits={}",
                    currentUserId, keyword, category, range, topN, devices.size());
            return ToolExecutionResult.ok(devices);
        } catch (BusinessException e) {
            return ToolExecutionResult.fail(String.valueOf(e.getCode()), e.getMessage());
        }
    }

    /**
     * 设备详情。
     */
    @Tool(name = "getDeviceDetails",
          description = "按设备 ID 获取设备详情(规格/位置/状态/价格/标签等)。{roles:STUDENT,LAB_ADMIN,SYS_ADMIN}")
    public ToolExecutionResult getDeviceDetails(
            @ToolParam(description = "设备 ID(>0)") Long deviceId) {

        // 仅对真正必填字段走 validator
        Map<String, Object> args = new HashMap<>();
        args.put("deviceId", deviceId);
        validator.validate("DeviceTool.getDeviceDetails", args);

        try {
            DeviceVO vo = deviceService.getById(deviceId);
            return ToolExecutionResult.ok(vo);
        } catch (BusinessException e) {
            return ToolExecutionResult.fail(String.valueOf(e.getCode()), e.getMessage());
        }
    }

    // -------- helpers --------

    private List<DeviceVO> filterByAvailability(List<DeviceVO> devices, DateRange range) {
        List<DeviceVO> out = new ArrayList<>();
        for (DeviceVO d : devices) {
            if (d == null || d.getId() == null) continue;
            List<DeviceCalendarItemVO> cal = safeCalendar(d.getId(), range);
            if (cal.isEmpty()) {
                // 没有任何 PENDING/APPROVED/IN_USE 占用,视为全部空闲
                out.add(d);
            }
        }
        return out;
    }

    private List<DeviceCalendarItemVO> safeCalendar(Long deviceId, DateRange range) {
        try {
            List<DeviceCalendarItemVO> raw = deviceService.calendar(deviceId, range.from, range.to);
            if (raw == null) return Collections.emptyList();
            // calendar 已只在 PENDING / APPROVED / IN_USE 状态写入,这里二次确认防御一下
            Set<String> blocking = Set.of(
                    ReservationStatus.PENDING.name(),
                    ReservationStatus.APPROVED.name(),
                    ReservationStatus.IN_USE.name()
            );
            List<DeviceCalendarItemVO> filtered = new ArrayList<>();
            for (DeviceCalendarItemVO it : raw) {
                if (it != null && it.getStatus() != null && blocking.contains(it.getStatus())) {
                    filtered.add(it);
                }
            }
            return filtered;
        } catch (BusinessException e) {
            log.debug("calendar(deviceId={}) ignored: {}", deviceId, e.getMessage());
            return Collections.emptyList();
        }
    }

    /** 在分类树里按 name 精确匹配（大小写不敏感,trim 后比较）。 */
    private Long findCategoryIdByName(String name) {
        try {
            return walkForCategoryId(deviceCategoryService.tree(), name);
        } catch (BusinessException e) {
            log.debug("category tree lookup failed: {}", e.getMessage());
            return null;
        }
    }

    private Long walkForCategoryId(List<com.lab.reservation.vo.device.DeviceCategoryNodeVO> nodes, String name) {
        if (nodes == null) return null;
        for (com.lab.reservation.vo.device.DeviceCategoryNodeVO n : nodes) {
            if (n == null) continue;
            if (n.getName() != null && n.getName().trim().equalsIgnoreCase(name)) {
                return n.getId();
            }
            Long child = walkForCategoryId(n.getChildren(), name);
            if (child != null) return child;
        }
        return null;
    }

    private static String blankToNull(String s) {
        return (s == null || s.isBlank()) ? null : s.trim();
    }

    private static Long currentUserIdOrNull() {
        try {
            Authentication auth = SecurityContextHolder.getContext().getAuthentication();
            if (auth == null || !auth.isAuthenticated()) return null;
            Object p = auth.getPrincipal();
            return (p instanceof SecurityUserDetails u) ? u.getUserId() : null;
        } catch (Exception e) {
            return null;
        }
    }

    /** 解析 timeRange;非法格式返回 null（视为不过滤）。 */
    private static DateRange parseRange(String s) {
        if (s == null || s.isBlank()) return null;
        String[] parts = s.split(",", -1);
        try {
            LocalDate from = LocalDate.parse(parts[0].trim());
            LocalDate to = (parts.length > 1 && !parts[1].isBlank())
                    ? LocalDate.parse(parts[1].trim())
                    : from;
            if (to.isBefore(from)) {
                log.debug("timeRange to < from, ignoring: {}", s);
                return null;
            }
            return new DateRange(from, to);
        } catch (DateTimeParseException e) {
            log.debug("timeRange parse failed, ignoring: {}", s);
            return null;
        }
    }

    private record DateRange(LocalDate from, LocalDate to) { }
}

package com.lab.reservation.mapper;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.lab.reservation.entity.PendingTimeoutTask;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 延迟任务表 Mapper。
 *
 * <p>扫描用 {@link #claimDuePending(LocalDateTime, int)} 一次性拿走一批到点任务
 * （{@code UPDATE ... status='DONE' WHERE id IN (SELECT ...)} 思路：单线程调度器无需
 * 悲观锁，直接 SELECT 拿到 id 后逐条 UPDATE 状态，简单且够用）。
 *
 * <p>Producer 端只调 {@link #insert}；失败重试用 {@link #markFailed} + {@link #markDone}。
 */
@Mapper
public interface PendingTimeoutTaskMapper extends BaseMapper<PendingTimeoutTask> {

    /**
     * 取一批到期未执行的 PENDING 任务。{@code ORDER BY execute_at} 保证 FIFO。
     */
    @Select("SELECT * FROM pending_timeout_task "
            + "WHERE status = 'PENDING' AND execute_at <= #{now} "
            + "ORDER BY execute_at ASC LIMIT #{limit}")
    List<PendingTimeoutTask> claimDuePending(LocalDateTime now, int limit);

    /**
     * 标记成功（执行完直接删除最简单，避免表膨胀）。
     * 实际 Producer 在 init 时不删、Consumer 在 done 时删。
     */
    @Update("DELETE FROM pending_timeout_task WHERE id = #{id}")
    int deleteById(Long id);

    /**
     * 标记失败：attempts +1，记录错误摘要。attempts >= 5 时改 status=FAILED（不再重试）。
     */
    @Update("UPDATE pending_timeout_task "
            + "SET attempts = attempts + 1, last_error = #{err}, "
            + "    status = IF(attempts + 1 >= 5, 'FAILED', 'PENDING') "
            + "WHERE id = #{id}")
    int markFailed(Long id, String err);

    /** 幂等检查：根据 reservation_id 是否还有 PENDING 任务。Producer 端用，避免重复入队。 */
    default boolean existsPendingByReservationId(Long reservationId) {
        Long n = selectCount(new LambdaQueryWrapper<PendingTimeoutTask>()
                .eq(PendingTimeoutTask::getReservationId, reservationId)
                .eq(PendingTimeoutTask::getStatus, PendingTimeoutTask.Status.PENDING.name()));
        return n != null && n > 0;
    }
}

package com.lab.reservation.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.lab.reservation.entity.AiToolExecution;
import org.apache.ibatis.annotations.Mapper;

/**
 * AI 工具执行审计 Mapper。
 *
 * <p>状态机的状态转换 SQL 由 Task 4b 的 {@code ConfirmationService} 实现,
 * 此处只暴露 {@link BaseMapper} 的通用 CRUD。
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
@Mapper
public interface AiToolExecutionMapper extends BaseMapper<AiToolExecution> {
}
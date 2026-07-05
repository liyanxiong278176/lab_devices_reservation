<script setup lang="ts">
// Timeline — 垂直时间轴(深色)
// 设计 spec §5 + plan Task R1.5:
//   - 预约/报修生命周期:done(已发生,实心淡化点)/ current(进行中,青色脉冲点)/
//     todo(未到,空心点)。
//   - 每项左侧节点点 + 竖向 1px 连接线(连接相邻节点,仅非末项),右侧标题/desc/time。
//   - 全量走 token,scoped scss。脉冲只用 transform/opacity(GPU),本地 reduced-motion 守卫。
//   - 容器级 stagger 由父页用 data-stagger 包,本组件不内嵌入场动画。
type Status = 'done' | 'current' | 'todo'

interface Item {
  title: string
  desc?: string
  time?: string
  status: Status
}

defineProps<{
  items: Item[]
}>()
</script>

<template>
  <ol class="timeline" role="list">
    <li
      v-for="(item, i) in items"
      :key="i"
      class="timeline__item"
      :class="`timeline__item--${item.status}`"
      :data-status="item.status"
    >
      <!-- 左侧导轨:节点点 + 向下连接线(仅非末项) -->
      <div class="timeline__rail" aria-hidden="true">
        <span class="timeline__node" :class="`timeline__node--${item.status}`" />
        <span v-if="i < items.length - 1" class="timeline__line" />
      </div>
      <!-- 右侧内容 -->
      <div class="timeline__content">
        <div class="timeline__title">{{ item.title }}</div>
        <div v-if="item.desc" class="timeline__desc">{{ item.desc }}</div>
        <div v-if="item.time" class="timeline__time">{{ item.time }}</div>
      </div>
    </li>
  </ol>
</template>

<style scoped lang="scss">
// 通过 CSS 变量把节点颜色从 item modifier 桥到 node/伪元素,色全走 token,无硬编码 hex。
.timeline {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
}

.timeline__item {
  display: grid;
  grid-template-columns: 20px 1fr;
  gap: 12px;
  padding-bottom: 20px;

  &:last-child {
    padding-bottom: 0;
  }
}

// ---- 左侧导轨:节点 + 连接线 ----------------------------------------------
.timeline__rail {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  align-self: stretch;
}

.timeline__node {
  position: relative;
  width: 10px;
  height: 10px;
  margin-top: 4px; // 与右侧标题首行视觉对齐
  border-radius: 50%;
  background: var(--node-color, var(--text-tertiary));
  box-shadow: var(--node-ring, none);
  // todo 空心点:透明底 + 发丝边
  border: 1px solid transparent;
}

// 连接线:从节点下方延伸到下一个节点(竖向 1px)
.timeline__line {
  flex: 1 1 auto;
  width: 1px;
  margin-top: 4px;
  background: var(--border-default);
}

// ---- 右侧内容 ------------------------------------------------------------
.timeline__content {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.timeline__title {
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 500;
  line-height: 1.5;
}

.timeline__desc {
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.5;
}

// time 用 mono caption(spec §5 "时间文字 --font-mono 可选")
.timeline__time {
  color: var(--text-tertiary);
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.4;
  letter-spacing: 0.02em;
}

// ============================================================================
// 状态映射
// ============================================================================

// ---- done:实心淡化点(success 色淡化),线已连 --------------------------------
.timeline__item--done {
  --node-color: var(--text-tertiary);

  .timeline__title {
    color: var(--text-primary);
  }
}

// ---- current:青色脉冲点 + 标题加粗(进行中) -------------------------------
.timeline__item--current {
  --node-color: var(--accent);

  .timeline__title {
    color: var(--text-primary);
    font-weight: 600;
  }

  // 脉冲:伪元素 scale + opacity(GPU 合成层,不触发 layout),思路同 StatusDot
  .timeline__node::after {
    content: '';
    position: absolute;
    inset: 0;
    border-radius: 50%;
    background: var(--node-color);
    animation: timeline-pulse 1.6s var(--ease-out-expo) infinite;
    will-change: transform, opacity;
  }
}

// ---- todo:空心点(发丝边 + 透明底),内容淡化 -------------------------------
.timeline__item--todo {
  --node-color: transparent;

  .timeline__node {
    background: transparent;
    border-color: var(--border-strong);
  }

  .timeline__title {
    color: var(--text-tertiary);
  }

  .timeline__desc {
    color: var(--text-tertiary);
  }
}

// ============================================================================
// keyframes —— 仅 transform / opacity(GPU)
// ============================================================================
@keyframes timeline-pulse {
  0% {
    transform: scale(1);
    opacity: 0.55;
  }
  100% {
    transform: scale(2.4);
    opacity: 0;
  }
}

// ---- 本地 reduced-motion 守卫(全局 _motion.scss 不覆盖本组件 keyframe)------
@media (prefers-reduced-motion: reduce) {
  .timeline__item--current .timeline__node::after {
    animation: none;
  }
}
</style>

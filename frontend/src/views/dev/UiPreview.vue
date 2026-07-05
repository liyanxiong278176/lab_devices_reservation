<script setup lang="ts">
// ============================================================================
// UiPreview — R1 全组件目检页(临时开发页)
// ----------------------------------------------------------------------------
// Slice R1 收尾:14 件 UI 组件集中渲染 + 示例 props/slots,供设计目检 + 截图。
// 此页是临时产物,Slice R6 会删掉它(路由 + 文件一并清)。
//   - 路由:/ui-preview(child of /,套 MainLayout 深色壳)
//   - meta.hidden:true → 不进侧边栏菜单(MainLayout menuItems 已过滤 hidden)
//   - 不写测试:预览页无业务逻辑,R6 删
// 全量走 design token,scoped scss,无硬编码色。
// ============================================================================
import { ref } from 'vue'
import PageHeader from '@/components/ui/PageHeader.vue'
import Panel from '@/components/ui/Panel.vue'
import GlowCard from '@/components/ui/GlowCard.vue'
import GradientButton from '@/components/ui/GradientButton.vue'
import GhostButton from '@/components/ui/GhostButton.vue'
import TextButton from '@/components/ui/TextButton.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Tag from '@/components/ui/Tag.vue'
import Badge from '@/components/ui/Badge.vue'
import StatusDot from '@/components/ui/StatusDot.vue'
import StatCard from '@/components/ui/StatCard.vue'
import SegmentedControl from '@/components/ui/SegmentedControl.vue'
import Timeline from '@/components/ui/Timeline.vue'

// SegmentedControl 双向绑定示例
const seg = ref('a')
</script>

<template>
  <div class="ui-preview">
    <PageHeader title="UI 预览" subtitle="R1 全组件目检 · 14 件 · 临时页(R6 删)" />

    <!-- 01 PageHeader ---------------------------------------------------------- -->
    <section class="ui-preview__section">
      <h2 class="ui-preview__title">01 · PageHeader</h2>
      <Panel>
        <PageHeader title="设备管理" subtitle="实验室资产总览与状态监控" />
      </Panel>
    </section>

    <!-- 02 Panel -------------------------------------------------------------- -->
    <section class="ui-preview__section">
      <h2 class="ui-preview__title">02 · Panel</h2>
      <div class="ui-preview__row">
        <Panel>普通卡片</Panel>
        <Panel :accent="true">accent 顶条卡</Panel>
      </div>
    </section>

    <!-- 03 GlowCard ----------------------------------------------------------- -->
    <section class="ui-preview__section">
      <h2 class="ui-preview__title">03 · GlowCard</h2>
      <div class="ui-preview__row">
        <GlowCard>hover 辉光卡</GlowCard>
        <GlowCard :accent="true">accent + 辉光</GlowCard>
      </div>
    </section>

    <!-- 04 GradientButton ----------------------------------------------------- -->
    <section class="ui-preview__section">
      <h2 class="ui-preview__title">04 · GradientButton</h2>
      <div class="ui-preview__row">
        <GradientButton>主操作</GradientButton>
        <GradientButton disabled>禁用态</GradientButton>
      </div>
    </section>

    <!-- 05 GhostButton -------------------------------------------------------- -->
    <section class="ui-preview__section">
      <h2 class="ui-preview__title">05 · GhostButton</h2>
      <div class="ui-preview__row">
        <GhostButton>次操作</GhostButton>
        <GhostButton disabled>禁用态</GhostButton>
      </div>
    </section>

    <!-- 06 TextButton --------------------------------------------------------- -->
    <section class="ui-preview__section">
      <h2 class="ui-preview__title">06 · TextButton</h2>
      <div class="ui-preview__row">
        <TextButton>文字按钮</TextButton>
        <TextButton disabled>禁用态</TextButton>
      </div>
    </section>

    <!-- 07 Skeleton ----------------------------------------------------------- -->
    <section class="ui-preview__section">
      <h2 class="ui-preview__title">07 · Skeleton</h2>
      <Panel>
        <div class="ui-preview__row">
          <Skeleton width="120px" height="20px" />
          <Skeleton variant="circle" />
          <Skeleton variant="text" :rows="3" />
        </div>
      </Panel>
    </section>

    <!-- 08 EmptyState --------------------------------------------------------- -->
    <section class="ui-preview__section">
      <h2 class="ui-preview__title">08 · EmptyState</h2>
      <Panel>
        <EmptyState
          icon="Inbox"
          title="暂无数据"
          description="这里还没有任何内容,创建后会在此展示。"
        />
      </Panel>
    </section>

    <!-- 09 Tag ---------------------------------------------------------------- -->
    <section class="ui-preview__section">
      <h2 class="ui-preview__title">09 · Tag</h2>
      <div class="ui-preview__row">
        <Tag>默认</Tag>
        <Tag variant="success">成功</Tag>
        <Tag variant="warning">警告</Tag>
        <Tag variant="danger">危险</Tag>
        <Tag variant="info">信息</Tag>
        <Tag variant="accent">强调</Tag>
      </div>
    </section>

    <!-- 10 Badge -------------------------------------------------------------- -->
    <section class="ui-preview__section">
      <h2 class="ui-preview__title">10 · Badge</h2>
      <div class="ui-preview__row">
        <Badge :value="9">
          <div class="ui-preview__badge-host" />
        </Badge>
        <Badge :value="99">
          <div class="ui-preview__badge-host" />
        </Badge>
        <Badge is-dot>
          <div class="ui-preview__badge-host" />
        </Badge>
      </div>
    </section>

    <!-- 11 StatusDot ---------------------------------------------------------- -->
    <section class="ui-preview__section">
      <h2 class="ui-preview__title">11 · StatusDot</h2>
      <div class="ui-preview__row">
        <StatusDot status="IDLE" :label="true" />
        <StatusDot status="IN_USE" :label="true" />
        <StatusDot status="MAINTENANCE" :label="true" />
        <StatusDot status="BROKEN" :label="true" />
      </div>
    </section>

    <!-- 12 StatCard ----------------------------------------------------------- -->
    <section class="ui-preview__section">
      <h2 class="ui-preview__title">12 · StatCard</h2>
      <div class="ui-preview__grid-2">
        <StatCard
          :value="1280"
          label="设备总数"
          unit="台"
          :trend="{ delta: 12, dir: 'up' }"
          icon="Monitor"
        />
        <StatCard :value="348" label="今日预约" unit="单" icon="Calendar" />
        <StatCard
          :value="6"
          label="故障设备"
          unit="台"
          :trend="{ delta: 2, dir: 'down' }"
          icon="Warning"
        />
        <StatCard :value="98" label="使用率" unit="%" :decimals="0" icon="DataLine" />
      </div>
    </section>

    <!-- 13 SegmentedControl --------------------------------------------------- -->
    <section class="ui-preview__section">
      <h2 class="ui-preview__title">13 · SegmentedControl</h2>
      <Panel>
        <SegmentedControl
          v-model="seg"
          :options="[
            { value: 'a', label: '全部' },
            { value: 'b', label: '空闲' },
            { value: 'c', label: '使用中' },
          ]"
        />
        <p class="ui-preview__caption">当前选中:{{ seg }}</p>
      </Panel>
    </section>

    <!-- 14 Timeline ----------------------------------------------------------- -->
    <section class="ui-preview__section">
      <h2 class="ui-preview__title">14 · Timeline</h2>
      <Panel>
        <Timeline
          :items="[
            { title: '创建预约', time: '10:00', status: 'done' },
            {
              title: '审批通过',
              time: '10:05',
              status: 'current',
              desc: '管理员已通过,请按时签到',
            },
            { title: '签到使用', status: 'todo' },
          ]"
        />
      </Panel>
    </section>
  </div>
</template>

<style scoped lang="scss">
// 全量走 token,无硬编码色。section gap / title 字号统一,目检网格整齐。
.ui-preview {
  display: flex;
  flex-direction: column;
  gap: 32px;

  &__section {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  &__title {
    margin: 0;
    font-family: var(--font-display);
    font-size: 15px;
    font-weight: 600;
    letter-spacing: 0.02em;
    color: var(--text-secondary);

    // 与下方示例之间加一条发丝分隔线,让目检时各 section 边界清晰
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border-subtle);
  }

  // 水平排列(按钮 / Tag / StatusDot / Badge / Skeleton 等小尺寸示例)
  &__row {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 16px;
  }

  // 2 列网格(StatCard 等中尺寸卡片)
  &__grid-2 {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 16px;
  }

  // Badge 宿主:深色小方块,让 dot/value 角标有承载体
  &__badge-host {
    width: 40px;
    height: 40px;
    background: var(--bg-elevated);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-control);
  }

  &__caption {
    margin: 12px 0 0;
    font-family: var(--font-mono);
    font-size: 12px;
    color: var(--text-tertiary);
  }
}
</style>

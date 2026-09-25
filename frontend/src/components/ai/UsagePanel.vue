<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Refresh, Coin, PieChart, User, OfficeBuilding } from '@element-plus/icons-vue'
import { getAiUsage } from '@/api/aiV2'
import type { AiUsageReport } from '@/types/aiWorkbench'

const usage = ref<AiUsageReport | null>(null)
const loading = ref(false)
const error = ref('')
onMounted(() => { void refresh() })

async function refresh() {
  loading.value = true
  error.value = ''
  try { usage.value = await getAiUsage() }
  catch (cause) { error.value = (cause as Error).message || '用量信息暂时不可用' }
  finally { loading.value = false }
}

function number(value?: number) { return new Intl.NumberFormat('zh-CN').format(value || 0) }
function percent(used = 0, cap = 0) { return cap > 0 ? Math.min(100, Math.round((used / cap) * 100)) : 0 }
</script>

<template>
  <section v-loading="loading" class="usage-panel panel-surface">
    <header class="usage-panel__head">
      <div><span class="section-kicker">AI USAGE / SHANGHAI DAY</span><h2>用量与额度</h2><p>统计按上海自然日汇总；这里只展示 Token 计量与任务数量，不读取聊天正文。</p></div>
      <el-button :icon="Refresh" :loading="loading" @click="refresh">刷新</el-button>
    </header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <template v-if="usage">
      <div class="usage-date">统计日期 <strong>{{ usage.mine.date }}</strong></div>
      <div class="usage-cards">
        <article class="usage-card"><div><span>个人已用</span><User /></div><strong>{{ number(usage.mine.used_tokens) }}</strong><small>/ {{ number(usage.mine.daily_cap) }} Token</small><el-progress :percentage="percent(usage.mine.used_tokens, usage.mine.daily_cap)" :show-text="false" :stroke-width="4" /></article>
        <article v-if="usage.college" class="usage-card"><div><span>学院已用</span><OfficeBuilding /></div><strong>{{ number(usage.college.used_tokens) }}</strong><small>/ {{ number(usage.college.daily_cap) }} Token</small><el-progress :percentage="percent(usage.college.used_tokens, usage.college.daily_cap)" :show-text="false" :stroke-width="4" /></article>
        <article v-if="usage.global" class="usage-card"><div><span>全校已用</span><PieChart /></div><strong>{{ number(usage.global.used_tokens) }}</strong><small>/ {{ number(usage.global.daily_cap) }} Token</small><el-progress :percentage="percent(usage.global.used_tokens, usage.global.daily_cap)" :show-text="false" :stroke-width="4" /></article>
      </div>
      <div class="usage-reserved"><Coin /><span>正在执行的任务已预留</span><strong>{{ number(usage.mine.reserved_tokens) }} Token</strong></div>
      <section v-if="usage.auxiliary?.length" class="usage-auxiliary">
        <div class="usage-colleges__head"><div><span class="section-kicker">DOCUMENT PIPELINE</span><h3>知识处理用量</h3></div><span>单独统计，不占聊天 Token 额度</span></div>
        <div class="usage-auxiliary__grid">
          <article v-for="item in usage.auxiliary" :key="`${item.component}-${item.operation}`" class="usage-auxiliary__item">
            <span>{{ item.component === 'mineru' ? 'MinerU 文档解析' : 'Embedding 向量处理' }}</span>
            <strong>{{ number(item.request_count) }} <small>次</small></strong>
            <small>{{ number(item.item_count) }} {{ item.component === 'mineru' ? '页 / 文件项' : '文本块' }} · {{ number(item.input_units) }} 字符 / 字节</small>
          </article>
        </div>
      </section>
      <section v-if="usage.colleges?.length" class="usage-colleges">
        <div class="usage-colleges__head"><div><span class="section-kicker">TENANT OVERVIEW</span><h3>学院用量</h3></div><span>{{ usage.colleges.length }} 个学院</span></div>
        <el-table :data="usage.colleges" stripe>
          <el-table-column prop="college_name" label="学院" min-width="180" />
          <el-table-column label="已用 Token" min-width="140"><template #default="scope">{{ number(scope.row.used_tokens) }}</template></el-table-column>
          <el-table-column label="预留 Token" min-width="140"><template #default="scope">{{ number(scope.row.reserved_tokens) }}</template></el-table-column>
          <el-table-column label="额度使用" min-width="180"><template #default="scope"><el-progress :percentage="percent(scope.row.used_tokens, scope.row.daily_cap)" :show-text="false" /><small>{{ percent(scope.row.used_tokens, scope.row.daily_cap) }}%</small></template></el-table-column>
        </el-table>
      </section>
      <div class="usage-note">额度在发起模型请求前原子预留，结束后按模型返回的输入 / 输出 Token 结算；异常结束会释放未消耗部分。</div>
    </template>
    <div v-else-if="!loading && !error" class="usage-empty"><Coin /><strong>暂时没有用量数据</strong><span>管理员启用聊天模型并配置有限额度后，这里会显示使用情况。</span></div>
  </section>
</template>

<style scoped lang="scss">
.usage-panel { min-height:0; padding:clamp(18px,2.2vw,28px); border-radius:var(--radius-card); }
.usage-panel__head,.usage-colleges__head { display:flex; align-items:flex-start; justify-content:space-between; gap:18px; }.usage-panel__head { padding-bottom:20px; border-bottom:1px solid var(--border-subtle); }.usage-panel h2 { margin:7px 0 5px; font-family:var(--font-display); font-size:23px; }.usage-panel__head p { margin:0; color:var(--text-secondary); font-size:12px; }.usage-date { margin:18px 0 12px; color:var(--text-tertiary); font-size:11px; }.usage-date strong { margin-left:8px; color:var(--text-secondary); font-family:var(--font-mono); }
.usage-cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(205px,1fr)); gap:12px; }.usage-card { padding:16px; background:var(--bg-elevated); border:1px solid var(--border-subtle); border-radius:var(--radius-card); }.usage-card > div { display:flex; align-items:center; justify-content:space-between; color:var(--text-tertiary); font-size:11px; }.usage-card svg { width:15px; color:var(--accent); }.usage-card > strong { display:block; margin:18px 0 1px; font-family:var(--font-mono); font-size:24px; font-weight:500; }.usage-card > small { display:block; margin-bottom:12px; color:var(--text-tertiary); font-size:10px; }
.usage-reserved { display:flex; align-items:center; gap:8px; margin:14px 0 26px; padding:12px 14px; color:var(--text-secondary); background:color-mix(in srgb,var(--accent) 6%,transparent); border:1px solid color-mix(in srgb,var(--accent) 14%,transparent); border-radius:9px; font-size:11px; }.usage-reserved svg { width:15px; color:var(--accent); }.usage-reserved strong { margin-left:auto; color:var(--text-primary); font-family:var(--font-mono); }
.usage-auxiliary { margin:0 0 24px; }.usage-auxiliary__grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:10px; }.usage-auxiliary__item { display:grid; gap:7px; padding:14px; border:1px solid var(--border-subtle); border-radius:10px; background:var(--bg-elevated); }.usage-auxiliary__item > span,.usage-auxiliary__item > small { color:var(--text-tertiary); font-size:10px; }.usage-auxiliary__item > strong { color:var(--text-primary); font-family:var(--font-mono); font-size:20px; font-weight:500; }.usage-auxiliary__item > strong small { color:var(--text-tertiary); font-family:var(--font-body); font-size:10px; font-weight:400; }
.usage-colleges__head { align-items:center; margin:24px 0 12px; }.usage-colleges__head h3 { margin:4px 0 0; font-size:15px; }.usage-colleges__head > span { color:var(--text-tertiary); font-size:10px; }.usage-colleges :deep(.el-table) { color:var(--text-secondary); background:transparent; }.usage-colleges :deep(.el-table tr),.usage-colleges :deep(.el-table th.el-table__cell) { background:var(--bg-elevated); }.usage-colleges :deep(.el-table td.el-table__cell),.usage-colleges :deep(.el-table th.el-table__cell) { border-color:var(--border-subtle); }.usage-colleges :deep(.el-table::before) { background:var(--border-subtle); }.usage-colleges small { color:var(--text-tertiary); }
.usage-note { margin-top:20px; color:var(--text-tertiary); font-size:10px; line-height:1.6; }.usage-empty { display:grid; place-items:center; gap:9px; padding:75px 18px; color:var(--text-tertiary); text-align:center; }.usage-empty svg { width:28px; height:28px; color:var(--accent); }.usage-empty strong { color:var(--text-primary); }
</style>

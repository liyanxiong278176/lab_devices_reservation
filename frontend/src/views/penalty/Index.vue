<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import PageHeader from '@/components/ui/PageHeader.vue'
import {
  addOverdueFollowUp,
  escalateOverdue,
  getGraceBounds,
  getPenaltyPolicy,
  listCollegePenalties,
  listOverdueCases,
  listPenaltyAppeals,
  myPenaltyBalance,
  myPenalties,
  reviewPenaltyAppeal,
  saveGraceBounds,
  savePenaltyPolicy,
  submitPenaltyAppeal,
  type AppealResult,
  type GraceBounds,
  type OverdueCase,
  type PenaltyAppeal,
  type PenaltyCase,
  type PenaltyTier,
  type ViolationType,
} from '@/api/penalties'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()
const loading = ref(false)
const submitting = ref(false)
const activeTab = ref('mine')
const ownCases = ref<PenaltyCase[]>([])
const currentPoints = ref<number | null>(null)
const canManageRules = ref(false)
const hasCollegeAdminAccess = ref(false)
const policyVersion = ref<number | null>(null)
const effectiveAt = ref<string | null>(null)
const graceDays = ref(0)
const ruleTiers = ref<Record<ViolationType, PenaltyTier[]>>({
  NO_SHOW: [],
  OVERDUE_RETURN: [],
  MANUAL_VIOLATION: [],
})
const adminCases = ref<PenaltyCase[]>([])
const adminCaseTotal = ref(0)
const casePage = ref(1)
const appeals = ref<PenaltyAppeal[]>([])
const appealTotal = ref(0)
const appealPage = ref(1)
const overdueCases = ref<OverdueCase[]>([])
const overdueTotal = ref(0)
const overduePage = ref(1)
const graceBounds = ref<GraceBounds>({ minimum_days: 0, maximum_days: 30 })
const showGraceBounds = computed(() => userStore.hasRole('SYS_ADMIN'))
const violationOptions: Array<{ type: ViolationType; label: string; description: string }> = [
  { type: 'NO_SHOW', label: '预约爽约', description: '已审批预约首日未完成设备交接' },
  { type: 'OVERDUE_RETURN', label: '逾期未还', description: '超过学院宽限期仍未提交归还' },
  { type: 'MANUAL_VIOLATION', label: '其他违规', description: '管理员核实后手动登记的违规' },
]

const appealDialog = ref(false)
const appealCase = ref<PenaltyCase | null>(null)
const appealReason = ref('')
const appealEvidence = ref('')
const reviewDialog = ref(false)
const reviewAppeal = ref<PenaltyAppeal | null>(null)
const reviewResult = ref<AppealResult>('MAINTAIN')
const reviewReason = ref('')
const reviewPoints = ref(0)
const reviewBlockDays = ref(0)
const followUpDialog = ref(false)
const followUpCase = ref<OverdueCase | null>(null)
const followUpResult = ref('')
const followUpContactedAt = ref('')

const typeLabel = (type: ViolationType) =>
  violationOptions.find((item) => item.type === type)?.label || type

const dateTime = (value?: string | null) => {
  if (!value) return '—'
  const normalized = value.replace(' ', 'T')
  const hasZone = /(?:Z|[+-]\d\d:\d\d)$/i.test(normalized)
  return new Date(hasZone ? normalized : `${normalized}Z`).toLocaleString('zh-CN', { hour12: false })
}

const localDateTimeInput = (value = new Date()) =>
  new Date(value.getTime() - value.getTimezoneOffset() * 60_000).toISOString().slice(0, 19)

const canAppeal = (row: PenaltyCase) => {
  const latest = row.appeals?.at(-1)
  return row.status === 'ACTIVE' && row.appeal_count! < 3 && latest?.status !== 'PENDING'
}

async function loadMine() {
  if (userStore.collegeId === null) return
  const [balance, cases] = await Promise.all([myPenaltyBalance(), myPenalties()])
  currentPoints.value = balance.points
  ownCases.value = cases
}

async function loadCollegeAdminData() {
  try {
    const policy = await getPenaltyPolicy()
    canManageRules.value = policy.can_manage
    hasCollegeAdminAccess.value = policy.can_review
    policyVersion.value = policy.version
    effectiveAt.value = policy.effective_at
    graceDays.value = policy.grace_days ?? 0
    graceBounds.value = {
      minimum_days: policy.minimum_grace_days,
      maximum_days: policy.maximum_grace_days,
    }
    ruleTiers.value = {
      NO_SHOW: [...(policy.tiers?.NO_SHOW || [])],
      OVERDUE_RETURN: [...(policy.tiers?.OVERDUE_RETURN || [])],
      MANUAL_VIOLATION: [...(policy.tiers?.MANUAL_VIOLATION || [])],
    }
    if (!policy.can_review) return
  } catch {
    canManageRules.value = false
    hasCollegeAdminAccess.value = false
    return
  }
  const results = await Promise.allSettled([
    listCollegePenalties(casePage.value, 20),
    listPenaltyAppeals(true, appealPage.value, 20),
    listOverdueCases(overduePage.value, 20),
  ])
  const [caseResult, appealResult, overdueResult] = results
  if (caseResult.status === 'fulfilled') {
    adminCases.value = caseResult.value.items
    adminCaseTotal.value = caseResult.value.total
  }
  if (appealResult.status === 'fulfilled') {
    appeals.value = appealResult.value.items
    appealTotal.value = appealResult.value.total
  }
  if (overdueResult.status === 'fulfilled') {
    overdueCases.value = overdueResult.value.items
    overdueTotal.value = overdueResult.value.total
  }
}

async function load() {
  loading.value = true
  try {
    await loadMine()
    if (showGraceBounds.value) {
      try {
        graceBounds.value = await getGraceBounds()
      } catch {
        // 系统管理员设置项按接口授权展示。
      }
    } else if (userStore.collegeId !== null) {
      await loadCollegeAdminData()
    }
  } catch {
    // 请求拦截器负责提示网络和服务端错误。
  } finally {
    loading.value = false
  }
}

function addTier(type: ViolationType) {
  const rows = ruleTiers.value[type]
  if (rows.length >= 20) return
  rows.push({ occurrence: rows.length + 1, points: 0, block_days: 0 })
}

function removeTier(type: ViolationType, index: number) {
  ruleTiers.value[type].splice(index, 1)
  ruleTiers.value[type].forEach((row, rowIndex) => { row.occurrence = rowIndex + 1 })
}

async function savePolicy() {
  submitting.value = true
  try {
    const saved = await savePenaltyPolicy({ grace_days: graceDays.value, tiers: ruleTiers.value })
    policyVersion.value = saved.version
    effectiveAt.value = saved.effective_at
    ElMessage.success('学院处罚规则已保存并立即生效')
    await loadCollegeAdminData()
  } catch {
    // 请求拦截器已显示错误。
  } finally {
    submitting.value = false
  }
}

async function saveBounds() {
  submitting.value = true
  try {
    graceBounds.value = await saveGraceBounds(graceBounds.value)
    ElMessage.success('学院逾期宽限期范围已更新')
  } catch {
    // 请求拦截器已显示错误。
  } finally {
    submitting.value = false
  }
}

function openAppeal(row: PenaltyCase) {
  appealCase.value = row
  appealReason.value = ''
  appealEvidence.value = ''
  appealDialog.value = true
}

async function sendAppeal() {
  if (!appealCase.value || !appealReason.value.trim()) {
    ElMessage.warning('请填写申诉理由')
    return
  }
  submitting.value = true
  try {
    await submitPenaltyAppeal(appealCase.value.id, {
      reason: appealReason.value.trim(),
      evidence: appealEvidence.value.trim() || undefined,
    })
    ElMessage.success('申诉已提交，复核结果会通过通知中心送达')
    appealDialog.value = false
    await loadMine()
  } catch {
    // 请求拦截器已显示错误。
  } finally {
    submitting.value = false
  }
}

function openReview(row: PenaltyAppeal) {
  reviewAppeal.value = row
  reviewResult.value = 'MAINTAIN'
  reviewReason.value = ''
  reviewPoints.value = Math.max(0, -(row.penalty_points_delta ?? 0))
  reviewBlockDays.value = row.penalty_block_days ?? 0
  reviewDialog.value = true
}

async function submitReview() {
  if (!reviewAppeal.value || !reviewReason.value.trim()) {
    ElMessage.warning('请填写复核理由')
    return
  }
  submitting.value = true
  try {
    await reviewPenaltyAppeal(reviewAppeal.value.id, {
      result: reviewResult.value,
      result_reason: reviewReason.value.trim(),
      ...(reviewResult.value === 'ADJUST'
        ? { points_deduction: reviewPoints.value, block_days: reviewBlockDays.value }
        : {}),
    })
    ElMessage.success('申诉复核已完成，结果已通知用户')
    reviewDialog.value = false
    await loadCollegeAdminData()
    await loadMine()
  } catch {
    // 请求拦截器已显示错误。
  } finally {
    submitting.value = false
  }
}

function openFollowUp(row: OverdueCase) {
  followUpCase.value = row
  followUpResult.value = ''
  followUpContactedAt.value = localDateTimeInput()
  followUpDialog.value = true
}

async function submitFollowUp() {
  if (!followUpCase.value || !followUpResult.value.trim() || !followUpContactedAt.value) {
    ElMessage.warning('请填写联系时间和结果')
    return
  }
  submitting.value = true
  try {
    await addOverdueFollowUp(followUpCase.value.id, {
      result: followUpResult.value.trim(),
      contacted_at: new Date(followUpContactedAt.value).toISOString(),
    })
    ElMessage.success('跟进记录已保存')
    followUpDialog.value = false
    await loadCollegeAdminData()
  } catch {
    // 请求拦截器已显示错误。
  } finally {
    submitting.value = false
  }
}

async function escalate(row: OverdueCase) {
  try {
    const { value } = await ElMessageBox.prompt(
      '说明多次联系仍未追回设备的情况。升级后用户在本学院的新预约和新领用会暂停。',
      `升级逾期案件 #${row.id}`,
      { inputType: 'textarea', inputValidator: (value) => Boolean(value.trim()) || '请填写原因' },
    )
    await escalateOverdue(row.id, value.trim())
    ElMessage.success('逾期案件已升级，用户已收到通知')
    await loadCollegeAdminData()
  } catch {
    // 用户取消提示框时不提交。
  }
}

async function changeCasePage(value: number) {
  casePage.value = value
  await loadCollegeAdminData()
}

async function changeAppealPage(value: number) {
  appealPage.value = value
  await loadCollegeAdminData()
}

async function changeOverduePage(value: number) {
  overduePage.value = value
  await loadCollegeAdminData()
}

onMounted(() => {
  if (showGraceBounds.value) activeTab.value = 'system'
  void load()
})
</script>

<template>
  <div class="penalty-page" v-loading="loading">
    <PageHeader
      title="违规与申诉"
      subtitle="查看学院预约违规处罚、提交申诉，或处理设备逾期未还。规则仅在所属学院内生效。"
    />

    <section class="penalty-summary">
      <div>
        <span class="penalty-kicker">规则生效</span>
        <strong>{{ policyVersion ? `学院规则 v${policyVersion}` : '尚未配置学院规则' }}</strong>
        <small>{{ effectiveAt ? `自 ${dateTime(effectiveAt)} 起生效` : '学院负责人可配置统一处罚规则' }}</small>
      </div>
      <div>
        <span class="penalty-kicker">本院信用分</span>
        <strong>{{ currentPoints ?? '—' }}</strong>
        <small>仅统计当前所属学院的积分</small>
      </div>
      <div>
        <span class="penalty-kicker">我的处罚</span>
        <strong>{{ ownCases.length }}</strong>
        <small>最近记录，申诉进度和结果在此查看</small>
      </div>
      <div v-if="hasCollegeAdminAccess">
        <span class="penalty-kicker">待处理申诉</span>
        <strong>{{ appealTotal }}</strong>
        <small>逾期案件 {{ overdueTotal }} 件</small>
      </div>
    </section>

    <el-tabs v-model="activeTab" class="penalty-tabs">
      <el-tab-pane label="我的处罚" name="mine">
        <el-empty v-if="!ownCases.length && !loading" description="暂无违规处罚记录" />
        <article v-for="row in ownCases" :key="row.id" class="penalty-card">
          <div class="penalty-card__top">
            <div>
              <el-tag type="warning" effect="dark">{{ typeLabel(row.violation_type) }}</el-tag>
              <strong>第 {{ row.occurrence_number }} 次 · {{ row.device_name }}</strong>
            </div>
            <el-tag :type="row.status === 'REVOKED' ? 'success' : 'danger'" effect="plain">
              {{ row.status === 'REVOKED' ? '已撤销' : '处罚生效中' }}
            </el-tag>
          </div>
          <p>{{ row.reason }}</p>
          <div class="penalty-card__facts">
            <span>实验室：{{ row.lab_name || '未关联实验室' }}</span>
            <span>扣分：{{ Math.max(0, -row.points_delta) }}</span>
            <span>暂停预约：{{ row.reservation_block_days }} 天</span>
            <span>发生时间：{{ dateTime(row.event_at) }}</span>
          </div>
          <div v-if="row.appeals?.length" class="appeal-history">
            <div v-for="appeal in row.appeals" :key="appeal.id" class="appeal-history__row">
              <span>第 {{ appeal.attempt_number }} 次申诉 · {{ dateTime(appeal.submitted_at) }}</span>
              <el-tag :type="appeal.status === 'PENDING' ? 'warning' : 'info'" size="small">
                {{ appeal.status === 'PENDING' ? '待复核' : `已处理：${appeal.result || ''}` }}
              </el-tag>
              <small v-if="appeal.result_reason">{{ appeal.result_reason }}</small>
            </div>
          </div>
          <div class="penalty-card__actions">
            <el-button
              v-if="canAppeal(row)"
              type="primary"
              plain
              @click="openAppeal(row)"
            >
              {{ row.appeal_count ? '再次申诉' : '提交申诉' }}
              <span v-if="row.appeal_count">（还可 {{ 3 - row.appeal_count }} 次）</span>
            </el-button>
            <el-button v-else-if="row.status === 'ACTIVE' && row.appeal_count === 3" disabled>
              已达到 3 次申诉上限
            </el-button>
          </div>
        </article>
      </el-tab-pane>

      <el-tab-pane v-if="hasCollegeAdminAccess" label="学院处理" name="college">
        <el-alert
          title="同一类违规全院使用统一规则。只有学院负责人能制定规则；管理员可以复核申诉和跟进逾期案件。保存的新规则立即生效并保留操作记录。"
          type="info"
          :closable="false"
          show-icon
          class="penalty-alert"
        />

        <section v-if="canManageRules" class="policy-panel">
          <header class="section-heading">
            <div><h2>学院处罚规则</h2><p>滚动三个月统计同类违规次数，按阶梯自动处罚。</p></div>
            <el-tag effect="plain">{{ policyVersion ? `当前版本 v${policyVersion}` : '首次配置' }}</el-tag>
          </header>
          <el-form label-position="top" class="policy-form">
            <el-form-item label="逾期归还宽限期（自然日）">
              <el-input-number v-model="graceDays" :min="0" :max="365" />
              <small>系统管理员允许范围：{{ graceBounds.minimum_days }}–{{ graceBounds.maximum_days }} 天</small>
            </el-form-item>
          </el-form>
          <div v-for="option in violationOptions" :key="option.type" class="tier-section">
            <header>
              <div><strong>{{ option.label }}</strong><small>{{ option.description }}</small></div>
              <el-button size="small" @click="addTier(option.type)">添加阶梯</el-button>
            </header>
            <div v-if="!ruleTiers[option.type].length" class="tier-empty">尚未配置阶梯</div>
            <div v-for="(tier, index) in ruleTiers[option.type]" :key="`${option.type}-${index}`" class="tier-row">
              <span>第 {{ tier.occurrence }} 次及以上</span>
              <label>扣分 <el-input-number v-model="tier.points" :min="0" :max="100" size="small" /></label>
              <label>暂停预约天数 <el-input-number v-model="tier.block_days" :min="0" :max="365" size="small" /></label>
              <el-button text type="danger" @click="removeTier(option.type, index)">移除</el-button>
            </div>
          </div>
          <div class="policy-footer">
            <span>新规则仅用于生效时间之后发生的违规。</span>
            <el-button type="primary" :loading="submitting" @click="savePolicy">保存并立即生效</el-button>
          </div>
        </section>

        <section class="admin-panel">
          <header class="section-heading"><div><h2>待复核申诉</h2><p>处理结果会即时更新处罚，并通知用户。</p></div></header>
          <el-empty v-if="!appeals.length" description="当前没有待复核申诉" />
          <article v-for="row in appeals" :key="row.id" class="review-row">
            <div><strong>{{ row.user_name }} · {{ typeLabel(row.violation_type!) }} · 预约 #{{ row.reservation_id }}</strong><p>{{ row.reason }}</p><small>{{ row.device_name }} · 提交于 {{ dateTime(row.submitted_at) }}</small><small v-if="row.evidence">补充材料：{{ row.evidence }}</small></div>
            <el-button type="primary" @click="openReview(row)">复核</el-button>
          </article>
          <el-pagination
            v-if="appealTotal > 20"
            :current-page="appealPage"
            :page-size="20"
            :total="appealTotal"
            layout="prev, pager, next"
            @current-change="changeAppealPage"
          />
        </section>

        <section class="admin-panel">
          <header class="section-heading"><div><h2>逾期未还跟进</h2><p>记录联系时间和结果；至少一次跟进后可升级给学院负责人。</p></div></header>
          <el-empty v-if="!overdueCases.length" description="当前没有未结案逾期设备" />
          <article v-for="row in overdueCases" :key="row.id" class="review-row overdue-row">
            <div>
              <strong>{{ row.user_name }} · {{ row.device_name }} · 预约 #{{ row.reservation_id }}</strong>
              <p>{{ row.lab_name || '未关联实验室' }} · 逾期开始 {{ dateTime(row.started_at) }} · 宽限至 {{ dateTime(row.grace_deadline_at) }}</p>
              <small>状态：{{ row.status }} · 已记录 {{ row.followups.length }} 次联系</small>
              <small v-if="row.escalation_reason">升级原因：{{ row.escalation_reason }}</small>
              <small v-for="follow in row.followups" :key="follow.id">{{ dateTime(follow.contacted_at) }} · {{ follow.operator_name }}：{{ follow.result }}</small>
            </div>
            <div class="row-actions">
              <el-button size="small" @click="openFollowUp(row)">记录联系</el-button>
              <el-button
                v-if="!row.escalated_at"
                size="small"
                type="danger"
                plain
                :disabled="row.followups.length === 0"
                @click="escalate(row)"
              >升级处理</el-button>
            </div>
          </article>
          <el-pagination
            v-if="overdueTotal > 20"
            :current-page="overduePage"
            :page-size="20"
            :total="overdueTotal"
            layout="prev, pager, next"
            @current-change="changeOverduePage"
          />
        </section>

        <section class="admin-panel">
          <header class="section-heading"><div><h2>学院处罚记录</h2><p>仅展示本学院违规和自动处罚记录。</p></div></header>
          <el-table :data="adminCases" stripe row-key="id">
            <el-table-column label="用户 / 违规" min-width="180">
              <template #default="{ row }"><strong>{{ row.user_name }}</strong><small class="table-sub">{{ typeLabel(row.violation_type) }} · 第 {{ row.occurrence_number }} 次</small></template>
            </el-table-column>
            <el-table-column prop="device_name" label="设备" min-width="140" />
            <el-table-column label="处罚" min-width="150">
              <template #default="{ row }">扣 {{ Math.max(0, -row.points_delta) }} 分 · 暂停 {{ row.reservation_block_days }} 天</template>
            </el-table-column>
            <el-table-column label="发生时间" min-width="170"><template #default="{ row }">{{ dateTime(row.event_at) }}</template></el-table-column>
            <el-table-column prop="status" label="状态" width="100" />
          </el-table>
          <el-pagination
            v-if="adminCaseTotal > 20"
            :current-page="casePage"
            :page-size="20"
            :total="adminCaseTotal"
            layout="prev, pager, next"
            @current-change="changeCasePage"
          />
        </section>
      </el-tab-pane>

      <el-tab-pane v-if="showGraceBounds" label="全校参数" name="system">
        <section class="policy-panel system-panel">
          <header class="section-heading"><div><h2>学院宽限期可配置范围</h2><p>系统管理员只维护范围；各学院负责人在范围内设置本院统一宽限期。</p></div></header>
          <el-form label-position="top" class="bounds-form">
            <el-form-item label="最短宽限期（自然日）"><el-input-number v-model="graceBounds.minimum_days" :min="0" :max="365" /></el-form-item>
            <el-form-item label="最长宽限期（自然日）"><el-input-number v-model="graceBounds.maximum_days" :min="0" :max="365" /></el-form-item>
          </el-form>
          <el-button type="primary" :loading="submitting" @click="saveBounds">保存范围</el-button>
        </section>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="appealDialog" title="提交处罚申诉" width="min(560px, 94vw)" destroy-on-close>
      <p v-if="appealCase">对预约 #{{ appealCase.reservation_id }} 的{{ typeLabel(appealCase.violation_type) }}处罚提出申诉。</p>
      <el-form label-position="top">
        <el-form-item label="申诉理由" required><el-input v-model="appealReason" type="textarea" :rows="5" maxlength="2000" show-word-limit /></el-form-item>
        <el-form-item label="补充材料（可选）"><el-input v-model="appealEvidence" type="textarea" :rows="3" maxlength="2000" show-word-limit /></el-form-item>
      </el-form>
      <template #footer><el-button @click="appealDialog = false">取消</el-button><el-button type="primary" :loading="submitting" @click="sendAppeal">提交申诉</el-button></template>
    </el-dialog>

    <el-dialog v-model="reviewDialog" title="复核处罚申诉" width="min(560px, 94vw)" destroy-on-close>
      <div v-if="reviewAppeal" class="review-context">{{ reviewAppeal.user_name }} 对预约 #{{ reviewAppeal.reservation_id }} 的{{ typeLabel(reviewAppeal.violation_type!) }}处罚提出申诉：{{ reviewAppeal.reason }}</div>
      <el-form label-position="top">
        <el-form-item label="复核结果"><el-radio-group v-model="reviewResult"><el-radio-button value="MAINTAIN">维持</el-radio-button><el-radio-button value="ADJUST">调整</el-radio-button><el-radio-button value="REVOKE">撤销</el-radio-button></el-radio-group></el-form-item>
        <template v-if="reviewResult === 'ADJUST'"><el-form-item label="调整后扣分"><el-input-number v-model="reviewPoints" :min="0" :max="100" /></el-form-item><el-form-item label="调整后预约暂停天数"><el-input-number v-model="reviewBlockDays" :min="0" :max="365" /></el-form-item></template>
        <el-form-item label="处理理由" required><el-input v-model="reviewReason" type="textarea" :rows="4" maxlength="2000" show-word-limit /></el-form-item>
      </el-form>
      <template #footer><el-button @click="reviewDialog = false">取消</el-button><el-button type="primary" :loading="submitting" @click="submitReview">提交复核结果</el-button></template>
    </el-dialog>

    <el-dialog v-model="followUpDialog" title="记录逾期联系" width="min(560px, 94vw)" destroy-on-close>
      <p v-if="followUpCase">案件 #{{ followUpCase.id }} · {{ followUpCase.user_name }} · {{ followUpCase.device_name }}</p>
      <el-form label-position="top">
        <el-form-item label="实际联系时间" required><el-date-picker v-model="followUpContactedAt" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" /></el-form-item>
        <el-form-item label="联系结果" required><el-input v-model="followUpResult" type="textarea" :rows="5" maxlength="1000" placeholder="记录联系方式、用户反馈和后续安排" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="followUpDialog = false">取消</el-button><el-button type="primary" :loading="submitting" @click="submitFollowUp">保存跟进</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
.penalty-page { display: grid; gap: 20px; min-width: 0; }
.penalty-summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); overflow: hidden; border: 1px solid var(--border-default); border-radius: var(--radius-card); background: var(--bg-surface); }
.penalty-summary > div { display: grid; gap: 5px; min-height: 106px; padding: 20px 24px; border-right: 1px solid var(--border-subtle); }
.penalty-summary > div:last-child { border: 0; }
.penalty-kicker { color: var(--text-tertiary); font-size: 11px; letter-spacing: .08em; text-transform: uppercase; }
.penalty-summary strong { color: var(--text-primary); font-size: 19px; }
.penalty-summary small, .section-heading p, .tier-section small { color: var(--text-secondary); line-height: 1.55; }
.penalty-tabs { min-width: 0; }
.penalty-tabs :deep(.el-tabs__content) { overflow: visible; }
.penalty-card, .policy-panel, .admin-panel { margin-bottom: 16px; padding: 22px; border: 1px solid var(--border-default); border-radius: var(--radius-card); background: var(--bg-surface); }
.penalty-card__top, .penalty-card__top > div, .penalty-card__facts, .penalty-card__actions, .section-heading, .tier-section > header, .tier-row, .policy-footer, .review-row, .row-actions { display: flex; align-items: center; gap: 12px; }
.penalty-card__top, .section-heading, .tier-section > header, .policy-footer, .review-row { justify-content: space-between; }
.penalty-card__top strong { color: var(--text-primary); }
.penalty-card p, .review-row p { margin: 12px 0; color: var(--text-secondary); line-height: 1.65; }
.penalty-card__facts { flex-wrap: wrap; color: var(--text-tertiary); font-size: 12px; }
.penalty-card__actions { justify-content: flex-end; margin-top: 16px; }
.appeal-history { display: grid; gap: 8px; margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--border-subtle); }
.appeal-history__row { display: grid; grid-template-columns: 1fr auto; gap: 4px 12px; color: var(--text-secondary); font-size: 12px; }
.appeal-history__row small { grid-column: 1 / -1; color: var(--text-tertiary); }
.section-heading { margin-bottom: 16px; }
.section-heading h2 { margin: 0 0 5px; color: var(--text-primary); font-size: 18px; }
.section-heading p { margin: 0; font-size: 13px; }
.policy-alert { margin-bottom: 16px; }
.policy-form { max-width: 460px; }
.policy-form small { margin-left: 12px; color: var(--text-tertiary); }
.tier-section { padding: 16px 0; border-top: 1px solid var(--border-subtle); }
.tier-section > header > div { display: grid; gap: 4px; }
.tier-section strong { color: var(--text-primary); }
.tier-section small { font-size: 12px; }
.tier-empty { padding: 16px 0 4px; color: var(--text-tertiary); font-size: 13px; }
.tier-row { flex-wrap: wrap; justify-content: flex-end; padding: 12px 0 0; color: var(--text-secondary); font-size: 13px; }
.tier-row > span { margin-right: auto; color: var(--text-primary); }
.tier-row label { display: flex; align-items: center; gap: 8px; }
.policy-footer { padding-top: 18px; border-top: 1px solid var(--border-subtle); color: var(--text-tertiary); font-size: 12px; }
.review-row { align-items: flex-start; padding: 16px 0; border-top: 1px solid var(--border-subtle); }
.review-row > div:first-child { min-width: 0; }
.review-row strong { color: var(--text-primary); }
.review-row small { display: block; margin-top: 5px; color: var(--text-tertiary); line-height: 1.5; }
.overdue-row .row-actions { flex: none; }
.bounds-form { display: flex; gap: 20px; }
.review-context { margin-bottom: 16px; padding: 12px; border-radius: 8px; background: var(--bg-subtle); color: var(--text-secondary); line-height: 1.6; }
.table-sub { display: block; margin-top: 4px; color: var(--text-tertiary); }
@media (max-width: 760px) {
  .penalty-summary { grid-template-columns: 1fr; }
  .penalty-summary > div { min-height: auto; border-right: 0; border-bottom: 1px solid var(--border-subtle); }
  .penalty-card__top, .review-row, .policy-footer { align-items: flex-start; flex-direction: column; }
  .bounds-form { flex-direction: column; gap: 0; }
}
</style>

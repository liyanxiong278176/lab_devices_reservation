const { execFileSync } = require('node:child_process')
const path = require('node:path')
const { test, expect } = require('../../frontend/node_modules/@playwright/test')
const {
  api,
  dateAfter,
  fillReservationForm,
  fixture,
  openReservation,
  qaRoot,
  signIn,
  snap,
} = require('./support.cjs')

const tenant = fixture('e2e-penalty10')

async function createAppointment(user, deviceId, deviceName, startDate, purpose) {
  await openReservation(user, deviceId, deviceName)
  await fillReservationForm(user, startDate, startDate, purpose)
  await snap(user, '04-penalties', '02', 'user', `reservation_${purpose}`)
  const createdResponse = user.waitForResponse((response) =>
    response.url().endsWith('/api/v2/reservations') &&
    response.request().method() === 'POST',
  )
  await user.getByRole('button', { name: '提交预约', exact: true }).click()
  const created = await createdResponse
  const createdBody = await created.json()
  expect(created.status(), JSON.stringify(createdBody)).toBe(201)
  await user.waitForURL(/\/reservations\/mine/)
  const page = await api(user, '/reservations/mine?page=1&page_size=100')
  expect(page.status).toBe(200)
  const row = page.payload.data.items.find((item) => item.purpose === purpose)
  expect(row, `reservation for ${purpose} was saved`).toBeTruthy()
  return row.id
}

async function approveAppointment(manager, reservationId, purpose) {
  await manager.goto('/approvals/pending')
  const card = manager.locator('.approval__card').filter({ hasText: purpose })
  await expect(card).toBeVisible()
  await card.getByRole('button', { name: '通过', exact: true }).click()
  await expect(card).toHaveCount(0)
  const saved = await api(manager, `/reservations/${reservationId}`)
  expect(saved.status).toBe(200)
  expect(saved.payload.data.status).toBe('APPROVED')
}

async function submitAppeal(user, attempt, reason) {
  const card = user.locator('.penalty-card').filter({ hasText: '预约爽约' })
  await expect(card).toBeVisible()
  const label = attempt === 1 ? /提交申诉/ : /再次申诉/
  await card.getByRole('button', { name: label }).click()
  const dialog = user.getByRole('dialog', { name: '提交处罚申诉' })
  await expect(dialog).toBeVisible()
  await dialog.locator('textarea').nth(0).fill(reason)
  await dialog.locator('textarea').nth(1).fill(`QA 第 ${attempt} 次申诉的补充材料`)
  await snap(user, '04-penalties', `0${5 + attempt}`, 'user', `appeal_${attempt}_before_submit`)
  const response = user.waitForResponse((item) =>
    item.url().includes('/api/v2/penalties/cases/') &&
    item.url().includes('/appeals') &&
    item.request().method() === 'POST',
  )
  await dialog.getByRole('button', { name: '提交申诉', exact: true }).click()
  const result = await response
  expect(result.status()).toBe(201)
  await expect(dialog).toBeHidden()
  await expect(card).toContainText('待复核')
  await snap(user, '04-penalties', `0${5 + attempt}`, 'user', `appeal_${attempt}_submitted`)
}

async function reviewAppeal(manager, attempt, reason, outcome) {
  await manager.reload()
  await manager.goto('/penalties')
  await manager.getByRole('tab', { name: '学院处理' }).click()
  const row = manager.locator('.review-row').filter({ hasText: reason })
  await expect(row).toBeVisible()
  await row.getByRole('button', { name: '复核', exact: true }).click()
  const dialog = manager.getByRole('dialog', { name: '复核处罚申诉' })
  await expect(dialog).toBeVisible()
  const outcomeLabel = { MAINTAIN: '维持', ADJUST: '调整', REVOKE: '撤销' }[outcome]
  await dialog.locator('.el-radio-button').filter({ hasText: outcomeLabel }).click()
  await dialog.locator('textarea').fill(`学院负责人完成第 ${attempt} 次申诉复核，核对相关预约和交接记录。`)
  await snap(manager, '04-penalties', `1${attempt}`, 'manager', `appeal_${attempt}_review_dialog`)
  const response = manager.waitForResponse((item) =>
    item.url().includes('/api/v2/penalties/appeals/') &&
    item.url().includes('/review') &&
    item.request().method() === 'POST',
  )
  await dialog.getByRole('button', { name: '提交复核结果', exact: true }).click()
  const result = await response
  expect(result.status()).toBe(200)
  const body = await result.json()
  expect(body.data.result).toBe(outcome)
  await expect(dialog).toBeHidden()
  await snap(manager, '04-penalties', `1${attempt}`, 'manager', `appeal_${attempt}_reviewed`)
  return body.data
}

test('college policy, automatic no-show penalty, lab restriction, three appeals, and rebooking', async ({ browser }) => {
  const managerContext = await browser.newContext()
  const userContext = await browser.newContext()
  const manager = await managerContext.newPage()
  const user = await userContext.newPage()
  let missedReservationId
  let futureReservationId

  try {
    await signIn(manager, tenant.manager_username, '04-penalties', 'manager')
    await manager.goto('/penalties')
    await manager.getByRole('tab', { name: '学院处理' }).click()
    const noShow = manager.locator('.tier-section').filter({ hasText: '预约爽约' })
    const overdue = manager.locator('.tier-section').filter({ hasText: '逾期未还' })
    await noShow.getByRole('button', { name: '添加阶梯', exact: true }).click()
    await overdue.getByRole('button', { name: '添加阶梯', exact: true }).click()
    await noShow.locator('.tier-row').first().locator('input').nth(0).fill('15')
    await noShow.locator('.tier-row').first().locator('input').nth(1).fill('3')
    await overdue.locator('.tier-row').first().locator('input').nth(0).fill('0')
    await overdue.locator('.tier-row').first().locator('input').nth(1).fill('0')
    await snap(manager, '04-penalties', '01', 'manager', 'college_policy_before_save')
    const saveResponse = manager.waitForResponse((response) =>
      response.url().includes('/api/v2/penalties/policy') && response.request().method() === 'PUT',
    )
    await manager.getByRole('button', { name: '保存并立即生效', exact: true }).click()
    const savedPolicy = await saveResponse
    expect(savedPolicy.status()).toBe(200)
    const policyBody = await savedPolicy.json()
    expect(policyBody.data.version).toBe(1)
    expect(policyBody.data.tiers.NO_SHOW[0]).toMatchObject({ points: 15, block_days: 3 })
    await expect(manager.locator('.penalty-summary')).toContainText('学院规则 v1')
    await snap(manager, '04-penalties', '01', 'manager', 'college_policy_active')

    await signIn(user, tenant.username, '04-penalties', 'user')
    const today = dateAfter(0)
    const futureDate = dateAfter(2)
    const stamp = Date.now()
    const missedPurpose = `qa-no-show-${stamp}`
    const futurePurpose = `qa-future-booking-${stamp}`
    missedReservationId = await createAppointment(
      user, tenant.device_id, tenant.device_name, today, missedPurpose,
    )
    futureReservationId = await createAppointment(
      user, tenant.second_device_id, tenant.second_device_name, futureDate, futurePurpose,
    )
    await snap(user, '04-penalties', '03', 'user', 'appointments_submitted')

    await approveAppointment(manager, missedReservationId, missedPurpose)
    await approveAppointment(manager, futureReservationId, futurePurpose)
    await snap(manager, '04-penalties', '04', 'manager', 'appointments_approved')

    const triggerScript = path.join(qaRoot, 'scripts', 'trigger_no_show.py')
    const workerEvidence = JSON.parse(execFileSync(
      'uv', ['run', 'python', triggerScript, String(missedReservationId)],
      {
        cwd: path.resolve(qaRoot, '..', 'backend'),
        encoding: 'utf8',
        timeout: 60_000,
        windowsHide: true,
      },
    ).trim())
    expect(workerEvidence).toMatchObject({
      reservation_status: 'NO_SHOW',
      outbox_status: 'COMPLETED',
      violation_type: 'NO_SHOW',
      points_delta: -15,
      reservation_block_days: 3,
      scope_lab_id: expect.any(Number),
    })

    const userCases = await api(user, '/penalties/mine')
    expect(userCases.status).toBe(200)
    const penalty = userCases.payload.data.find((item) => item.reservation_id === missedReservationId)
    expect(penalty).toBeTruthy()
    expect(penalty).toMatchObject({ status: 'ACTIVE', points_delta: -15, reservation_block_days: 3 })
    const balance = await api(user, '/penalties/balance')
    expect(balance.payload.data.points).toBe(85)
    const canceledFuture = await api(user, `/reservations/${futureReservationId}`)
    expect(canceledFuture.payload.data.status).toBe('CANCELLED')
    const blockedBooking = await api(user, '/reservations', {
      method: 'POST',
      idempotencyKey: `qa-penalty-block-${stamp}`,
      body: {
        device_id: tenant.second_device_id,
        start_date: dateAfter(1),
        end_date: dateAfter(1),
        purpose: `qa-blocked-by-penalty-${stamp}`,
        purpose_category: 'OTHER',
      },
    })
    expect(blockedBooking.status).toBe(403)
    expect(blockedBooking.payload.code).toBe('BOOKING_RESTRICTED')
    await user.goto('/penalties')
    const userPenaltyCard = user.locator('.penalty-card').filter({ hasText: '预约爽约' })
    await expect(userPenaltyCard).toContainText('扣分：15')
    await expect(userPenaltyCard).toContainText('暂停预约：3 天')
    await snap(user, '04-penalties', '04', 'user', 'automatic_penalty_and_lab_block')

    const reasons = [
      `请复核第 1 次爽约处罚 ${stamp}，我希望重新核对交接记录。`,
      `请复核第 2 次爽约处罚 ${stamp}，补充核对预约记录。`,
      `请复核第 3 次爽约处罚 ${stamp}，提交最后一轮材料。`,
    ]
    await submitAppeal(user, 1, reasons[0])
    await expect(manager.locator('.el-notification__title').filter({ hasText: '收到新的处罚申诉' })).toBeVisible({ timeout: 20_000 })
    await snap(manager, '04-penalties', '08', 'manager', 'appeal_notification_center')
    const first = await reviewAppeal(manager, 1, reasons[0], 'MAINTAIN')
    expect(first.attempt_number).toBe(1)
    await user.reload()
    await expect(user.locator('.penalty-card').filter({ hasText: '预约爽约' })).toContainText('已处理：MAINTAIN')
    await expect(user.locator('.penalty-card').filter({ hasText: '预约爽约' }).getByRole('button', { name: /再次申诉.*还可 2 次/ })).toBeVisible()
    await snap(user, '04-penalties', '09', 'user', 'first_appeal_maintained')

    await submitAppeal(user, 2, reasons[1])
    const second = await reviewAppeal(manager, 2, reasons[1], 'MAINTAIN')
    expect(second.attempt_number).toBe(2)
    await user.reload()
    await expect(user.locator('.penalty-card').filter({ hasText: '预约爽约' }).getByRole('button', { name: /再次申诉.*还可 1 次/ })).toBeVisible()
    await snap(user, '04-penalties', '10', 'user', 'second_appeal_maintained')

    await submitAppeal(user, 3, reasons[2])
    const third = await reviewAppeal(manager, 3, reasons[2], 'REVOKE')
    expect(third.attempt_number).toBe(3)
    await user.reload()
    const finalCard = user.locator('.penalty-card').filter({ hasText: '预约爽约' })
    await expect(finalCard).toContainText('已撤销')
    const restoredBalance = await api(user, '/penalties/balance')
    expect(restoredBalance.payload.data.points).toBe(100)
    const stillCanceled = await api(user, `/reservations/${futureReservationId}`)
    expect(stillCanceled.payload.data.status).toBe('CANCELLED')
    await snap(user, '04-penalties', '11', 'user', 'third_appeal_revoked_penalty')

    const rebookPurpose = `qa-rebook-after-revocation-${stamp}`
    const rebookedId = await createAppointment(
      user, tenant.second_device_id, tenant.second_device_name, futureDate, rebookPurpose,
    )
    const rebooked = await api(user, `/reservations/${rebookedId}`)
    expect(rebooked.payload.data.status).toBe('PENDING')
    await expect(user.locator('.mine__card').filter({ hasText: rebookPurpose })).toContainText('待审批')
    await snap(user, '04-penalties', '12', 'user', 'rebook_requires_new_application')

    console.log(JSON.stringify({
      evidence: 'P1-P8',
      policyVersion: policyBody.data.version,
      missedReservation: workerEvidence.reservation_status,
      penaltyPoints: penalty.points_delta,
      restrictionScopeLabId: workerEvidence.scope_lab_id,
      existingApprovedReservationAfterPenalty: canceledFuture.payload.data.status,
      activePenaltyBookingAttempt: blockedBooking.status,
      appeals: [first.result, second.result, third.result],
      creditAfterRevoke: restoredBalance.payload.data.points,
      canceledReservationRestored: stillCanceled.payload.data.status !== 'CANCELLED',
      replacementReservation: rebooked.payload.data.status,
    }))
  } finally {
    await managerContext.close()
    await userContext.close()
  }
})

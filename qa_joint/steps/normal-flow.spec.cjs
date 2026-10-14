const { test, expect } = require('../../frontend/node_modules/@playwright/test')
const {
  api,
  dateAfter,
  fillReservationForm,
  fixture,
  listenApiErrors,
  openReservation,
  pngBuffer,
  showApiResult,
  signIn,
  snap,
} = require('./support.cjs')

const primary = fixture('e2e-joint01')
const purpose = 'qa-joint-S2-' + dateAfter(0)
const repairTitle = 'qa-joint-S8-' + dateAfter(0)
const png = pngBuffer()
const scenarioDeviceId = primary.second_device_id
const scenarioDeviceName = primary.second_device_name

test('S1-S8 real user/admin reservation, handover, return, feedback, and repair', async ({ browser }) => {
  const userContext = await browser.newContext()
  const adminContext = await browser.newContext()
  const user = await userContext.newPage()
  const admin = await adminContext.newPage()
  const userErrors = listenApiErrors(user)
  const adminErrors = listenApiErrors(admin)
  let reservationId
  let repairId
  try {
    await signIn(user, primary.username, '01-normal', 'user')
    await signIn(admin, primary.admin_username, '01-normal', 'admin')

    for (const page of [user, admin]) {
      await page.goto('/devices')
      const card = page.locator('.device-card').filter({
        has: page.locator('.device-card__brand').getByText(primary.device_name, { exact: true }),
      })
      await expect(card).toBeVisible()
      await expect(card.getByRole('button', { name: '预约', exact: true })).toBeEnabled()
      await snap(page, '01-normal', '03', page === user ? 'user' : 'admin', 'device_visible')
    }

    await openReservation(user, scenarioDeviceId, scenarioDeviceName)
    await fillReservationForm(user, dateAfter(0), dateAfter(0), purpose)
    await snap(user, '01-normal', '04', 'user', 'reservation_before_submit')
    const submit = user.getByRole('button', { name: '提交预约', exact: true })
    await expect(submit).toBeEnabled()
    await submit.click()
    await user.waitForURL(/\/reservations\/mine/)
    const mine = await api(user, '/reservations/mine?page=1&page_size=100')
    expect(mine.status).toBe(200)
    const created = mine.payload.data.items.find((item) => item.purpose === purpose)
    expect(created).toBeTruthy()
    reservationId = created.id
    await expect(user.locator('.mine__card').filter({ hasText: purpose })).toContainText('待审批')
    await snap(user, '01-normal', '05', 'user', 'reservation_pending_approval')

    await admin.goto('/approvals/pending')
    const approval = admin.locator('.approval__card').filter({ hasText: purpose })
    await expect(approval).toBeVisible()
    await snap(admin, '01-normal', '06', 'admin', 'approval_pending')

    await approval.getByRole('button', { name: '通过', exact: true }).click()
    await expect(admin.locator('.approval__card').filter({ hasText: purpose })).toHaveCount(0)
    const approved = await api(admin, '/reservations/' + reservationId)
    expect(approved.status).toBe(200)
    expect(approved.payload.data.status).toBe('APPROVED')
    await snap(admin, '01-normal', '07', 'admin', 'approval_complete')

    // The user page remains open while approval commits; this proves the real
    // backend outbox -> notification store -> SSE -> browser UI delivery path.
    await expect(user.locator('.el-notification__title').filter({ hasText: '预约申请已通过' })).toBeVisible()
    await snap(user, '01-normal', '07', 'user', 'approval_sse_notification')
    await user.reload()
    const approvedCard = user.locator('.mine__card').filter({ hasText: purpose })
    await expect(approvedCard.locator('.mine__card-head')).toContainText('已通过')
    await expect(approvedCard).toContainText('等待负责人交接')
    await expect(approvedCard.getByRole('button', { name: '归还', exact: true })).toHaveCount(0)
    await expect(approvedCard.getByRole('button', { name: '签到', exact: true })).toHaveCount(0)
    await snap(user, '01-normal', '08', 'user', 'approved_waiting_handover')

    for (const [path, method, body] of [
      ['/reservations/' + reservationId + '/check-in', 'POST', undefined],
      ['/reservations/' + reservationId + '/return', 'POST', { condition: 'NORMAL', image_urls: ['/uploads/not-uploaded.png'] }],
    ]) {
      const result = await api(user, path, { method, body })
      expect(result.status).toBeGreaterThanOrEqual(400)
      await showApiResult(user, result, method, path)
      await snap(user, '02-boundaries', '01', 'user', 'pre_handover_' + (path.includes('check-in') ? 'checkin' : 'return'), 'err')
    }

    await admin.goto('/handovers')
    const pendingHandover = admin.locator('.handover-card').filter({ hasText: purpose })
    await expect(pendingHandover).toBeVisible()
    await pendingHandover.getByRole('button', { name: '核对并完成交接', exact: true }).click()
    const handoverDialog = admin.getByRole('dialog', { name: '完成设备交接' })
    await expect(handoverDialog).toBeVisible()
    await snap(admin, '01-normal', '09', 'admin', 'handover_dialog_before')
    await handoverDialog.locator('input[type="file"]').setInputFiles({
      name: 'handover.png',
      mimeType: 'image/png',
      buffer: png,
    })
    await expect(handoverDialog.getByText('1 张已选择', { exact: true })).toBeVisible()
    await snap(admin, '01-normal', '10', 'admin', 'handover_photo_selected')
    const handoverResponse = admin.waitForResponse((response) =>
      response.url().includes('/api/v2/reservations/' + reservationId + '/handover') && response.request().method() === 'POST',
    )
    await handoverDialog.getByRole('button', { name: '确认', exact: true }).click()
    expect((await handoverResponse).status()).toBe(200)
    const inUse = await api(admin, '/reservations/' + reservationId)
    expect(inUse.payload.data.status).toBe('IN_USE')
    await snap(admin, '01-normal', '11', 'admin', 'handover_complete')

    await user.reload()
    const inUseCard = user.locator('.mine__card').filter({ hasText: purpose })
    await expect(inUseCard).toContainText('使用中')
    await expect(inUseCard.getByRole('button', { name: '归还', exact: true })).toBeVisible()
    await snap(user, '01-normal', '12', 'user', 'in_use')
    await inUseCard.getByRole('button', { name: '归还', exact: true }).click()
    const returnDialog = user.getByRole('dialog', { name: '提交归还' })
    await expect(returnDialog).toBeVisible()
    await snap(user, '01-normal', '13', 'user', 'return_dialog_before')
    await returnDialog.locator('input[type="file"]').setInputFiles({
      name: 'return.png',
      mimeType: 'image/png',
      buffer: png,
    })
    await expect(returnDialog.getByText('1 张已选择', { exact: true })).toBeVisible()
    const returnResponse = user.waitForResponse((response) =>
      response.url().includes('/api/v2/reservations/' + reservationId + '/return') && response.request().method() === 'POST',
    )
    await returnDialog.getByRole('button', { name: '确认归还', exact: true }).click()
    expect((await returnResponse).status()).toBe(200)
    const returned = await api(user, '/reservations/' + reservationId)
    expect(returned.payload.data.status).toBe('IN_USE')
    expect(returned.payload.data.handover_status).toBe('RETURN_PENDING')
    await expect(user.locator('.mine__card').filter({ hasText: purpose })).toContainText('待负责人验收')
    await snap(user, '01-normal', '14', 'user', 'return_pending_acceptance')

    const duplicateReturn = await api(user, '/reservations/' + reservationId + '/return', {
      method: 'POST',
      body: { condition: 'NORMAL', image_urls: returned.payload.data.return_image_urls },
    })
    expect(duplicateReturn.status).toBeGreaterThanOrEqual(400)
    await showApiResult(user, duplicateReturn, 'POST', '/reservations/' + reservationId + '/return')
    await snap(user, '02-boundaries', '02', 'user', 'duplicate_return', 'err')

    await admin.goto('/handovers')
    await admin.getByText('待验收', { exact: true }).click()
    const pendingAcceptance = admin.locator('.handover-card').filter({ hasText: purpose })
    await expect(pendingAcceptance).toBeVisible()
    await pendingAcceptance.getByRole('button', { name: '核对并确认验收', exact: true }).click()
    const acceptanceDialog = admin.getByRole('dialog', { name: '确认归还验收' })
    await expect(acceptanceDialog.getByText('打开照片', { exact: true })).toBeVisible()
    await snap(admin, '01-normal', '15', 'admin', 'acceptance_dialog_before')
    const acceptanceResponse = admin.waitForResponse((response) =>
      response.url().includes('/api/v2/reservations/' + reservationId + '/accept-return') && response.request().method() === 'POST',
    )
    await acceptanceDialog.getByRole('button', { name: '确认', exact: true }).click()
    expect((await acceptanceResponse).status()).toBe(200)
    const completed = await api(admin, '/reservations/' + reservationId)
    expect(completed.payload.data.status).toBe('COMPLETED')
    await snap(admin, '01-normal', '16', 'admin', 'return_accepted')
    await user.goto('/reservations/mine')
    const completedCard = user.locator('.mine__card').filter({ hasText: purpose })
    await expect(completedCard.locator('.mine__card-head')).toContainText('已完成')
    await expect(user.locator('.mine__grid .el-loading-mask')).toBeHidden()
    await snap(user, '01-normal', '17', 'user', 'reservation_completed')

    await completedCard.getByRole('button', { name: '详情', exact: true }).click()
    await user.waitForURL(new RegExp('/reservations/' + reservationId + '$'))
    await user.getByRole('button', { name: '评价设备', exact: true }).click()
    const feedbackDialog = user.getByRole('dialog', { name: '评价本次使用' })
    await feedbackDialog.getByPlaceholder('分享一下设备状态或使用体验（可选）').fill('qa_joint 全链路使用反馈')
    await snap(user, '01-normal', '18', 'user', 'feedback_before_submit')
    const feedbackResponse = user.waitForResponse((response) =>
      response.url().includes('/api/v2/reservations/' + reservationId + '/feedback') && response.request().method() === 'POST',
    )
    await feedbackDialog.getByRole('button', { name: '提交评价', exact: true }).click()
    expect((await feedbackResponse).status()).toBe(201)
    await expect(user.getByText('使用评价', { exact: true })).toBeVisible()
    await snap(user, '01-normal', '19', 'user', 'feedback_submitted')

    await user.goto('/repairs/submit')
    await expect(user.getByRole('heading', { name: '提交报修', exact: true })).toBeVisible()
    await user.locator('.rsubmit__el-form .el-select').click()
    await user.locator('.el-select-dropdown__item').filter({ hasText: '#' + scenarioDeviceId + ' · ' + scenarioDeviceName }).first().click()
    await user.getByPlaceholder('一句话描述故障').fill(repairTitle)
    await user.getByPlaceholder('故障现象、复现步骤等').fill('S8 真实前后端联调报修闭环')
    await snap(user, '01-normal', '20', 'user', 'repair_before_submit')
    const repairCreateResponse = user.waitForResponse((response) =>
      response.url().includes('/api/v2/repair-reports') && !response.url().includes('/mine') && response.request().method() === 'POST',
    )
    await user.getByRole('button', { name: '提交报修', exact: true }).click()
    expect((await repairCreateResponse).status()).toBe(201)
    await user.waitForURL(/\/repairs\/mine/)
    const repairs = await api(user, '/repair-reports/mine?page=1&size=100')
    const repair = repairs.payload.data.items.find((item) => item.title === repairTitle)
    expect(repair).toBeTruthy()
    repairId = repair.id
    await expect(user.locator('.rmine__card').filter({ hasText: repairTitle })).toBeVisible()
    await snap(user, '01-normal', '21', 'user', 'repair_pending')

    const deviceUnderRepair = await api(admin, '/devices/' + scenarioDeviceId)
    expect(deviceUnderRepair.status).toBe(200)
    expect(deviceUnderRepair.payload.data.status).toBe('MAINTENANCE')
    const maintenanceBooking = await api(user, '/reservations', {
      method: 'POST',
      idempotencyKey: 'qa-joint-maintenance-' + Date.now(),
      body: {
        device_id: scenarioDeviceId,
        start_date: dateAfter(2),
        end_date: dateAfter(2),
        purpose: 'qa-joint-maintenance-guard',
        purpose_category: 'OTHER',
      },
    })
    expect(maintenanceBooking.status, JSON.stringify(maintenanceBooking.payload)).toBe(409)
    expect(maintenanceBooking.payload.code).toBe('RESERVATION_CONFLICT')
    expect(maintenanceBooking.payload.data.conflicts.some((item) => item.reason.includes('MAINTENANCE'))).toBe(true)
    await user.goto('/devices')
    await showApiResult(user, maintenanceBooking, 'POST', '/reservations')
    await snap(user, '03-repair-errors', '02', 'user', 'reserve_maintenance_device', 'err')

    const prematureResolve = await api(admin, '/repair-reports/' + repairId + '/resolve', {
      method: 'POST',
      body: { resolution_note: 'premature resolve check' },
    })
    expect(prematureResolve.status).toBeGreaterThanOrEqual(400)
    await admin.goto('/repairs')
    await showApiResult(admin, prematureResolve, 'POST', '/repair-reports/' + repairId + '/resolve')
    await snap(admin, '03-repair-errors', '01', 'admin', 'resolve_before_take', 'err')

    const repairRow = admin.locator('.el-table__row').filter({ hasText: repairTitle })
    await expect(repairRow).toBeVisible()
    await snap(admin, '01-normal', '22', 'admin', 'repair_pending')
    await repairRow.getByRole('button', { name: '受理', exact: true }).click()
    await expect(repairRow.getByRole('button', { name: '解决', exact: true })).toBeVisible()
    await snap(admin, '01-normal', '23', 'admin', 'repair_taken')
    await repairRow.getByRole('button', { name: '解决', exact: true }).click()
    await admin.getByPlaceholder('说明处理方式与结果(必填)').fill('已完成实验设备检查与修复')
    await snap(admin, '01-normal', '24', 'admin', 'repair_resolution_before')
    const resolveResponse = admin.waitForResponse((response) =>
      response.url().includes('/api/v2/repair-reports/' + repairId + '/resolve') && response.request().method() === 'POST',
    )
    await admin.getByRole('button', { name: '确认处理', exact: true }).click()
    expect((await resolveResponse).status()).toBe(200)
    await snap(admin, '01-normal', '25', 'admin', 'repair_resolved')

    await user.goto('/repairs/mine')
    const resolvedCard = user.locator('.rmine__card').filter({ hasText: repairTitle })
    await expect(resolvedCard.getByRole('button', { name: '确认已修复', exact: true })).toBeVisible()
    await snap(user, '01-normal', '26', 'user', 'repair_waiting_confirmation')
    await resolvedCard.getByRole('button', { name: '确认已修复', exact: true }).click()
    const confirmDialog = user.getByRole('dialog', { name: '确认维修结果' })
    await expect(confirmDialog).toBeVisible()
    const confirmResponse = user.waitForResponse((response) =>
      response.url().includes('/api/v2/repair-reports/' + repairId + '/confirm') && response.request().method() === 'POST',
    )
    await confirmDialog.getByRole('button', { name: '确认已修复', exact: true }).click()
    expect((await confirmResponse).status()).toBe(200)
    const completedRepairs = await api(user, '/repair-reports/mine?page=1&size=100')
    expect(completedRepairs.payload.data.items.find((item) => item.id === repairId).status).toBe('COMPLETED')
    await expect(user.locator('.rmine__card').filter({ hasText: repairTitle })).toContainText('已完成')
    await snap(user, '01-normal', '27', 'user', 'repair_completed')

    const device = await api(admin, '/devices/' + scenarioDeviceId)
    expect(device.status).toBe(200)
    expect(device.payload.data.status).toBe('IDLE')

    const adminFeedback = await api(admin, '/reservations/' + reservationId + '/feedback')
    const cookieFlags = await userContext.cookies('http://127.0.0.1:5173/api/v2/auth/me')
    const accessCookie = cookieFlags.find((cookie) => cookie.name === 'lab_access')
    const csrfCookie = cookieFlags.find((cookie) => cookie.name === 'lab_csrf')
    console.log(JSON.stringify({
      evidence: 'S1-S8',
      reservation: completed.payload.data.status,
      reservationDate: completed.payload.data.start_date,
      feedback: adminFeedback.status === 200 && Boolean(adminFeedback.payload.data),
      repairStatus: completedRepairs.payload.data.items.find((item) => item.id === repairId).status,
      maintenanceDevice: device.payload.data.status,
      accessCookie: accessCookie ? { httpOnly: accessCookie.httpOnly, sameSite: accessCookie.sameSite } : null,
      csrfCookie: csrfCookie ? { httpOnly: csrfCookie.httpOnly, sameSite: csrfCookie.sameSite } : null,
      frontendApiErrors: userErrors.length + adminErrors.length,
    }))
  } finally {
    await userContext.close()
    await adminContext.close()
  }
})

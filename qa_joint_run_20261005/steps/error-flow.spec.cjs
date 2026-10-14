const { test, expect } = require('../../frontend/node_modules/@playwright/test')
const {
  api,
  databaseReservationsForPurpose,
  dateAfter,
  fillDateRange,
  fillReservationForm,
  fixture,
  openReservation,
  showApiResult,
  signIn,
  snap,
} = require('./support.cjs')

const primary = fixture('e2e-joint09')
const foreign = fixture('e2e-joint10')
const responsePath = (pathname) => (response) =>
  response.url().includes('/api/v2' + pathname) && response.request().method() === 'POST'

test('E1 rejects empty, wrong-password, and injection login attempts', async ({ browser }) => {
  const userContext = await browser.newContext()
  const adminContext = await browser.newContext()
  const emptyContext = await browser.newContext()
  const user = await userContext.newPage()
  const admin = await adminContext.newPage()
  const empty = await emptyContext.newPage()
  try {
    await user.goto('/login')
    await user.getByLabel('用户名').fill(primary.username)
    await user.getByLabel('密码').fill('wrong-password')
    await snap(user, '04-errors', 'E1-01', 'user', 'wrong_password_before', 'err')
    await user.getByRole('button', { name: '登录', exact: true }).click()
    await expect(user.locator('.el-message--error')).toBeVisible()
    await expect(user).toHaveURL(/\/login/)
    await snap(user, '04-errors', 'E1-02', 'user', 'wrong_password_rejected', 'err')

    await admin.goto('/login')
    await admin.getByLabel('用户名').fill("' OR '1'='1")
    await admin.getByLabel('密码').fill('incorrect')
    await admin.getByRole('button', { name: '登录', exact: true }).click()
    await expect(admin.locator('.el-message--error')).toBeVisible()
    await expect(admin).toHaveURL(/\/login/)
    await snap(admin, '04-errors', 'E1-03', 'admin', 'sql_injection_rejected', 'err')
    await expect(admin.getByText("' OR '1'='1", { exact: true })).toHaveCount(0)

    await empty.goto('/login')
    await empty.getByRole('button', { name: '登录', exact: true }).click()
    await expect(empty.locator('.el-form-item__error').first()).toBeVisible()
    await expect(empty).toHaveURL(/\/login/)
    await snap(empty, '04-errors', 'E1-04', 'user', 'empty_credentials_rejected', 'err')
    console.log(JSON.stringify({ evidence: 'E1', cases: 3, outcome: 'rejected' }))
  } finally {
    await userContext.close()
    await adminContext.close()
    await emptyContext.close()
  }
})

test('E2 validates reversed, past, over-limit, empty, and oversized reservation input', async ({ browser }) => {
  const context = await browser.newContext()
  const page = await context.newPage()
  try {
    await signIn(page, primary.username, '04-errors', 'user')
    await openReservation(page, primary.device_id, primary.device_name)
    await fillDateRange(page, dateAfter(0), dateAfter(0))
    await page.getByPlaceholder('例如：完成材料拉伸实验并采集三组数据').fill('')
    await page.getByPlaceholder('例如：完成材料拉伸实验并采集三组数据').blur()
    const submit = page.getByRole('button', { name: '提交预约', exact: true })
    await expect(submit).toBeDisabled()
    await snap(page, '04-errors', 'E2-01', 'user', 'empty_purpose_frontend_block', 'err')

    const cases = [
      {
        name: 'reversed_dates',
        body: {
          device_id: primary.device_id,
          start_date: dateAfter(0),
          end_date: dateAfter(-1),
          purpose: 'E2 reversed date validation',
          purpose_category: 'OTHER',
        },
      },
      {
        name: 'past_date',
        body: {
          device_id: primary.device_id,
          start_date: dateAfter(-7),
          end_date: dateAfter(-7),
          purpose: 'E2 past date validation',
          purpose_category: 'OTHER',
        },
      },
      {
        name: 'over_eight_days',
        body: {
          device_id: primary.device_id,
          start_date: dateAfter(0),
          end_date: dateAfter(30),
          purpose: 'E2 max length policy validation',
          purpose_category: 'OTHER',
        },
      },
      {
        name: 'empty_purpose',
        body: {
          device_id: primary.device_id,
          start_date: dateAfter(4),
          end_date: dateAfter(4),
          purpose: '',
          purpose_category: 'OTHER',
        },
      },
      {
        name: 'oversized_purpose',
        body: {
          device_id: primary.device_id,
          start_date: dateAfter(4),
          end_date: dateAfter(4),
          purpose: 'x'.repeat(501),
          purpose_category: 'OTHER',
        },
      },
    ]
    for (const [index, item] of cases.entries()) {
      const result = await api(page, '/reservations/preflight', { method: 'POST', body: item.body })
      expect(result.status, item.name + ' should be rejected by the real API').toBeGreaterThanOrEqual(400)
      await showApiResult(page, result, 'POST', '/reservations/preflight')
      await snap(page, '04-errors', 'E2-' + String(index + 2).padStart(2, '0'), 'user', item.name, 'err')
    }
    console.log(JSON.stringify({ evidence: 'E2', cases: cases.map((item) => item.name), outcome: 'rejected' }))
  } finally {
    await context.close()
  }
})

test('E3 concurrent conflict is enforced by MySQL and E4/E5 scope and approval errors are visible', async ({ browser }) => {
  const userContext = await browser.newContext()
  const user2Context = await browser.newContext()
  const adminContext = await browser.newContext()
  const managerContext = await browser.newContext()
  const foreignContext = await browser.newContext()
  const user = await userContext.newPage()
  const user2 = await user2Context.newPage()
  const admin = await adminContext.newPage()
  const manager = await managerContext.newPage()
  const foreignUser = await foreignContext.newPage()
  const purpose = 'qa-joint-E3-' + dateAfter(0) + '-' + Date.now()
  let winnerId
  let foreignReservationId
  try {
    await Promise.all([
      signIn(user, primary.username, '05-concurrency', 'user'),
      signIn(user2, primary.alternate_username, '05-concurrency', 'user2'),
    ])
    await Promise.all([
      openReservation(user, primary.device_id, primary.device_name),
      openReservation(user2, primary.device_id, primary.device_name),
    ])
    await Promise.all([
      fillReservationForm(user, dateAfter(0), dateAfter(0), purpose),
      fillReservationForm(user2, dateAfter(0), dateAfter(0), purpose),
    ])
    await snap(user, '05-concurrency', 'E3-01', 'user', 'same_date_ready')
    await snap(user2, '05-concurrency', 'E3-02', 'user2', 'same_date_ready')
    const waitCreate = (page) => page.waitForResponse((response) =>
      response.url().endsWith('/api/v2/reservations') && response.request().method() === 'POST',
    )
    const userResponsePromise = waitCreate(user)
    const user2ResponsePromise = waitCreate(user2)
    await Promise.all([
      user.getByRole('button', { name: '提交预约', exact: true }).click(),
      user2.getByRole('button', { name: '提交预约', exact: true }).click(),
    ])
    const [userResponse, user2Response] = await Promise.all([userResponsePromise, user2ResponsePromise])
    const statuses = [userResponse.status(), user2Response.status()].sort()
    expect(statuses).toEqual([201, 409])
    const winnerPage = userResponse.status() === 201 ? user : user2
    const loserPage = userResponse.status() === 409 ? user : user2
    await winnerPage.waitForURL(/\/reservations\/mine/)
    await expect(loserPage.locator('.el-message--error')).toBeVisible()
    await snap(winnerPage, '05-concurrency', 'E3-03', winnerPage === user ? 'user' : 'user2', 'concurrent_winner')
    await snap(loserPage, '05-concurrency', 'E3-04', loserPage === user ? 'user' : 'user2', 'concurrent_conflict', 'err')

    const winnerRows = await api(winnerPage, '/reservations/mine?page=1&page_size=100')
    const created = winnerRows.payload.data.items.filter((item) => item.purpose === purpose)
    expect(created).toHaveLength(1)
    winnerId = created[0].id
    const db = databaseReservationsForPurpose(purpose)
    expect(db.count).toBe(1)
    expect(db.reservations).toHaveLength(1)
    expect(db.reservations[0].reservation_days).toBe(1)

    await signIn(admin, primary.admin_username, '05-concurrency', 'admin')
    await admin.goto('/approvals/pending')
    const adminApprovals = await api(admin, '/approvals/pending?page=1&page_size=100')
    expect(adminApprovals.payload.data.items.filter((item) => item.purpose === purpose)).toHaveLength(1)
    await snap(admin, '05-concurrency', 'E3-05', 'admin', 'only_one_pending')

    await winnerPage.goto('/approvals/pending')
    await expect(winnerPage).toHaveURL(/\/dashboard/)
    await snap(winnerPage, '06-scope-approval', 'E4-01', 'user', 'management_url_denied', 'err')
    const userPendingDenied = await api(winnerPage, '/approvals/pending')
    expect(userPendingDenied.status).toBe(403)
    await showApiResult(winnerPage, userPendingDenied, 'GET', '/approvals/pending')
    await snap(winnerPage, '06-scope-approval', 'E4-02', 'user', 'approval_api_denied', 'err')

    await signIn(foreignUser, foreign.username, '06-scope-approval', 'user2')
    const foreignCreate = await api(foreignUser, '/reservations', {
      method: 'POST',
      idempotencyKey: 'qa-joint-E4-foreign-' + Date.now(),
      body: {
        device_id: foreign.device_id,
        start_date: dateAfter(4),
        end_date: dateAfter(4),
        purpose: 'qa-joint-E4-foreign-' + Date.now(),
        purpose_category: 'OTHER',
      },
    })
    expect(foreignCreate.status, JSON.stringify(foreignCreate.payload)).toBe(201)
    foreignReservationId = foreignCreate.payload.data.created[0].id
    const foreignDetail = await api(winnerPage, '/reservations/' + foreignReservationId)
    expect([403, 404]).toContain(foreignDetail.status)
    await showApiResult(winnerPage, foreignDetail, 'GET', '/reservations/' + foreignReservationId)
    await snap(winnerPage, '06-scope-approval', 'E4-03', 'user', 'foreign_reservation_denied', 'err')

    const firstApproval = await api(admin, '/approvals/' + winnerId + '/approve', { method: 'POST', body: {} })
    expect(firstApproval.status).toBe(200)
    const duplicateApproval = await api(admin, '/approvals/' + winnerId + '/approve', { method: 'POST', body: {} })
    expect(duplicateApproval.status).toBe(409)
    await showApiResult(admin, duplicateApproval, 'POST', '/approvals/' + winnerId + '/approve')
    await snap(admin, '06-scope-approval', 'E5-01', 'admin', 'duplicate_approval', 'err')

    const cancelledCreate = await api(winnerPage, '/reservations', {
      method: 'POST',
      idempotencyKey: 'qa-joint-E5-cancelled-' + Date.now(),
      body: {
        device_id: primary.device_id,
        start_date: dateAfter(2),
        end_date: dateAfter(2),
        purpose: 'qa-joint-E5-cancelled-' + Date.now(),
        purpose_category: 'OTHER',
      },
    })
    expect(cancelledCreate.status).toBe(201)
    const cancelledId = cancelledCreate.payload.data.created[0].id
    const cancelled = await api(winnerPage, '/reservations/' + cancelledId + '/cancel', { method: 'POST' })
    expect(cancelled.status).toBe(200)
    const cancelledApproval = await api(admin, '/approvals/' + cancelledId + '/approve', { method: 'POST', body: {} })
    expect(cancelledApproval.status).toBe(409)
    const cancelledDetail = await api(winnerPage, '/reservations/' + cancelledId)
    expect(cancelledDetail.payload.data.status).toBe('CANCELLED')
    await showApiResult(admin, cancelledApproval, 'POST', '/approvals/' + cancelledId + '/approve')
    await snap(admin, '06-scope-approval', 'E5-02', 'admin', 'cancelled_approval_denied', 'err')

    const missingApproval = await api(admin, '/approvals/999999999/approve', { method: 'POST', body: {} })
    expect(missingApproval.status).toBe(404)
    await showApiResult(admin, missingApproval, 'POST', '/approvals/999999999/approve')
    await snap(admin, '06-scope-approval', 'E5-03', 'admin', 'missing_approval_denied', 'err')

    await signIn(manager, primary.manager_username, '06-scope-approval', 'manager')
    await manager.goto('/approvals/pending')
    const crossCollegeApproval = await api(manager, '/approvals/' + foreignReservationId + '/approve', {
      method: 'POST',
      body: {},
    })
    expect([403, 404]).toContain(crossCollegeApproval.status)
    await showApiResult(manager, crossCollegeApproval, 'POST', '/approvals/' + foreignReservationId + '/approve')
    await snap(manager, '06-scope-approval', 'E5-04', 'manager', 'foreign_approval_denied', 'err')
    console.log(JSON.stringify({
      evidence: 'E3-E5',
      concurrentStatuses: statuses,
      reservationsInDatabase: db.count,
      duplicateApproval: duplicateApproval.status,
      cancelledApproval: cancelledApproval.status,
      missingApproval: missingApproval.status,
      managerCrossCollegeApproval: crossCollegeApproval.status,
    }))
  } finally {
    await userContext.close()
    await user2Context.close()
    await adminContext.close()
    await managerContext.close()
    await foreignContext.close()
  }
})

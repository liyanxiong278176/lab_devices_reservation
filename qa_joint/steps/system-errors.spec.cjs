const { execFileSync } = require('node:child_process')
const { test, expect } = require('../../frontend/node_modules/@playwright/test')
const {
  api,
  databaseReservationsForPurpose,
  dateAfter,
  fillReservationForm,
  fixture,
  openReservation,
  qaRoot,
  showApiResult,
  signIn,
  snap,
} = require('./support.cjs')
const path = require('node:path')

const primary = fixture('e2e-joint01')
const cycleBackend = (action) => execFileSync('powershell.exe', [
  '-NoProfile',
  '-ExecutionPolicy',
  'Bypass',
  '-File',
  path.join(qaRoot, 'scripts', 'cycle-backend.ps1'),
  '-Action',
  action,
], { stdio: 'ignore', timeout: 240_000, windowsHide: true })

test('E8 backend outage is shown in both browser sessions and recovers without data changes', async ({ browser }) => {
  const userContext = await browser.newContext()
  const adminContext = await browser.newContext()
  const user = await userContext.newPage()
  const admin = await adminContext.newPage()
  let stopped = false
  try {
    await signIn(user, primary.username, '07-recovery', 'user')
    await signIn(admin, primary.admin_username, '07-recovery', 'admin')
    await user.goto('/devices')
    await admin.goto('/approvals/pending')
    await snap(user, '07-recovery', 'E8-01', 'user', 'backend_before_outage')
    await snap(admin, '07-recovery', 'E8-02', 'admin', 'backend_before_outage')

    cycleBackend('Stop')
    stopped = true
    const userFailure = await api(user, '/devices')
    const adminFailure = await api(admin, '/approvals/pending')
    expect(userFailure.status === 0 || userFailure.status >= 500).toBe(true)
    expect(adminFailure.status === 0 || adminFailure.status >= 500).toBe(true)
    await showApiResult(user, userFailure, 'GET', '/devices')
    await showApiResult(admin, adminFailure, 'GET', '/approvals/pending')
    await snap(user, '07-recovery', 'E8-03', 'user', 'backend_unavailable', 'err')
    await snap(admin, '07-recovery', 'E8-04', 'admin', 'backend_unavailable', 'err')

    try {
      cycleBackend('Start')
    } catch (error) {
      const health = await api(user, '/live')
      if (health.status !== 200) throw error
    }
    stopped = false
    const userRecovered = await api(user, '/auth/me')
    const adminRecovered = await api(admin, '/auth/me')
    expect(userRecovered.status).toBe(200)
    expect(adminRecovered.status).toBe(200)
    await user.goto('/devices')
    await expect(user.locator('.device-card')).toHaveCount(2)
    await admin.goto('/approvals/pending')
    await expect(admin.getByRole('heading', { name: '待审批', exact: true })).toBeVisible()
    await snap(user, '07-recovery', 'E8-05', 'user', 'backend_recovered')
    await snap(admin, '07-recovery', 'E8-06', 'admin', 'backend_recovered')
    console.log(JSON.stringify({ evidence: 'E8', outageResponses: [userFailure.status, adminFailure.status], recovery: [userRecovered.status, adminRecovered.status] }))
  } finally {
    if (stopped) cycleBackend('Start')
    await userContext.close()
    await adminContext.close()
  }
})

test('E9 logout revokes the browser session and browser back returns to login', async ({ browser }) => {
  const context = await browser.newContext()
  const page = await context.newPage()
  try {
    await signIn(page, primary.username, '08-session', 'user')
    await page.goto('/reservations/mine')
    await snap(page, '08-session', 'E9-01', 'user', 'session_active')
    await page.getByRole('button', { name: '退出登录', exact: true }).click()
    await page.waitForURL(/\/login(?:\?.*)?$/)
    await snap(page, '08-session', 'E9-02', 'user', 'logout_complete', 'err')
    await page.goBack()
    await expect(page).toHaveURL(/\/login(?:\?.*)?$/)
    await page.goto('/reservations/mine')
    await expect(page).toHaveURL(/\/login\?redirect=/)
    const me = await api(page, '/auth/me')
    expect(me.status).toBe(401)
    await snap(page, '08-session', 'E9-03', 'user', 'back_and_expired_access', 'err')
    console.log(JSON.stringify({ evidence: 'E9', meAfterLogout: me.status, currentPath: new URL(page.url()).pathname }))
  } finally {
    await context.close()
  }
})

test('E10 missing CSRF and forged Origin are rejected and no reservation row is written', async ({ browser }) => {
  const context = await browser.newContext()
  const page = await context.newPage()
  const missingPurpose = 'qa-joint-E10-missing-csrf-' + Date.now()
  const forgedPurpose = 'qa-joint-E10-forged-origin-' + Date.now()
  try {
    await signIn(page, primary.username, '09-write-protection', 'user')
    const missingCsrf = await api(page, '/reservations', {
      method: 'POST',
      csrf: false,
      body: {
        device_id: primary.device_id,
        start_date: dateAfter(5),
        end_date: dateAfter(5),
        purpose: missingPurpose,
        purpose_category: 'OTHER',
      },
    })
    expect(missingCsrf.status).toBe(403)
    expect(missingCsrf.payload.code).toBe('CSRF_TOKEN_INVALID')
    await page.goto('/devices')
    await showApiResult(page, missingCsrf, 'POST', '/reservations')
    await snap(page, '09-write-protection', 'E10-01', 'user', 'missing_csrf_rejected', 'err')

    await openReservation(page, primary.device_id, primary.device_name)
    await fillReservationForm(page, dateAfter(6), dateAfter(6), forgedPurpose)
    // Browser requests pass through Vite's changeOrigin proxy, which rewrites
    // Origin to the trusted backend origin. Exercise the actual backend
    // boundary directly so a forged Origin cannot be masked by that proxy.
    const csrfToken = await page.evaluate(() => localStorage.getItem('lab-auth-csrf-token'))
    expect(csrfToken).toBeTruthy()
    const forgedOrigin = await context.request.post('http://127.0.0.1:8001/api/v2/reservations', {
      headers: {
        Origin: 'https://evil.invalid',
        'X-CSRF-Token': csrfToken,
      },
      data: {
        device_id: primary.device_id,
        start_date: dateAfter(6),
        end_date: dateAfter(6),
        purpose: forgedPurpose,
        purpose_category: 'OTHER',
      },
    })
    const forgedPayload = await forgedOrigin.json()
    expect(forgedOrigin.status()).toBe(403)
    expect(forgedPayload.code).toBe('CSRF_ORIGIN_INVALID')
    await showApiResult(page, { status: forgedOrigin.status(), payload: forgedPayload }, 'POST', '/reservations')
    await snap(page, '09-write-protection', 'E10-02', 'user', 'forged_origin_rejected', 'err')
    const accessCookies = await context.cookies('http://127.0.0.1:5173/api/v2/auth/me')
    const access = accessCookies.find((cookie) => cookie.name === 'lab_access')
    const csrf = accessCookies.find((cookie) => cookie.name === 'lab_csrf')
    expect(access).toBeTruthy()
    expect(access.httpOnly).toBe(true)
    expect(csrf).toBeTruthy()
    const missingRows = databaseReservationsForPurpose(missingPurpose)
    const forgedRows = databaseReservationsForPurpose(forgedPurpose)
    expect(missingRows.count).toBe(0)
    expect(forgedRows.count).toBe(0)
    console.log(JSON.stringify({
      evidence: 'E10',
      missingCsrf: missingCsrf.status,
      forgedOrigin: forgedOrigin.status(),
      accessCookie: { httpOnly: access.httpOnly, sameSite: access.sameSite },
      csrfCookie: csrf ? { httpOnly: csrf.httpOnly, sameSite: csrf.sameSite } : null,
      databaseRows: [missingRows.count, forgedRows.count],
    }))
  } finally {
    await context.close()
  }
})

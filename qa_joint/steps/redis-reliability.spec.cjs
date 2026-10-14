const { execFileSync } = require('node:child_process')
const path = require('node:path')
const { test, expect } = require('../../frontend/node_modules/@playwright/test')
const {
  api,
  fixture,
  password,
  signIn,
  snap,
} = require('./support.cjs')

const qaRoot = path.resolve(__dirname, '..')
const repoRoot = path.resolve(qaRoot, '..')
const primary = fixture('e2e-joint01')

function cycleRedis(action) {
  execFileSync('docker-compose', [action, 'redis'], {
    cwd: repoRoot,
    stdio: 'ignore',
    timeout: 60_000,
    windowsHide: true,
  })
}

const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds))
const outageMessage = '登录服务暂时不可用，请稍后重试'

async function expectTopRightSessionUnavailable(page) {
  const notice = page.locator('.el-notification').filter({ hasText: outageMessage }).first()
  await expect(notice).toBeVisible()
  const bounds = await notice.boundingBox()
  expect(bounds).not.toBeNull()
  expect(bounds.x).toBeGreaterThan(720)
  expect(bounds.y).toBeLessThan(120)
}

async function loginWithoutReplacingEvidence(page, username) {
  await page.goto('/login')
  await page.getByLabel('用户名').fill(username)
  await page.getByLabel('密码').fill(password())
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.waitForURL(/\/dashboard(?:\?.*)?$/, { timeout: 20_000 })
}

async function waitForAuth(page) {
  let result
  for (let attempt = 0; attempt < 20; attempt += 1) {
    result = await api(page, '/auth/me')
    if (result.status === 200 || result.status === 401) return result
    await wait(1_000)
  }
  return result
}

test('E11 Redis outage fails closed and the browser recovers with reservation data intact', async ({ browser }) => {
  const userContext = await browser.newContext()
  const adminContext = await browser.newContext()
  const user = await userContext.newPage()
  const admin = await adminContext.newPage()
  let redisStopped = false

  try {
    await signIn(user, primary.username, '10-redis-outage', 'user')
    await signIn(admin, primary.admin_username, '10-redis-outage', 'admin')
    await user.goto('/reservations/mine')
    await admin.goto('/approvals/pending')

    const beforeReservations = await api(user, '/reservations/mine?page=1&page_size=100')
    expect(beforeReservations.status).toBe(200)
    const reservationIdsBefore = beforeReservations.payload.data.items.map((item) => item.id).sort()
    await snap(user, '10-redis-outage', '03', 'user', 'before_redis_outage')
    await snap(admin, '10-redis-outage', '03', 'admin', 'before_redis_outage')

    redisStopped = true
    cycleRedis('stop')
    await wait(500)

    const userDuringOutage = await api(user, '/reservations/mine?page=1&page_size=100')
    const adminDuringOutage = await api(admin, '/approvals/pending')
    expect(userDuringOutage.status).toBe(503)
    expect(userDuringOutage.payload.code).toBe('AUTH_SESSION_UNAVAILABLE')
    expect(adminDuringOutage.status).toBe(503)
    expect(adminDuringOutage.payload.code).toBe('AUTH_SESSION_UNAVAILABLE')

    // Reload through the real Vue app so the Axios interceptor renders the
    // production notification instead of the test-only API diagnostic panel.
    await Promise.all([user.reload(), admin.reload()])
    await Promise.all([
      expectTopRightSessionUnavailable(user),
      expectTopRightSessionUnavailable(admin),
    ])
    await snap(user, '10-redis-outage', '04', 'user', 'redis_unavailable', 'err')
    await snap(admin, '10-redis-outage', '04', 'admin', 'redis_unavailable', 'err')

    cycleRedis('start')
    redisStopped = false

    const userSession = await waitForAuth(user)
    const adminSession = await waitForAuth(admin)
    expect(userSession.status).toBe(200)
    expect(adminSession.status).toBe(200)

    // The outage reload clears the in-memory Pinia profile on purpose. Log
    // back in after the raw session checks, without overwriting baseline images.
    await Promise.all([
      loginWithoutReplacingEvidence(user, primary.username),
      loginWithoutReplacingEvidence(admin, primary.admin_username),
    ])

    const afterReservations = await api(user, '/reservations/mine?page=1&page_size=100')
    expect(afterReservations.status).toBe(200)
    const reservationIdsAfter = afterReservations.payload.data.items.map((item) => item.id).sort()
    expect(reservationIdsAfter).toEqual(reservationIdsBefore)

    await user.evaluate(() => document.querySelector('[data-qa-joint-api-result]')?.remove())
    await admin.evaluate(() => document.querySelector('[data-qa-joint-api-result]')?.remove())
    await user.goto('/devices')
    await expect(user.locator('.device-card')).toHaveCount(2)
    await admin.goto('/approvals/pending')
    await expect(admin.getByRole('heading', { name: '待审批', exact: true })).toBeVisible()
    await snap(user, '10-redis-outage', '05', 'user', 'redis_recovered')
    await snap(admin, '10-redis-outage', '05', 'admin', 'redis_recovered')

    console.log(JSON.stringify({
      evidence: 'E11',
      outageResponses: [userDuringOutage.status, adminDuringOutage.status],
      recoverySessions: [userSession.status, adminSession.status],
      reservationsBeforeAndAfter: [reservationIdsBefore.length, reservationIdsAfter.length],
      reservationIdsPreserved: true,
    }))
  } finally {
    if (redisStopped) cycleRedis('start')
    await userContext.close()
    await adminContext.close()
  }
})

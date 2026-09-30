import { execFileSync } from 'node:child_process'
import { expect, test } from '@playwright/test'

type Fixture = {
  prefix: string
  username: string
  password: string
}

const prefix = `e2e-csrf-${Date.now().toString(36)}`
let fixture: Fixture

function fixtureCommand(action: 'seed' | 'cleanup'): string {
  return execFileSync(
    'uv',
    ['run', 'python', 'scripts/e2e_fixture.py', action, '--prefix', prefix],
    {
      cwd: new URL('../../backend', import.meta.url),
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'inherit'],
    },
  ).trim()
}

test.describe('同一登录会话的多标签页 CSRF 保护', () => {
  test.beforeAll(() => {
    fixture = JSON.parse(fixtureCommand('seed')) as Fixture
  })

  test.afterAll(() => {
    fixtureCommand('cleanup')
  })

  test('两个标签页并发提交时使用共享令牌并成功通过 CSRF 校验', async ({ browser }) => {
    const context = await browser.newContext()
    const firstTab = await context.newPage()
    await firstTab.goto('/login')
    await firstTab.getByLabel('用户名').fill(fixture.username)
    await firstTab.getByLabel('密码').fill(fixture.password)
    await firstTab.getByRole('button', { name: '登录' }).click()
    await expect(firstTab).toHaveURL(/dashboard/)

    const secondTab = await context.newPage()
    await secondTab.goto('/dashboard')
    await expect(secondTab).toHaveURL(/dashboard/)
    await expect(secondTab.getByRole('heading', { name: '我的仪表盘', exact: true })).toBeVisible()

    const sharedTokens = await Promise.all([
      firstTab.evaluate(() => localStorage.getItem('lab-auth-csrf-token')),
      secondTab.evaluate(() => localStorage.getItem('lab-auth-csrf-token')),
    ])
    expect(sharedTokens[0]).toBeTruthy()
    expect(sharedTokens[1]).toBe(sharedTokens[0])

    const attemptWrite = (page: typeof firstTab) => page.evaluate(async () => {
      const csrfToken = localStorage.getItem('lab-auth-csrf-token')
      const response = await fetch('/api/v2/reservations/999999999/cancel', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': csrfToken || '',
        },
        body: '{}',
      })
      const body = await response.json()
      return { status: response.status, code: body.code || body.data?.code || 'UNKNOWN' }
    })
    const outcomes = await Promise.all([attemptWrite(firstTab), attemptWrite(secondTab)])

    expect(outcomes.map((outcome) => outcome.status)).toEqual([404, 404])
    expect(outcomes.map((outcome) => outcome.code)).not.toContain('CSRF_TOKEN_INVALID')
    expect(outcomes.map((outcome) => outcome.code)).not.toContain('CSRF_SESSION_MISMATCH')
    await context.close()
  })
})

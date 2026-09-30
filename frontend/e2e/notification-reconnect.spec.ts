import { execFileSync } from 'node:child_process'
import { once } from 'node:events'
import {
  createServer,
  request as proxyRequest,
  type ClientRequest,
  type ServerResponse,
} from 'node:http'
import type { AddressInfo } from 'node:net'
import { expect, test, type Page } from '@playwright/test'

type Fixture = {
  username: string
  password: string
}

let prefix = ''
let fixture: Fixture

function fixtureCommand(action: 'seed' | 'notification' | 'cleanup', title?: string): string {
  const args = ['run', 'python', 'scripts/e2e_fixture.py', action, '--prefix', prefix]
  if (title) args.push('--title', title)
  return execFileSync('uv', args, {
    cwd: new URL('../../backend', import.meta.url),
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'inherit'],
  }).trim()
}

async function login(page: Page, username: string, password: string) {
  await page.goto('/login')
  await page.getByLabel('用户名').fill(username)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).toHaveURL(/dashboard/)
  await expect(page.getByText('实验室预约系统')).toBeVisible()
}

function isUnreadCountResponse(response: { url(): string; request(): { method(): string } }) {
  const url = new URL(response.url())
  return response.request().method() === 'GET'
    && url.pathname.endsWith('/api/v2/notifications/mine')
    && url.searchParams.get('onlyUnread') === 'true'
    && url.searchParams.get('size') === '1'
}

function isNotificationStreamResponse(response: { url(): string; request(): { method(): string } }) {
  return response.request().method() === 'GET'
    && new URL(response.url()).pathname.endsWith('/api/v2/notifications/stream')
}

async function startInterruptibleSseProxy(backendPort: number) {
  const active = new Map<ServerResponse, ClientRequest>()
  const lastEventIds: string[] = []
  const server = createServer((incoming, outgoing) => {
    if (!incoming.url?.startsWith('/api/v2/notifications/stream')) {
      outgoing.writeHead(404).end()
      return
    }
    lastEventIds.push(String(incoming.headers['last-event-id'] || ''))
    const headers = { ...incoming.headers, host: `127.0.0.1:${backendPort}` }
    delete headers.connection
    const upstream = proxyRequest({
      hostname: '127.0.0.1',
      port: backendPort,
      path: incoming.url,
      method: incoming.method,
      headers,
    }, (backendResponse) => {
      const responseHeaders = { ...backendResponse.headers }
      delete responseHeaders.connection
      delete responseHeaders['transfer-encoding']
      outgoing.writeHead(backendResponse.statusCode || 502, responseHeaders)
      backendResponse.pipe(outgoing)
      backendResponse.once('end', () => active.delete(outgoing))
    })
    active.set(outgoing, upstream)
    incoming.once('aborted', () => upstream.destroy())
    outgoing.once('close', () => {
      active.delete(outgoing)
      upstream.destroy()
    })
    upstream.once('error', () => {
      if (!outgoing.headersSent) outgoing.writeHead(502)
      outgoing.end()
    })
    incoming.pipe(upstream)
  })
  server.listen(0, '127.0.0.1')
  await once(server, 'listening')
  const address = server.address() as AddressInfo

  return {
    origin: `http://127.0.0.1:${address.port}`,
    lastEventIds,
    dropActiveStreams() {
      for (const [outgoing, upstream] of active) {
        outgoing.destroy()
        upstream.destroy()
      }
      active.clear()
    },
    async close() {
      this.dropActiveStreams()
      server.close()
      await once(server, 'close')
    },
  }
}

test.describe('通知 SSE 断线重连', () => {
  test.beforeEach(() => {
    prefix = `e2e-${Date.now().toString(36)}`
    fixture = JSON.parse(fixtureCommand('seed')) as Fixture
  })

  test.afterEach(() => {
    fixtureCommand('cleanup')
  })

  test('HTTP 连接中断后同一 EventSource 按 Last-Event-ID 补发通知', async ({ browser }) => {
    test.setTimeout(45_000)
    const context = await browser.newContext()
    const backendPort = Number(process.env.E2E_BACKEND_PORT || 8000)
    const proxy = await startInterruptibleSseProxy(backendPort)
    try {
      await context.route(/\/api\/v2\/notifications\/stream(?:\?.*)?$/, (route) => {
        const path = new URL(route.request().url()).pathname
        return route.continue({ url: `${proxy.origin}${path}` })
      })
      const page = await context.newPage()
      const initialUnreadResponse = page.waitForResponse(isUnreadCountResponse)
      const initialStreamResponse = page.waitForResponse(isNotificationStreamResponse)
      await login(page, fixture.username, fixture.password)
      const initialResponse = await initialUnreadResponse
      const initialBody = await initialResponse.json() as { data?: { total?: number } }
      expect(initialBody.data?.total).toBe(0)
      expect((await initialStreamResponse).status()).toBe(200)

      const title = `断线期间通知 ${prefix}`
      fixtureCommand('notification', title)
      proxy.dropActiveStreams()

      await expect(page.getByText('断线通知已同步')).toBeVisible({ timeout: 20_000 })
      await expect.poll(() => proxy.lastEventIds.length, { timeout: 10_000 }).toBeGreaterThan(1)
      expect(proxy.lastEventIds[1]).not.toBe('')
      await expect(page.locator('.layout__header-right .el-badge__content')).toHaveText('1')

      await page.getByRole('menuitem', { name: '我的通知', exact: true }).click()
      await expect(page.getByRole('heading', { name: '通知中心', exact: true })).toBeVisible()
      await expect(page.locator('.notif-row__title').filter({ hasText: title })).toBeVisible()
    } finally {
      await context.close()
      await proxy.close()
    }
  })

  test('一个标签页标记已读后同步更新同账号的另一个标签页', async ({ browser }) => {
    test.setTimeout(45_000)
    const context = await browser.newContext()
    try {
      const firstPage = await context.newPage()
      const firstStream = firstPage.waitForResponse(isNotificationStreamResponse)
      await login(firstPage, fixture.username, fixture.password)
      expect((await firstStream).status()).toBe(200)

      const title = `多标签页已读同步 ${prefix}`
      fixtureCommand('notification', title)
      await firstPage.getByRole('menuitem', { name: '我的通知', exact: true }).click()
      await expect(firstPage.locator('.notif-row__title').filter({ hasText: title })).toBeVisible()

      const secondPage = await context.newPage()
      const secondStream = secondPage.waitForResponse(isNotificationStreamResponse)
      await secondPage.goto('/notifications')
      expect((await secondStream).status()).toBe(200)
      const secondRow = secondPage.locator('.notif-row').filter({ hasText: title })
      await expect(secondRow).toBeVisible()
      await expect(secondRow).toHaveAttribute('data-read', 'unread')

      await firstPage.locator('.notif-row').filter({ hasText: title }).click()
      await expect(secondRow).toHaveAttribute('data-read', 'read', { timeout: 10_000 })
      await expect(secondPage.locator('.layout__header-right .el-badge__content')).toBeHidden()
    } finally {
      await context.close()
    }
  })
})

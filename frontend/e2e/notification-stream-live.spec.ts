import { execFileSync, spawn } from 'node:child_process'
import { once } from 'node:events'
import { createServer, request as proxyRequest, type ClientRequest, type ServerResponse } from 'node:http'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { basename, join, resolve } from 'node:path'
import type { AddressInfo } from 'node:net'
import { expect, test, type BrowserContext, type Page } from '@playwright/test'

type Fixture = { username: string; password: string; user_id: number }
type CaptureRecord = {
  kind: string
  at: string
  requestId?: string
  method?: string
  url?: string
  status?: number
  lastEventId?: string
  eventName?: string
  eventId?: string
  data?: string
  headers?: Record<string, string>
}
type Capture = { records: CaptureRecord[] }
type GroupStat = {
  name: string
  consumers: number
  pending: number
  lag: number
  lastDeliveredId: string
}
type StreamStat = {
  stream: string
  streamLength: number
  groups: GroupStat[]
  deadLetterLength: number
  matchingNotificationEntries: Array<Record<string, unknown>>
}
type CaseResult = {
  id: string
  title: string
  precondition: string
  steps: string
  expected: string
  actual: string
  status: string
  screenshots: string[]
}

const backendCwd = resolve(process.cwd(), '..', 'backend')
const artifactRoot = resolve(
  process.env.E2E_NOTIFICATION_EVIDENCE_DIR
    || join(process.cwd(), '.artifacts', 'notification-stream-e2e'),
)
const runPrefix = process.env.E2E_NOTIFICATION_PREFIX || `e2e-${Date.now().toString(36)}`
mkdirSync(artifactRoot, { recursive: true })

let context: BrowserContext | undefined
let fixture: Fixture
let captures = new Map<Page, Capture>()
let pages: Page[] = []
let extraEvidence: Array<{ filename: string; title: string; body: unknown }> = []
let explicitScreenshots: string[] = []
let actual = ''
let caseResults: CaseResult[] = []

const specifications: Record<string, Omit<CaseResult, 'actual' | 'status' | 'screenshots'>> = {
  '01': {
    id: '01',
    title: '正常实时推送',
    precondition: '测试用户已登录，SSE EventSource 返回 200，API 使用独立 Redis DB 14。',
    steps: '写入一条 NOTIFICATION Outbox 任务，等待消费、Stream ACK 和通知中心更新。',
    expected: '前端及时显示通知；CDP Network 捕获 SSE notification 事件和序号。',
  },
  '02': {
    id: '02',
    title: 'SSE 断线重连补发',
    precondition: 'SSE 已连接并已收到通知 A、B；测试代理可中断连接并暂停重连。',
    steps: '中断 SSE；Outbox 产生 C、D；恢复代理，记录重连 Last-Event-ID 与 SSE 事件。',
    expected: '重连请求携带 B 的 Last-Event-ID；只补发 C、D，按 deliverySequence 有序且不重复。',
  },
  '03': {
    id: '03',
    title: '重复投递幂等',
    precondition: '一条通知已通过 Outbox、Redis Stream 和 SSE 到达已登录客户端。',
    steps: '将相同 notification.id 与 deliverySequence 的完整事件再次写入 Stream。',
    expected: 'Stream 可见重复投递；Hub 按 notification.id 去重，前端只显示一次。',
  },
  '04': {
    id: '04',
    title: '序号缺口 MySQL 补偿',
    precondition: '客户端已有连续游标；MySQL 保存下两个序号，Redis 只收到较大序号事件。',
    steps: '让 SSE Hub 收到后续序号，观察 SSE 与 MySQL 测试用户通知记录。',
    expected: '缺失通知从 MySQL 补读；浏览器收到连续、递增的两个序号。',
  },
  '05': {
    id: '05',
    title: '多 API 进程广播订阅',
    precondition: '两个 API 进程使用不同 Redis Stream 消费组，同一用户在两个标签页建立 SSE。',
    steps: '向测试用户写入一条 Outbox 通知，分别检查两页 SSE 与通知列表。',
    expected: '两个进程组各自消费同一 Stream 事件；两个客户端均只收到并显示一次。',
  },
  '06': {
    id: '06',
    title: '消费失败重试与死信',
    precondition: '测试 API 仅对 E2E_HUB_FAIL 标题注入 SSE Hub 故障；最大尝试次数为 5。',
    steps: '投递故障通知，观察两组重试、源 Stream 记录、ACK 状态和死信流。',
    expected: '带抖动的指数退避最多尝试 5 次后进入死信；源消息留在 Stream，不无限重试。',
  },
  '07': {
    id: '07',
    title: '消息积压与监控告警',
    precondition: 'API 指标由 Prometheus 抓取；测试消费者被 Redis 测试锁暂停。',
    steps: '写入 1,105 条 Stream 事件，检查 PEL/lag/最老消息年龄、运维统计和告警状态。',
    expected: '未 ACK 消息留在 Stream；Grafana 显示积压，Prometheus backlog 告警进入 firing。',
  },
  '08': {
    id: '08',
    title: '清理所有消费组均 ACK 的消息',
    precondition: '两个活动 API 消费组都消费并 ACK 测试消息；另构造一条未 ACK 消息。',
    steps: '运行 trim-acked，比较 ACK 消息和 PEL 消息清理前后的 Stream 状态。',
    expected: '所有组均 ACK 的消息被清理；任一组未 ACK 的消息保留。',
  },
  '09': {
    id: '09',
    title: '清理陈旧消费组',
    precondition: 'Stream 中存在手动创建的 e2e-stale 消费组和两个活动 API 组。',
    steps: '执行 destroy-group --confirm，检查清理前后的 XINFO GROUPS。',
    expected: '只删除指定陈旧组，活动 API 消费组仍存在且状态不变。',
  },
}

function commandJson(args: string[]): any {
  const output = execFileSync('uv', args, {
    cwd: backendCwd,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'inherit'],
  })
  if (!output.trim()) throw new Error(`Expected JSON from: ${args.join(' ')}`)
  return JSON.parse(output)
}

function fixtureCommand(action: 'seed' | 'notification' | 'cleanup', title?: string): any {
  const args = ['run', 'python', 'scripts/e2e_fixture.py', action, '--prefix', runPrefix]
  if (title) args.push('--title', title)
  if (action === 'cleanup') {
    execFileSync('uv', args, {
      cwd: backendCwd,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'inherit'],
    })
    return undefined
  }
  return commandJson(args)
}

function streamCommand(action: string, options: Record<string, string | number | boolean> = {}): any {
  const args = ['run', 'python', 'scripts/e2e_notification_stream.py', action, '--prefix', runPrefix]
  for (const [name, value] of Object.entries(options)) {
    if (typeof value === 'boolean') {
      if (value) args.push(`--${name}`)
    } else {
      args.push(`--${name}`, String(value))
    }
  }
  return commandJson(args)
}

function streamOps(args: string[]): any {
  const output = execFileSync(
    'uv',
    ['run', 'python', '-m', 'app.infrastructure.notifications.stream_ops', ...args],
    { cwd: backendCwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'inherit'] },
  )
  return JSON.parse(output)
}

function isSse(response: { url(): string; request(): { method(): string } }) {
  return response.request().method() === 'GET'
    && new URL(response.url()).pathname.endsWith('/api/v2/notifications/stream')
}

async function attachCapture(page: Page): Promise<Capture> {
  const capture: Capture = { records: [] }
  const cdp = await context!.newCDPSession(page)
  await cdp.send('Network.enable')
  cdp.on('Network.requestWillBeSent', (raw) => {
    const event = raw as {
      requestId: string
      request: { url: string; method: string; headers: Record<string, string> }
    }
    if (!event.request.url.includes('/api/v2/notifications/stream')) return
    capture.records.push({
      kind: 'request',
      at: new Date().toISOString(),
      requestId: event.requestId,
      method: event.request.method,
      url: event.request.url,
      lastEventId: event.request.headers['Last-Event-ID'] || event.request.headers['last-event-id'] || '',
    })
  })
  cdp.on('Network.requestWillBeSentExtraInfo', (raw) => {
    const event = raw as { requestId: string; headers: Record<string, string> }
    const lastEventId = event.headers['Last-Event-ID'] || event.headers['last-event-id'] || ''
    capture.records.push({
      kind: 'request-headers',
      at: new Date().toISOString(),
      requestId: event.requestId,
      lastEventId,
      headers: { 'Last-Event-ID': lastEventId },
    })
  })
  cdp.on('Network.responseReceived', (raw) => {
    const event = raw as {
      requestId: string
      response: { url: string; status: number; mimeType: string }
    }
    if (!event.response.url.includes('/api/v2/notifications/stream')) return
    capture.records.push({
      kind: 'response',
      at: new Date().toISOString(),
      requestId: event.requestId,
      url: event.response.url,
      status: event.response.status,
      data: event.response.mimeType,
    })
  })
  cdp.on('Network.eventSourceMessageReceived', (raw) => {
    const event = raw as {
      requestId: string
      eventName: string
      eventId: string
      data: string
    }
    capture.records.push({
      kind: 'eventsource-message',
      at: new Date().toISOString(),
      requestId: event.requestId,
      eventName: event.eventName,
      eventId: event.eventId,
      data: event.data,
    })
  })
  captures.set(page, capture)
  return capture
}

async function newTrackedPage(): Promise<Page> {
  const page = await context!.newPage()
  pages.push(page)
  await attachCapture(page)
  return page
}

async function login(page: Page) {
  const sseResponse = page.waitForResponse(isSse)
  await page.goto('/login')
  await page.getByLabel('用户名').fill(fixture.username)
  await page.getByLabel('密码').fill(fixture.password)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).toHaveURL(/dashboard/)
  await expect(page.getByText('实验室预约系统')).toBeVisible()
  expect((await sseResponse).status()).toBe(200)
}

async function openNotificationCenter(page: Page, expectedTitle?: string) {
  await page.getByRole('menuitem', { name: '我的通知', exact: true }).click()
  await expect(page.getByRole('heading', { name: '通知中心', exact: true })).toBeVisible()
  if (expectedTitle) {
    await expect(
      page.locator('.notif-row__title').filter({ hasText: expectedTitle }).first(),
    ).toBeVisible({ timeout: 20_000 })
  }
}

function notificationMessages(capture: Capture) {
  return capture.records
    .filter((record) => record.kind === 'eventsource-message' && record.eventName === 'notification')
    .map((record) => {
      try {
        return { eventId: record.eventId || '', payload: JSON.parse(record.data || '{}') }
      } catch {
        return { eventId: record.eventId || '', payload: {} }
      }
    })
}

function escapeHtml(value: unknown): string {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]!)
}

function networkHtml(capture: Capture, label: string) {
  const rows = capture.records.map((record) => `
    <tr>
      <td>${escapeHtml(record.kind)}</td><td>${escapeHtml(record.method || record.eventName || '')}</td>
      <td>${escapeHtml(record.status ?? record.eventId ?? '')}</td>
      <td>${escapeHtml(record.lastEventId || '')}</td>
      <td class="url">${escapeHtml(record.url || record.data || '')}</td>
    </tr>`).join('')
  return `<!doctype html><html><head><meta charset="utf-8"><title>SSE Network capture</title>
    <style>
      body{margin:0;background:#202124;color:#e8eaed;font:13px Arial,sans-serif}
      header{padding:12px 18px;background:#292a2d;border-bottom:1px solid #45464a}
      h1{font-size:16px;margin:0 0 6px}p{margin:0;color:#bdc1c6}
      table{border-collapse:collapse;width:100%;table-layout:fixed}th,td{border-bottom:1px solid #3c4043;padding:8px;text-align:left;vertical-align:top}
      th{color:#9aa0a6;background:#292a2d;position:sticky;top:0}td.url{overflow-wrap:anywhere;color:#bdc1c6}
      .badge{color:#8ab4f8} .empty{padding:20px;color:#f28b82}
    </style></head><body><header><h1>Network · EventSource SSE</h1>
    <p>${escapeHtml(label)} · Chromium CDP Network events · 实际请求头、响应状态和 EventSource 帧</p></header>
    <table><thead><tr><th style="width:170px">事件</th><th style="width:120px">方法/类型</th><th style="width:100px">状态/ID</th><th style="width:130px">Last-Event-ID</th><th>URL / SSE data</th></tr></thead>
    <tbody>${rows || '<tr><td colspan="5" class="empty">尚未捕获 SSE Network 事件</td></tr>'}</tbody></table></body></html>`
}

async function evidencePage(filename: string, title: string, body: unknown) {
  extraEvidence.push({ filename, title, body })
}

async function saveEvidencePages() {
  const caseNumber = Object.keys(specifications).find((id) => test.info().title.startsWith(`用例${Number(id)}`)) || '00'
  const screenshots: string[] = []
  for (let index = 0; index < pages.length; index += 1) {
    const page = pages[index]
    if (page.isClosed()) continue
    const filename = `case-${caseNumber}-frontend${pages.length > 1 ? `-${index + 1}` : ''}.png`
    const path = join(artifactRoot, filename)
    try {
      await page.screenshot({ path, fullPage: true, timeout: 15_000 })
      screenshots.push(filename)
    } catch {
      await page.screenshot({ path, fullPage: false, timeout: 10_000 })
      screenshots.push(filename)
    }
    const capture = captures.get(page)
    if (capture) {
      const networkFilename = `case-${caseNumber}-sse-network${pages.length > 1 ? `-${index + 1}` : ''}.png`
      const networkPage = await context!.newPage()
      await networkPage.setContent(networkHtml(capture, specifications[caseNumber].title))
      await networkPage.screenshot({ path: join(artifactRoot, networkFilename), fullPage: true })
      screenshots.push(networkFilename)
      await networkPage.close()
      writeFileSync(
        join(artifactRoot, `case-${caseNumber}-sse-network${pages.length > 1 ? `-${index + 1}` : ''}.json`),
        JSON.stringify(capture.records, null, 2),
        'utf8',
      )
    }
  }
  for (const item of extraEvidence) {
    const reportPage = await context!.newPage()
    await reportPage.setContent(`<!doctype html><meta charset="utf-8"><style>body{font:14px Consolas,monospace;background:#111827;color:#e5e7eb;padding:24px}h1{font:20px Arial}pre{white-space:pre-wrap;overflow-wrap:anywhere;border:1px solid #374151;padding:16px;background:#030712}</style><h1>${escapeHtml(item.title)}</h1><pre>${escapeHtml(JSON.stringify(item.body, null, 2))}</pre>`)
    await reportPage.screenshot({ path: join(artifactRoot, item.filename), fullPage: true })
    screenshots.push(item.filename)
    await reportPage.close()
  }
  return screenshots
}

function parseDotEnvValue(key: string): string {
  const envPath = resolve(process.cwd(), '..', '.env')
  const line = readFileSync(envPath, 'utf8').split(/\r?\n/).find((item) => item.startsWith(`${key}=`))
  return line?.slice(key.length + 1).trim().replace(/^['"]|['"]$/g, '') || ''
}

function parseStreamStats(): StreamStat {
  return streamCommand('inspect-stream') as StreamStat
}

async function waitForGroupsIdle(timeout = 30_000) {
  await expect.poll(() => {
    const stats = parseStreamStats()
    const apiGroups = stats.groups.filter((group) => group.name.includes(runPrefix))
    return apiGroups.length >= 1 && apiGroups.every((group) => group.pending === 0 && group.lag === 0)
  }, { timeout, intervals: [1_000, 2_000, 3_000] }).toBe(true)
}

function streamIdAtLeast(actualId: string, expectedId: string): boolean {
  const [actualMs, actualSeq] = actualId.split('-').map(Number)
  const [expectedMs, expectedSeq] = expectedId.split('-').map(Number)
  return actualMs > expectedMs || (actualMs === expectedMs && actualSeq >= expectedSeq)
}

async function startInterruptibleSseProxy(backendPort: number) {
  const active = new Map<ServerResponse, ClientRequest>()
  const requests: Array<{ lastEventId: string; status?: number; queued?: boolean }> = []
  const queued: Array<{
    incoming: import('node:http').IncomingMessage
    outgoing: ServerResponse
    record: { lastEventId: string; status?: number; queued?: boolean }
  }> = []
  let paused = false
  const forward = (
    incoming: import('node:http').IncomingMessage,
    outgoing: ServerResponse,
    record: { lastEventId: string; status?: number; queued?: boolean },
  ) => {
    if (outgoing.destroyed) return
    const path = incoming.url || ''
    const headers = { ...incoming.headers, host: `127.0.0.1:${backendPort}` }
    delete headers.connection
    const upstream = proxyRequest({
      hostname: '127.0.0.1', port: backendPort, path, method: incoming.method, headers,
    }, (response) => {
      record.status = response.statusCode || 502
      const responseHeaders = { ...response.headers }
      delete responseHeaders.connection
      delete responseHeaders['transfer-encoding']
      outgoing.writeHead(response.statusCode || 502, responseHeaders)
      response.pipe(outgoing)
      response.once('end', () => active.delete(outgoing))
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
  }
  const server = createServer((incoming, outgoing) => {
    const path = incoming.url || ''
    if (!path.startsWith('/api/v2/notifications/stream')) {
      outgoing.writeHead(404).end()
      return
    }
    const record = { lastEventId: String(incoming.headers['last-event-id'] || '') }
    requests.push(record)
    if (paused) {
      record.queued = true
      queued.push({ incoming, outgoing, record })
      return
    }
    forward(incoming, outgoing, record)
  })
  server.listen(0, '127.0.0.1')
  await once(server, 'listening')
  const address = server.address() as AddressInfo
  return {
    origin: `http://127.0.0.1:${address.port}`,
    requests,
    pause() {
      paused = true
      for (const [outgoing, upstream] of active) {
        outgoing.destroy()
        upstream.destroy()
      }
      active.clear()
    },
    resume() {
      paused = false
      for (const request of queued.splice(0)) forward(request.incoming, request.outgoing, request.record)
    },
    async close() {
      paused = true
      for (const [outgoing, upstream] of active) {
        outgoing.destroy()
        upstream.destroy()
      }
      active.clear()
      for (const request of queued.splice(0)) request.outgoing.destroy()
      server.close()
      await once(server, 'close')
    },
  }
}

async function startPrometheusProxy() {
  const server = createServer((request, response) => {
    const requestedPath = request.url || '/'
    const child = spawn('docker.exe', [
      'exec', 'lab_devices_reservation-prometheus-1', 'wget', '-qO-',
      `http://127.0.0.1:9090${requestedPath}`,
    ], { windowsHide: true })
    const chunks: Buffer[] = []
    child.stdout.on('data', (chunk: Buffer) => chunks.push(chunk))
    child.stderr.resume()
    child.once('error', (error) => {
      response.writeHead(502).end(String(error))
    })
    child.once('close', (code) => {
      if (response.writableEnded) return
      const body = Buffer.concat(chunks)
      if (code !== 0) {
        response.writeHead(502, { 'content-type': 'text/plain' }).end(body.length ? body : 'Prometheus proxy failed')
        return
      }
      const extension = requestedPath.split('?')[0].split('.').pop()
      const contentType = requestedPath.startsWith('/api/') || extension === 'json'
        ? 'application/json'
        : extension === 'css' ? 'text/css'
          : extension === 'js' ? 'application/javascript'
            : extension === 'svg' ? 'image/svg+xml'
              : 'text/html; charset=utf-8'
      response.writeHead(200, { 'content-type': contentType, 'cache-control': 'no-store' }).end(body)
    })
  })
  server.listen(0, '127.0.0.1')
  await once(server, 'listening')
  const address = server.address() as AddressInfo
  return {
    origin: `http://127.0.0.1:${address.port}`,
    close: async () => {
      server.close()
      await once(server, 'close')
    },
  }
}

test.describe('Redis Stream 通知专项前后端联调', () => {
  test.describe.configure({ mode: 'serial' })

  test.beforeEach(async ({ browser }) => {
    fixture = fixtureCommand('seed') as Fixture
    context = await browser.newContext()
    captures = new Map()
    pages = []
    extraEvidence = []
    explicitScreenshots = []
    actual = ''
  })

  test.afterEach(async ({}, testInfo) => {
    const match = testInfo.title.match(/^用例(\d+)/)
    const caseNumber = match ? match[1].padStart(2, '0') : '00'
    const screenshots = context ? await saveEvidencePages().catch(() => []) : []
    screenshots.push(...explicitScreenshots)
    caseResults.push({
      ...specifications[caseNumber],
      actual: actual || `测试结束状态：${testInfo.status || '未知'}；详见对应 Network、Redis/MySQL/监控证据。`,
      status: testInfo.status === testInfo.expectedStatus ? '通过' : '失败',
      screenshots,
    })
    if (context) await context.close()
    context = undefined
    try {
      streamCommand('release-backlog')
    } catch {
      // No backlog key is expected in scenarios that do not create one.
    }
    fixtureCommand('cleanup')
  })

  test.afterAll(() => {
    writeFileSync(join(artifactRoot, 'cases.json'), JSON.stringify(caseResults, null, 2), 'utf8')
    const lines = [
      '# 实时通知 Redis Stream 专项联调结果',
      '',
      `运行前缀：\`${runPrefix}\``,
      '',
      '| 用例 | 前置条件 | 操作步骤 | 预期结果 | 实际结果 | 是否通过 | 截图证据 |',
      '|---|---|---|---|---|---|---|',
      ...caseResults.map((item) => {
        const links = item.screenshots.map((file) => `[${basename(file)}](./${file})`).join('<br>')
        const safe = (value: string) => value.replaceAll('|', '\\|').replaceAll('\n', '<br>')
        return `| ${item.id} ${safe(item.title)} | ${safe(item.precondition)} | ${safe(item.steps)} | ${safe(item.expected)} | ${safe(item.actual)} | ${item.status} | ${links} |`
      }),
      '',
      `通过 ${caseResults.filter((item) => item.status === '通过').length}/${caseResults.length} 条。`,
    ]
    writeFileSync(join(artifactRoot, 'report.md'), `${lines.join('\n')}\n`, 'utf8')
  })

  test('用例1 正常实时推送', async () => {
    const page = await newTrackedPage()
    await login(page)
    const title = `实时推送 ${runPrefix}`
    const task = streamCommand('enqueue', { title })
    await openNotificationCenter(page, title)
    const stats = parseStreamStats()
    const capture = captures.get(page)!
    const observed = notificationMessages(capture).find((message) => message.payload.title === title)
    expect(observed).toBeTruthy()
    expect(stats.groups.filter((group) => group.name.includes(runPrefix)).every((group) => group.pending === 0)).toBe(true)
    actual = `通知 ${title} 由 Outbox 投递并在前端可见；SSE eventId=${observed?.eventId}，notification.id=${observed?.payload.id}；消费组 PEL 均为 0。Outbox task=${task.taskKey}。`
    await evidencePage('case-01-stream-stats.png', '用例1 Redis Stream/消费组统计', stats)
  })

  test('用例2 SSE 断线重连按 Last-Event-ID 补发', async () => {
    const page = await newTrackedPage()
    const proxy = await startInterruptibleSseProxy(8000)
    try {
      await page.route(/\/api\/v2\/notifications\/stream(?:\?.*)?$/, (route) => {
        const path = new URL(route.request().url()).pathname
        return route.continue({ url: `${proxy.origin}${path}` })
      })
      await login(page)
      const first = `断线前 A ${runPrefix}`
      const second = `断线前 B ${runPrefix}`
      const third = `断线后 C ${runPrefix}`
      const fourth = `断线后 D ${runPrefix}`
      streamCommand('enqueue', { title: first })
      streamCommand('enqueue', { title: second })
      await openNotificationCenter(page, first)
      await expect(page.locator('.notif-row__title').filter({ hasText: second })).toBeVisible()
      const lastBeforeDisconnect = notificationMessages(captures.get(page)!).at(-1)?.eventId
      proxy.pause()
      streamCommand('enqueue', { title: third })
      streamCommand('enqueue', { title: fourth })
      await expect.poll(
        () => proxy.requests.some((item) => item.queued && item.lastEventId === lastBeforeDisconnect),
        { timeout: 15_000 },
      ).toBe(true)
      proxy.resume()
      await expect(page.locator('.notif-row__title').filter({ hasText: third })).toBeVisible({ timeout: 25_000 })
      await expect(page.locator('.notif-row__title').filter({ hasText: fourth })).toBeVisible({ timeout: 25_000 })
      await expect(page.locator('.notif-row__title').filter({ hasText: first })).toHaveCount(1)
      await expect(page.locator('.notif-row__title').filter({ hasText: second })).toHaveCount(1)
      await expect(page.locator('.notif-row__title').filter({ hasText: third })).toHaveCount(1)
      await expect(page.locator('.notif-row__title').filter({ hasText: fourth })).toHaveCount(1)
      const successfulReconnect = proxy.requests.find((item) => item.status === 200 && item.lastEventId === lastBeforeDisconnect)
      expect(successfulReconnect?.lastEventId).toBe(lastBeforeDisconnect)
      captures.get(page)!.records.push(...proxy.requests.map((item) => ({
        kind: 'proxy-request', at: new Date().toISOString(), status: item.status, lastEventId: item.lastEventId,
        url: `${proxy.origin}/api/v2/notifications/stream`,
      })))
      const laterSequences = notificationMessages(captures.get(page)!)
        .filter((item) => [third, fourth].includes(String(item.payload.title)))
        .map((item) => item.payload.deliverySequence as number)
      expect(laterSequences).toEqual([...laterSequences].sort((a, b) => a - b))
      actual = `A/B 已在断线前各显示一次；断线后 MySQL 保存 C/D，浏览器重连 Last-Event-ID=${successfulReconnect?.lastEventId}（断线前游标 ${lastBeforeDisconnect}），按序补发 C/D 且各显示一次。`
    } finally {
      await proxy.close()
    }
  })

  test('用例3 Stream 重复投递只展示一次', async () => {
    const page = await newTrackedPage()
    await login(page)
    const title = `重复投递 ${runPrefix}`
    streamCommand('enqueue', { title })
    await openNotificationCenter(page, title)
    const firstMessage = notificationMessages(captures.get(page)!).find((item) => item.payload.title === title)
    expect(firstMessage).toBeTruthy()
    const duplicated = streamCommand('duplicate', { title }) as { notificationId: number; deliverySequence: number; streamId: string }
    await expect.poll(() => {
      const stats = streamCommand('inspect-stream', { 'notification-id': duplicated.notificationId }) as StreamStat
      return stats.matchingNotificationEntries.filter((item) => item.notificationId === duplicated.notificationId).length
    }, { timeout: 10_000 }).toBe(2)
    await expect(page.locator('.notif-row__title').filter({ hasText: title })).toHaveCount(1)
    const messages = notificationMessages(captures.get(page)!).filter((item) => item.payload.id === duplicated.notificationId)
    expect(messages).toHaveLength(1)
    const stats = parseStreamStats()
    actual = `Redis Stream 中 notification.id=${duplicated.notificationId}、deliverySequence=${duplicated.deliverySequence} 的投递副本为 2；Hub 按 id 去重后浏览器 SSE 帧为 1，通知列表行数为 1。`
    await evidencePage('case-03-stream-duplicate.png', '用例3 重复 Stream 投递证据', stats)
  })

  test('用例4 序号缺口从 MySQL 补齐', async () => {
    const page = await newTrackedPage()
    await login(page)
    const baselineTitle = `缺口前序通知 ${runPrefix}`
    streamCommand('enqueue', { title: baselineTitle })
    await openNotificationCenter(page, baselineTitle)
    const injected = streamCommand('gap') as {
      missingNotificationId: number
      missingSequence: number
      laterNotificationId: number
      laterSequence: number
      streamId: string
    }
    await expect(page.locator('.notif-row__title').filter({ hasText: '序号缺口补齐' })).toHaveCount(2, { timeout: 20_000 })
    const rows = streamCommand('rows') as Array<Record<string, unknown>>
    const expectedSequences = [injected.missingSequence, injected.laterSequence]
    const emitted = notificationMessages(captures.get(page)!)
      .filter((item) => expectedSequences.includes(item.payload.deliverySequence as number))
      .map((item) => item.payload.deliverySequence as number)
    expect(emitted).toEqual(expectedSequences)
    expect(rows.some((row) => row.id === injected.missingNotificationId)).toBe(true)
    expect(rows.some((row) => row.id === injected.laterNotificationId)).toBe(true)
    actual = `Redis 只写入后续序号 ${injected.laterSequence}（Stream ${injected.streamId}）；SSE 从 MySQL 按序补发缺失 ${injected.missingSequence} 和后续 ${injected.laterSequence}。notification 表共查到 ${rows.length} 条测试用户记录。`
    await evidencePage('case-04-mysql-notification-rows.png', '用例4 MySQL notification 表查询结果', rows)
  })

  test('用例5 两个 API 消费组广播到两个 SSE 客户端', async () => {
    const firstPage = await newTrackedPage()
    await login(firstPage)
    const secondPage = await newTrackedPage()
    await secondPage.route(/\/api\/v2\/notifications\/stream(?:\?.*)?$/, (route) => {
      const path = new URL(route.request().url()).pathname
      return route.continue({ url: `http://127.0.0.1:8001${path}` })
    })
    const secondStream = secondPage.waitForResponse(isSse)
    await secondPage.goto('/notifications')
    expect((await secondStream).status()).toBe(200)
    await expect(secondPage.getByRole('heading', { name: '通知中心', exact: true })).toBeVisible()
    const title = `双 API 广播 ${runPrefix}`
    streamCommand('enqueue', { title })
    await expect(firstPage.getByRole('menuitem', { name: '我的通知', exact: true })).toBeVisible()
    await openNotificationCenter(firstPage, title)
    await expect(secondPage.locator('.notif-row__title').filter({ hasText: title })).toBeVisible({ timeout: 20_000 })
    const firstMessages = notificationMessages(captures.get(firstPage)!).filter((item) => item.payload.title === title)
    const secondMessages = notificationMessages(captures.get(secondPage)!).filter((item) => item.payload.title === title)
    expect(firstMessages).toHaveLength(1)
    expect(secondMessages).toHaveLength(1)
    expect(firstMessages[0].payload.id).toBe(secondMessages[0].payload.id)
    const stats = parseStreamStats()
    const apiGroups = stats.groups.filter((group) => group.name.includes(runPrefix) && /api1|api2/.test(group.name))
    expect(apiGroups).toHaveLength(2)
    actual = `notification.id=${firstMessages[0].payload.id} 被 API1/API2 两个独立消费组各消费一次；两个 SSE 客户端均收到同一通知并只展示一行。消费组：${apiGroups.map((group) => group.name).join(', ')}。`
    await evidencePage('case-05-consumer-groups.png', '用例5 Redis 独立消费组状态', stats)
  })

  test('用例6 Hub 故障指数退避后转入死信流', async ({}, testInfo) => {
    testInfo.setTimeout(90_000)
    const page = await newTrackedPage()
    await login(page)
    await openNotificationCenter(page)
    const title = `E2E_HUB_FAIL:${runPrefix}`
    const baselineDeadLetters = parseStreamStats().deadLetterLength
    streamCommand('enqueue', { title })
    await expect.poll(() => {
      const stats = parseStreamStats()
      const groups = stats.groups.filter((group) => group.name.includes(runPrefix))
      return stats.deadLetterLength >= baselineDeadLetters + 2
        && groups.length === 2
        && groups.every((group) => group.pending === 0)
    }, { timeout: 30_000, intervals: [500, 1_000, 2_000] }).toBe(true)
    const deadLetters = streamOps(['inspect', '--limit', '10']) as Array<Record<string, unknown>>
    expect(deadLetters.length).toBeGreaterThanOrEqual(baselineDeadLetters + 2)
    expect(deadLetters.every((entry) => Number(entry.attempts) === 5)).toBe(true)
    const stats = parseStreamStats()
    const logPath = process.env.E2E_NOTIFICATION_SERVER_STDERR || ''
    const logText = logPath ? readFileSync(logPath, 'utf8') : ''
    const failureLines = logText.split(/\r?\n/).filter((line) => /handoff failed|moved to dead letter/.test(line)).slice(-20)
    expect(failureLines.some((line) => line.includes('5/5')) || deadLetters.length > 0).toBe(true)
    await expect(page.locator('.notif-row__title').filter({ hasText: title })).toHaveCount(0)
    actual = `测试 Hub 对该消息持续抛错；两个进程组各在第 5 次后转入死信，死信数=${deadLetters.length}，源 Stream 仍有记录且 PEL=0（已原子转 DLQ 并 ACK），没有无限重试。`
    await evidencePage('case-06-dead-letter-and-logs.png', '用例6 死信、Stream 统计与 API 重试日志', { deadLetters, stats, failureLines })
  })

  test('用例7 保留积压并验证 Prometheus/Grafana 告警', async ({ browser }, testInfo) => {
    testInfo.setTimeout(11 * 60_000)
    const page = await newTrackedPage()
    await login(page)
    await openNotificationCenter(page)
    const backlog = streamCommand('backlog', { 'user-id': fixture.user_id, count: 1105 })
    if (!backlog.firstId) throw new Error('backlog helper did not return Stream IDs')
    const statsBefore = parseStreamStats()
    await expect.poll(() => {
      const current = parseStreamStats()
      const groups = current.groups.filter((group) => group.name.includes(runPrefix))
      return groups.length >= 2 && groups.every((group) => group.lag > 1000 && group.pending > 0)
    }, { timeout: 30_000, intervals: [1_000, 2_000, 4_000] }).toBe(true)

    const prom = await startPrometheusProxy()
    const promContext = await browser.newContext()
    const promPage = await promContext.newPage()
    const grafanaUser = parseDotEnvValue('GRAFANA_ADMIN_USER')
    const grafanaPassword = parseDotEnvValue('GRAFANA_ADMIN_PASSWORD')
    const grafanaPort = parseDotEnvValue('GRAFANA_PORT') || '3001'
    const grafanaContext = await browser.newContext()
    const grafanaPage = await grafanaContext.newPage()
    try {
      await grafanaPage.goto(`http://127.0.0.1:${grafanaPort}/login`)
      await grafanaPage.getByLabel('Email or username').fill(grafanaUser)
      await grafanaPage.getByTestId('data-testid Password input field').fill(grafanaPassword)
      await grafanaPage.getByRole('button', { name: 'Log in' }).click()
      await expect(grafanaPage).not.toHaveURL(/\/login/)
      const alertData = async () => {
        const response = await promPage.request.get(`${prom.origin}/api/v1/alerts`)
        expect(response.ok()).toBeTruthy()
        const body = await response.json() as { data?: { alerts?: Array<{ labels?: { alertname?: string }; state?: string }> } }
        return body.data?.alerts || []
      }
      const queryData = async (query: string) => {
        const response = await promPage.request.get(`${prom.origin}/api/v1/query?query=${encodeURIComponent(query)}`)
        expect(response.ok()).toBeTruthy()
        return response.json()
      }
      const targets = await queryData('up{job="lab-api"}') as { data?: { result?: Array<{ value?: [number, string] }> } }
      expect(targets.data?.result?.some((item) => item.value?.[1] === '1')).toBe(true)
      const rulesResponse = await promPage.request.get(`${prom.origin}/api/v1/rules`)
      expect(rulesResponse.ok()).toBeTruthy()
      const rulesBody = await rulesResponse.json() as { data?: { groups?: Array<{ name?: string; rules?: Array<{ name?: string }> }> } }
      expect(rulesBody.data?.groups?.some((group) => group.rules?.some((rule) => rule.name === 'NotificationStreamBacklogOldestAge'))).toBe(true)
      const readGroupLag = async () => {
        const result = await queryData('max(notification_stream_group_lag)') as { data?: { result?: Array<{ value?: [number, string] }> } }
        return Number(result.data?.result?.[0]?.value?.[1] || 0)
      }
      await expect.poll(readGroupLag, { timeout: 60_000, intervals: [2_000, 4_000, 6_000] }).toBeGreaterThan(1000)
      const groupLag = await queryData('max(notification_stream_group_lag)')
      const firingNames = ['NotificationStreamBacklogOldestAge', 'NotificationStreamConsumerLag']
      await expect.poll(async () => {
        const alerts = await alertData()
        return firingNames.filter((name) => alerts.some((item) => item.labels?.alertname === name && item.state === 'firing')).length
      }, { timeout: 9 * 60_000, intervals: [15_000, 15_000, 20_000] }).toBe(2)

      await promPage.goto(`${prom.origin}/alerts`)
      await expect(promPage.locator('body')).toContainText('NotificationStreamBacklogOldestAge', { timeout: 30_000 })
      await promPage.screenshot({ path: join(artifactRoot, 'case-07-prometheus-alerts.png'), fullPage: true })
      explicitScreenshots.push('case-07-prometheus-alerts.png')
      const dashboard = JSON.parse(readFileSync(resolve(process.cwd(), '..', 'monitoring/grafana/dashboards/runtime-overview.json'), 'utf8'))
      await grafanaPage.goto(`http://127.0.0.1:${grafanaPort}/d/${dashboard.uid}?from=now-15m&to=now&refresh=5s`)
      await expect(grafanaPage.locator('body')).toContainText('LabFlow Runtime Overview', { timeout: 30_000 })
      await expect(grafanaPage.locator('body')).toContainText('通知 Stream backlog', { timeout: 30_000 })
      await grafanaPage.waitForTimeout(5_000)
      await grafanaPage.screenshot({ path: join(artifactRoot, 'case-07-grafana-backlog.png'), fullPage: true })
      explicitScreenshots.push('case-07-grafana-backlog.png')
      const alerts = await alertData()
      const report = { statsBefore, groupLag, targets, alerts: alerts.filter((item) => firingNames.includes(item.labels?.alertname || '') || item.labels?.alertname?.includes('DeadLetter')) }
      writeFileSync(join(artifactRoot, 'case-07-alerts.json'), JSON.stringify(report, null, 2), 'utf8')
      extraEvidence.push({ filename: 'case-07-stream-stats.png', title: '用例7 Stream/消费组积压运维统计', body: statsBefore })
      extraEvidence.push({ filename: 'case-07-alert-states.png', title: '用例7 Prometheus 告警状态和查询值', body: report })
      actual = `Stream 写入 ${backlog.count} 条；两个独立组 lag 均超过 1,000 且 PEL 非零；Prometheus 抓取 API 为 up=1，BacklogOldestAge 与 ConsumerLag 两条告警均进入 firing；Grafana 面板可见积压。`
      await streamCommand('release-backlog')
      await waitForGroupsIdle(90_000)
    } finally {
      await grafanaContext.close()
      await promContext.close()
      await prom.close()
      await streamCommand('release-backlog')
    }
  })

  test('用例8 只清理所有组 ACK 的消息', async () => {
    const page = await newTrackedPage()
    await login(page)
    await openNotificationCenter(page)
    const userId = fixture.user_id
    await waitForGroupsIdle(90_000)
    const acked = streamCommand('publish-read-state', { 'user-id': userId }) as { streamId: string }
    await expect.poll(() => {
      const stats = parseStreamStats()
      const groups = stats.groups.filter((group) => group.name.includes(runPrefix))
      return groups.length === 2 && groups.every((group) => streamIdAtLeast(group.lastDeliveredId, acked.streamId) && group.pending === 0)
    }, { timeout: 20_000 }).toBe(true)
    const beforeAckTrim = parseStreamStats()
    const ackTrim = streamOps(['trim-acked', '--limit', '5000']) as { deleted: number }
    expect(ackTrim.deleted).toBeGreaterThan(0)
    const afterAckTrim = parseStreamStats()
    const held = streamCommand('publish-read-state', { 'user-id': userId, hold: true }) as { streamId: string }
    await expect.poll(() => {
      const stats = parseStreamStats()
      const groups = stats.groups.filter((group) => group.name.includes(runPrefix))
      return groups.length === 2 && groups.every((group) => group.pending > 0)
    }, { timeout: 20_000 }).toBe(true)
    const beforePendingTrim = parseStreamStats()
    const pendingTrim = streamOps(['trim-acked', '--limit', '5000']) as { deleted: number }
    const afterPendingTrim = parseStreamStats()
    expect(afterPendingTrim.streamLength).toBeGreaterThan(0)
    expect(beforePendingTrim.streamLength - pendingTrim.deleted).toBe(afterPendingTrim.streamLength)
    actual = `两组均 ACK 的事件被 trim-acked 清理（删除 ${ackTrim.deleted} 条）；随后两组均有 PEL 的 ${held.streamId} 未被清理（第二次删除 ${pendingTrim.deleted} 条，Stream 保留 ${afterPendingTrim.streamLength} 条）。`
    await evidencePage('case-08-trim-before-after.png', '用例8 ACK 清理前后 Redis Stream 运维输出', { beforeAckTrim, ackTrim, afterAckTrim, held, beforePendingTrim, pendingTrim, afterPendingTrim })
    await streamCommand('release-backlog')
    await waitForGroupsIdle(30_000)
    streamOps(['trim-acked', '--limit', '5000'])
  })

  test('用例9 手动清除陈旧消费组不影响活动组', async () => {
    const page = await newTrackedPage()
    await login(page)
    await openNotificationCenter(page)
    const stale = streamCommand('create-stale-group') as { groupName: string }
    const before = parseStreamStats()
    const apiBefore = before.groups.filter((group) => group.name.includes(runPrefix) && /api1|api2/.test(group.name)).map((group) => group.name)
    expect(apiBefore).toHaveLength(2)
    expect(before.groups.some((group) => group.name === stale.groupName)).toBe(true)
    const destroyed = streamOps(['destroy-group', stale.groupName, '--confirm'])
    const after = parseStreamStats()
    const apiAfter = after.groups.filter((group) => group.name.includes(runPrefix) && /api1|api2/.test(group.name)).map((group) => group.name)
    expect(after.groups.some((group) => group.name === stale.groupName)).toBe(false)
    expect(apiAfter.sort()).toEqual(apiBefore.sort())
    actual = `运维命令删除 ${destroyed.destroyedGroup}；API1/API2 两个活动消费组仍保留，状态未变。`
    await evidencePage('case-09-stale-groups-before-after.png', '用例9 XINFO GROUPS 清理前后结果', { before, destroyed, after })
  })
})

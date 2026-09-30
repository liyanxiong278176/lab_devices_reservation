import { expect, test, type Browser, type BrowserContext, type Page } from '@playwright/test'
import { execFile } from 'node:child_process'
import { readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { promisify } from 'node:util'

type Account = { username: string; user_id: number }
type Manifest = {
  run_id: string
  password: string
  device_ids: Record<string, number[]>
  devices: Record<string, Array<{ id: number; name: string }>>
  accounts: {
    admin: Account
    managers: Record<string, Account>
    students: Record<string, Account[]>
  }
}

const projectRoot = resolve(__dirname, '../..')
const manifestPath = resolve(projectRoot, 'qa_eval/results/fixture.json')
const fixture = JSON.parse(readFileSync(manifestPath, 'utf8')) as Manifest
const pngSignature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])
const execFileAsync = promisify(execFile)
const outboxWorkerPath = resolve(projectRoot, 'qa_eval/outbox_notification_worker.py')
const qaPython = process.env.QA_PYTHON || resolve(projectRoot, 'qa_eval/.venv/Scripts/python.exe')

const frontendBase = process.env.QA_FRONTEND_URL || 'http://127.0.0.1:5174'
const proxyControl = process.env.QA_PROXY_CONTROL_URL || 'http://127.0.0.1:8002'
const sseOrigin = process.env.QA_SSE_ORIGIN || proxyControl

type SseProxyState = {
  blocked: boolean
  cutCount?: number
  reconnects?: Array<{ clientId: string | null; lastEventId: string | null }>
}

async function controlSseProxy(
  action: 'cut' | 'release' | 'status',
  clientId?: string,
): Promise<SseProxyState> {
  const response = await fetch(`${proxyControl}/__qa/${action}`, action === 'status'
    ? { method: 'GET' }
    : {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ clientId }),
    })
  if (!response.ok) throw new Error(`SSE fault proxy ${action} failed with HTTP ${response.status}`)
  return await response.json() as { blocked: boolean; cutCount?: number }
}

async function createContext(browser: Browser, clientId: string): Promise<{ context: BrowserContext; page: Page }> {
  const context = await browser.newContext({
    baseURL: frontendBase,
    timezoneId: 'Asia/Shanghai',
    extraHTTPHeaders: { 'x-qa-client': clientId },
  })
  const page = await context.newPage()
  await page.addInitScript((sseOrigin: string) => {
    const diagnosticWindow = window as Window & {
      __qaSseEvents?: Array<{ type: string; id?: string; replay?: boolean; readyState?: number; at: number }>
    }
    const events = diagnosticWindow.__qaSseEvents = []
    const NativeEventSource = window.EventSource

    class DiagnosticEventSource extends NativeEventSource {
      constructor(url: string | URL, init?: EventSourceInit) {
        const endpoint = new URL(String(url), window.location.href)
        const target = new URL(sseOrigin)
        target.pathname = endpoint.pathname
        target.search = endpoint.search
        target.hash = ''
        super(target.toString(), init)
        super.addEventListener('open', () => events.push({ type: 'open', at: Date.now() }))
        super.addEventListener('error', () => events.push({ type: 'error', readyState: this.readyState, at: Date.now() }))
      }

      override addEventListener(
        type: string,
        listener: EventListenerOrEventListenerObject | null,
        options?: boolean | AddEventListenerOptions,
      ): void {
        if (!listener) return super.addEventListener(type, listener, options)
        const source = this
        super.addEventListener(type, ((event: Event) => {
          let replay: boolean | undefined
          try {
            replay = JSON.parse((event as MessageEvent<string>).data)?.replay
          } catch {
            // Non-JSON notifications are still recorded by event type and ID.
          }
          events.push({
            type,
            id: (event as MessageEvent<string>).lastEventId,
            replay,
            at: Date.now(),
          })
          if (typeof listener === 'function') listener.call(source, event)
          else listener.handleEvent(event)
        }) as EventListener, options)
      }
    }

    Object.defineProperty(window, 'EventSource', { configurable: true, value: DiagnosticEventSource })
  }, sseOrigin)
  return { context, page }
}

async function login(page: Page, account: Account): Promise<void> {
  await page.goto('/login')
  await page.getByPlaceholder('请输入用户名').fill(account.username)
  await page.getByPlaceholder('请输入密码').fill(fixture.password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page).toHaveURL(/\/dashboard$/)
  await expect(page.getByText('实验室预约系统')).toBeVisible()
}

async function createBookingPage(page: Page, deviceId: number, purpose: string, day: string): Promise<void> {
  await page.goto(`/reservations/create?deviceId=${deviceId}&startDate=${day}&endDate=${day}`)
  await page.getByPlaceholder('例如：完成材料拉伸实验并采集三组数据').fill(purpose)
  await expect(page.getByRole('button', { name: '提交预约' })).toBeEnabled({ timeout: 20_000 })
}

test('multiple students, scoped manager, and system admin complete the browser lifecycle', async ({ browser }, testInfo) => {
  const studentA = await createContext(browser, 'studentA')
  const studentB = await createContext(browser, 'studentB')
  const bioStudent = await createContext(browser, 'bioStudent')
  const manager = await createContext(browser, 'manager')
  const admin = await createContext(browser, 'admin')
  const contexts = [studentA.context, studentB.context, bioStudent.context, manager.context, admin.context]
  const streamRequests: Array<{ page: 'studentA' | 'studentB'; lastEventId?: string; failed?: string; at: number }> = []
  for (const [label, page] of [['studentA', studentA.page], ['studentB', studentB.page]] as const) {
    page.on('request', (request) => {
      if (request.url().includes('/api/v2/notifications/stream')) {
        streamRequests.push({ page: label, lastEventId: request.headers()['last-event-id'], at: Date.now() })
        request.on('requestfailed', () => {
          streamRequests.push({
            page: label,
            lastEventId: request.headers()['last-event-id'],
            failed: request.failure()?.errorText,
            at: Date.now(),
          })
        })
      }
    })
  }
  let streamCut = false
  let cutClientId: string | undefined

  try {
    const streamReadyA = studentA.page.waitForResponse(
      (response) => response.url().includes('/api/v2/notifications/stream') && response.status() === 200,
      { timeout: 20_000 },
    )
    const streamReadyB = studentB.page.waitForResponse(
      (response) => response.url().includes('/api/v2/notifications/stream') && response.status() === 200,
      { timeout: 20_000 },
    )
    await Promise.all([
      login(studentA.page, fixture.accounts.students.CSE[0]),
      login(studentB.page, fixture.accounts.students.CSE[1]),
      login(bioStudent.page, fixture.accounts.students.BIO[0]),
      login(manager.page, fixture.accounts.managers.CSE),
      login(admin.page, fixture.accounts.admin),
    ])
    await Promise.all([streamReadyA, streamReadyB])

    await expect(studentA.page.getByRole('menuitem', { name: '待审批' })).toHaveCount(0)
    await studentA.page.goto('/approvals/pending')
    await expect(studentA.page).toHaveURL(/\/dashboard$/)

    await bioStudent.page.goto('/devices')
    const cseDevice = fixture.devices.CSE[0]
    const bioDevice = fixture.devices.BIO[0]
    await expect(bioStudent.page.getByText(bioDevice.name, { exact: true })).toBeVisible()
    await expect(bioStudent.page.getByText(cseDevice.name, { exact: true })).toHaveCount(0)
    const foreignResult = await bioStudent.page.evaluate(async (deviceId) => {
      const response = await fetch(`/api/v2/devices/${deviceId}`)
      return response.status
    }, cseDevice.id)
    expect([403, 404]).toContain(foreignResult)

    await admin.page.goto('/devices')
    await expect(admin.page.getByText(cseDevice.name, { exact: true })).toBeVisible()
    await expect(admin.page.getByText(bioDevice.name, { exact: true })).toBeVisible()
    await expect(admin.page.getByRole('menuitem', { name: '用户管理' })).toBeVisible()

    const today = await winnerDay(studentA.page)
    const purposeA = `qa-e2e-${fixture.run_id}-student-a`
    const purposeB = `qa-e2e-${fixture.run_id}-student-b`
    await Promise.all([
      createBookingPage(studentA.page, cseDevice.id, purposeA, today),
      createBookingPage(studentB.page, cseDevice.id, purposeB, today),
    ])

    await Promise.all([
      studentA.page.getByRole('button', { name: '提交预约' }).click(),
      studentB.page.getByRole('button', { name: '提交预约' }).click(),
    ])
    await expect.poll(async () => {
      return Number(studentA.page.url().endsWith('/reservations/mine'))
        + Number(studentB.page.url().endsWith('/reservations/mine'))
    }, { timeout: 20_000 }).toBe(1)

    const winner = studentA.page.url().endsWith('/reservations/mine') ? studentA : studentB
    const loser = winner === studentA ? studentB : studentA
    const winningPurpose = winner === studentA ? purposeA : purposeB
    await expect(winner.page.locator('.mine__card').filter({ hasText: winningPurpose })).toBeVisible()
    await expect(loser.page.locator('.el-message__content').filter({ hasText: /冲突|占用/ })).toBeVisible()

    // Reset only this user's active SSE socket. Normal HTTP requests remain available
    // so the manager can approve while automatic EventSource retries receive 503.
    const winnerLabel = winner === studentA ? 'studentA' : 'studentB'
    const winnerStreamRequestsBeforeDisconnect = streamRequests.filter(({ page }) => page === winnerLabel).length
    const cut = await controlSseProxy('cut', winnerLabel)
    cutClientId = winnerLabel
    streamCut = true
    expect(cut.cutCount).toBeGreaterThan(0)
    await expect.poll(async () => {
      return winner.page.evaluate(() =>
        Boolean((window as Window & { __qaSseEvents?: Array<{ type: string; readyState?: number }> })
          .__qaSseEvents?.some((event) => event.type === 'error' && event.readyState === EventSource.CONNECTING)),
      )
    }, { timeout: 15_000 }).toBe(true)
    await manager.page.goto('/approvals/pending')
    const approvalCard = manager.page.locator('.approval__card').filter({ hasText: winningPurpose })
    await expect(approvalCard).toBeVisible()
    await approvalCard.getByRole('button', { name: '通过', exact: true }).click()
    await expect(manager.page.getByText('已通过，预约进入设备交接队列')).toBeVisible()
    // Approval commits an Outbox task; wait for that specific notification row
    // to become the history source of truth before releasing the reconnecting browser.
    // The test-mode API deliberately has no background worker; run only this
    // fixture's notification tasks through the production claim/handler code.
    await execFileAsync(qaPython, [outboxWorkerPath, '--manifest', manifestPath], {
      cwd: projectRoot,
      env: process.env,
    })
    await expect.poll(async () => winner.page.evaluate(async () => {
      const response = await fetch('/api/v2/notifications/mine?page=1&size=20')
      const body = await response.json()
      return body.data?.records?.some((record: { title?: string }) => record.title === '预约申请已通过') === true
    }), { timeout: 20_000 }).toBe(true)
    await controlSseProxy('release', winnerLabel)
    streamCut = false
    await expect.poll(async () => streamRequests.filter(({ page }) => page === winnerLabel).length,
      { timeout: 15_000 }).toBeGreaterThan(winnerStreamRequestsBeforeDisconnect)
    await expect.poll(async () => {
      return winner.page.evaluate(() =>
        Boolean((window as Window & { __qaSseEvents?: Array<{ type: string; replay?: boolean }> })
          .__qaSseEvents?.some((event) => event.type === 'batch-complete' && event.replay === true)),
      )
    }, { timeout: 15_000 }).toBe(true)
    const proxyState = await controlSseProxy('status')
    expect(proxyState.reconnects?.some(
      (request) => request.clientId === winnerLabel && request.lastEventId !== null,
    )).toBe(true)
    await expect(winner.page.getByText(/断线期间有\s*\d+\s*条新通知/)).toBeVisible({ timeout: 20_000 })

    await manager.page.goto('/handovers')
    const handoverCard = manager.page.locator('.handover-card').filter({ hasText: winningPurpose })
    await expect(handoverCard).toBeVisible()
    await handoverCard.getByRole('button', { name: '核对并完成交接' }).click()
    const handoverDialog = manager.page.getByRole('dialog')
    await handoverDialog.locator('input[type="file"]').setInputFiles({
      name: 'qa-handover.png', mimeType: 'image/png', buffer: pngSignature,
    })
    await handoverDialog.getByRole('button', { name: '确认', exact: true }).click()
    await expect(manager.page.getByText('设备已完成交接，用户可以开始使用')).toBeVisible()

    await winner.page.goto('/reservations/mine')
    const winningCard = winner.page.locator('.mine__card').filter({ hasText: winningPurpose })
    await expect(winningCard.getByRole('button', { name: '归还', exact: true })).toBeVisible()
    await winningCard.getByRole('button', { name: '归还', exact: true }).click()
    const returnDialog = winner.page.getByRole('dialog')
    await returnDialog.locator('input[type="file"]').setInputFiles({
      name: 'qa-return.png', mimeType: 'image/png', buffer: pngSignature,
    })
    await returnDialog.getByRole('button', { name: '确认归还', exact: true }).click()
    await expect(winner.page.getByText('已提交归还，等待负责人验收')).toBeVisible()

    await manager.page.goto('/handovers')
    await manager.page.getByRole('radio', { name: '待验收' }).click()
    const returnCard = manager.page.locator('.handover-card').filter({ hasText: winningPurpose })
    await expect(returnCard).toBeVisible()
    await returnCard.getByRole('button', { name: '核对并确认验收' }).click()
    const acceptanceDialog = manager.page.getByRole('dialog')
    await acceptanceDialog.getByRole('button', { name: '确认', exact: true }).click()
    await expect(manager.page.getByText('归还已验收，预约已完成')).toBeVisible()

    await winner.page.goto('/notifications')
    await expect(winner.page.getByRole('heading', { name: '通知中心' })).toBeVisible()
    await expect(winner.page.locator('.notif-row').filter({ hasText: '预约' }).first()).toBeVisible()
    await expect(
      winner.page.locator('.notif-row').filter({ hasText: '预约申请已提交' }).first(),
    ).toBeVisible()
    await winner.page.screenshot({ path: testInfo.outputPath('lifecycle-notifications.png'), fullPage: true })

    const repairDevice = fixture.devices.CSE[1]
    const repairTitle = `QA repair ${fixture.run_id} E2E`
    await winner.page.goto('/repairs/submit')
    const repairDeviceSelect = winner.page.locator('.rsubmit__form .el-select__wrapper')
    await expect(repairDeviceSelect).toBeEnabled()
    await repairDeviceSelect.click()
    const repairDeviceOption = winner.page.getByRole('option', { name: new RegExp(repairDevice.name) })
    await expect(repairDeviceOption).toBeVisible()
    await repairDeviceOption.click()
    await winner.page.getByPlaceholder('一句话描述故障').fill(repairTitle)
    await winner.page.getByPlaceholder('故障现象、复现步骤等').fill('E2E 验证报修从提交到确认的完整闭环')
    await winner.page.getByRole('button', { name: '提交报修', exact: true }).click()
    await expect(winner.page.getByText('报修已提交')).toBeVisible()

    await manager.page.goto('/repairs')
    const repairRow = manager.page.locator('.el-table__row').filter({ hasText: repairTitle })
    await expect(repairRow).toBeVisible()
    await repairRow.getByRole('button', { name: '受理', exact: true }).click()
    await expect(manager.page.getByText('已受理', { exact: true })).toBeVisible()
    const processingRow = manager.page.locator('.el-table__row').filter({ hasText: repairTitle })
    await processingRow.getByRole('button', { name: '解决', exact: true }).click()
    await manager.page.getByPlaceholder('说明处理方式与结果(必填)').fill('QA E2E：更换线缆后设备恢复正常')
    await manager.page.getByRole('button', { name: '确认处理', exact: true }).click()
    await expect(manager.page.getByText('已标记解决，等待用户确认')).toBeVisible()

    await winner.page.goto('/repairs/mine')
    const ownRepair = winner.page.locator('.rmine__card').filter({ hasText: repairTitle })
    await expect(ownRepair.locator('.rmine__card-head .el-tag__content')).toHaveText('待用户确认')
    await ownRepair.getByRole('button', { name: '确认已修复', exact: true }).click()
    const confirmRepairDialog = winner.page.getByRole('dialog')
    await expect(confirmRepairDialog.getByText('确认设备已经恢复正常并关闭这条报修？')).toBeVisible()
    await confirmRepairDialog.getByRole('button', { name: '确认已修复', exact: true }).click()
    await expect(winner.page.getByText('报修已完成')).toBeVisible()
    await expect(ownRepair.locator('.rmine__card-head .el-tag__content')).toHaveText('已完成')
  } finally {
    const diagnostics = await Promise.all([studentA.page, studentB.page].map(async (page) => ({
      page: page === studentA.page ? 'studentA' : 'studentB',
      url: page.url(),
      events: await page.evaluate(() =>
        (window as Window & { __qaSseEvents?: unknown[] }).__qaSseEvents ?? [],
      ).catch(() => []),
      streamRequests: streamRequests.filter(({ page: requestPage }) => requestPage === (page === studentA.page ? 'studentA' : 'studentB')),
    })))
    writeFileSync(testInfo.outputPath('sse-reconnect-diagnostics.json'), JSON.stringify(diagnostics, null, 2))
    await testInfo.attach('sse-reconnect-diagnostics.json', {
      body: JSON.stringify(diagnostics, null, 2),
      contentType: 'application/json',
    })
    if (streamCut) {
      await controlSseProxy('release', cutClientId)
    }
    await Promise.all(contexts.map((context) => context.close()))
  }
})

async function winnerDay(page: Page): Promise<string> {
  return page.evaluate(() => {
    const current = new Date()
    const month = String(current.getMonth() + 1).padStart(2, '0')
    const day = String(current.getDate()).padStart(2, '0')
    return `${current.getFullYear()}-${month}-${day}`
  })
}

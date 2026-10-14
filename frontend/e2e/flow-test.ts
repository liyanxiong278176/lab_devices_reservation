import { test as base, expect, type Page, type Locator } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import { dirname } from 'node:path'

/** Opt-in screenshots of real browser actions; ordinary E2E runs use the same base fixtures. */
export const test = base.extend<{ flowCapture: void }>({
  flowCapture: [async ({ browser }, use, testInfo) => {
    if (process.env.E2E_FLOW_CAPTURE !== '1') { await use(); return }
    const steps: { index: number; action: string; url: string; file: string }[] = []
    let screenshotIndex = 0
    const actions = new Set(['click', 'fill', 'check', 'uncheck', 'selectOption', 'setInputFiles', 'press'])
    const queues = new WeakMap<Page, Promise<void>>()
    const capture = async (page: Page, action: string) => {
      const job = (queues.get(page) ?? Promise.resolve()).then(async () => {
        if (page.isClosed() || !/^https?:/.test(page.url())) return
        const index = ++screenshotIndex
        const file = `flow-${String(index).padStart(4, '0')}.png`
        const path = testInfo.outputPath(file)
        await mkdir(dirname(path), { recursive: true })
        // Keep the viewport fixed: resizing an open Element Plus table/drawer for every action
        // can itself trigger ResizeObserver loops. Existing final full-page shots are preserved.
        await page.screenshot({ path, fullPage: false, animations: 'disabled', timeout: 7000 })
        steps.push({ index, action, url: new URL(page.url()).pathname, file })
      }).catch(() => { /* Final assertion screenshots and the test result remain authoritative. */ })
      queues.set(page, job)
      await job
    }
    const wrapLocator = (page: Page, locator: Locator): Locator => new Proxy(locator, {
      get(target, property) {
        const value = Reflect.get(target, property)
        if (typeof value !== 'function' || property === 'constructor') return value
        return (...args: unknown[]) => {
          const result = value.apply(target, args)
          if (actions.has(String(property))) return Promise.resolve(result).then(async (value) => {
            // Record the control/action, never entered values (including passwords).
            const labels: Record<string, string> = { click: '点击', fill: '填写', check: '勾选', uncheck: '取消勾选', selectOption: '选择', setInputFiles: '上传测试附件', press: '键盘操作' }
            const control = target.toString().match(/name: ['"]([^'"]+)['"]|getBy(?:Label|Text|Placeholder)\(['"]([^'"]+)['"]/)
            await capture(page, `${labels[String(property)]}${control ? ' · ' + (control[1] || control[2]) : '控件'}`)
            return value
          })
          if (result && typeof result.click === 'function' && typeof result.count === 'function')
            return wrapLocator(page, result)
          return result
        }
      },
    })
    const instrument = (page: Page) => {
      for (const method of ['locator', 'getByRole', 'getByLabel', 'getByText', 'getByPlaceholder', 'getByTestId', 'getByTitle', 'getByAltText'] as const) {
        const original = page[method].bind(page) as (...args: unknown[]) => Locator
        Object.defineProperty(page, method, { configurable: true, value: (...args: unknown[]) => wrapLocator(page, original(...args)) })
      }
      const goto = page.goto.bind(page)
      page.goto = async (...args) => { const response = await goto(...args); await capture(page, '打开页面'); return response }
    }
    const original = browser.newContext.bind(browser)
    browser.newContext = async (...args) => {
      const context = await original(...args)
      context.on('page', instrument)
      return context
    }
    try { await use() } finally {
      browser.newContext = original
      const manifest = testInfo.outputPath('flow-steps.json')
      await mkdir(dirname(manifest), { recursive: true })
      await writeFile(manifest, JSON.stringify({ title: testInfo.title, status: testInfo.status, steps: steps.sort((a, b) => a.index - b.index) }, null, 2))
    }
  }, { auto: true }],
})
export { expect }
export type { Page, Locator, TestInfo } from '@playwright/test'

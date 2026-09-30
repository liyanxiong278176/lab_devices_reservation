import { chromium, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mkdirSync } from 'node:fs'

const baseURL = process.env.PREVIEW_URL || 'http://127.0.0.1:18080'
const username = process.env.QA_STUDENT_USERNAME
const password = process.env.QA_STUDENT_PASSWORD
const artifactDir = process.env.QA_ARTIFACT_DIR || '.artifacts/non-ai-preview'
const xssTitle = process.env.QA_XSS_TITLE || '<img src=x onerror=alert(1)> QA260928'

mkdirSync(artifactDir, { recursive: true })

if (!username || !password) {
  throw new Error('Set QA_STUDENT_USERNAME and QA_STUDENT_PASSWORD for the isolated fixture user.')
}

const browser = await chromium.launch({ headless: true })
  const pageErrors = []
  const consoleErrors = []
  let authenticated = false
  let expectedAnonymousMe401 = 0
  let dialogs = 0

try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await context.newPage()
  page.on('pageerror', (error) => pageErrors.push(error.message))
  page.on('console', (message) => {
    const isAnonymousMe401 =
      !authenticated &&
      message.location().url.includes('/api/v2/auth/me') &&
      message.text().includes('401')
    if (isAnonymousMe401) return
    if (message.type() === 'error') consoleErrors.push(`${message.text()} @ ${message.location().url}`)
  })
  page.on('response', (response) => {
    const isAnonymousMe401 =
      !authenticated && response.status() === 401 && response.url().endsWith('/api/v2/auth/me')
    if (isAnonymousMe401) {
      expectedAnonymousMe401 += 1
      return
    }
    if (response.status() >= 400) consoleErrors.push(`HTTP ${response.status()} ${response.url()}`)
  })
  page.on('dialog', async (dialog) => {
    dialogs += 1
    await dialog.dismiss()
  })

  const scans = []
  async function scan(label) {
    const result = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze()
    const serious = result.violations.filter((item) => ['critical', 'serious'].includes(item.impact))
    scans.push({ label, violations: result.violations.length, serious: serious.length })
    if (serious.length) {
      const details = serious
        .map((item) =>
          `${item.id}: ${item.nodes.slice(0, 4).map((node) => `${node.target.join(' ')} — ${node.failureSummary}`).join(' | ')}`,
        )
        .join('; ')
      throw new Error(`${label} has serious accessibility violations: ${details}`)
    }
  }

  await page.goto(`${baseURL}/login`, { waitUntil: 'networkidle' })
  await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible()
  await scan('login')

  // Keyboard focus must reach the login controls before submitting the form.
  await page.locator('body').press('Tab')
  const firstFocus = await page.evaluate(() => document.activeElement?.tagName.toLowerCase())
  expect(firstFocus).toBe('input')
  await page.locator('input').nth(0).fill(username)
  await page.locator('input').nth(1).fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL('**/dashboard', { timeout: 15_000 })
  authenticated = true
  await expect(page.locator('.login-page')).toHaveCount(0)
  await expect(page.locator('main.layout__main')).toBeVisible()

  await scan('student dashboard')
  await page.goto(`${baseURL}/devices`, { waitUntil: 'networkidle' })
  await expect(page.locator('main.layout__main')).toBeVisible()
  await scan('device catalog')
  await page.goto(`${baseURL}/reservations/mine`, { waitUntil: 'networkidle' })
  await expect(page.locator('main.layout__main')).toBeVisible()
  await scan('my reservations')
  await page.goto(`${baseURL}/notifications`, { waitUntil: 'networkidle' })
  await expect(page.locator('main.layout__main')).toBeVisible()
  await expect(page.getByText(xssTitle, { exact: true })).toBeVisible()
  await scan('notification history')

  const xssElementCount = await page.locator('img[src="x"]').count()
  expect(xssElementCount).toBe(0)
  expect(dialogs).toBe(0)

  await page.setViewportSize({ width: 375, height: 812 })
  await page.waitForTimeout(300)
  const mobileWidth = await page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
    offenders: Array.from(document.querySelectorAll('body *'))
      .map((element) => {
        const rect = element.getBoundingClientRect()
        return {
          tag: element.tagName.toLowerCase(),
          className: typeof element.className === 'string' ? element.className : '',
          left: Math.round(rect.left * 10) / 10,
          right: Math.round(rect.right * 10) / 10,
          width: Math.round(rect.width * 10) / 10,
        }
      })
      .filter((element) => element.right > window.innerWidth + 0.5 || element.left < -0.5)
      .slice(0, 8),
  }))
  if (mobileWidth.document > mobileWidth.viewport + 1) {
    throw new Error(`Mobile horizontal overflow: ${JSON.stringify(mobileWidth)}`)
  }
  await page.screenshot({ path: `${artifactDir}/student-mobile.png`, fullPage: true })

  if (pageErrors.length || consoleErrors.length) {
    throw new Error(
      `Browser errors: page=${pageErrors.length}, console=${consoleErrors.length}; ` +
        [...pageErrors, ...consoleErrors].slice(0, 5).join(' | '),
    )
  }

  console.log(
    JSON.stringify(
      {
        status: 'passed',
        screens: scans,
        xssElements: xssElementCount,
        dialogs,
        expectedAnonymousMe401,
        mobileWidth,
        browserErrors: 0,
      },
      null,
      2,
    ),
  )
  await context.close()
} finally {
  await browser.close()
}

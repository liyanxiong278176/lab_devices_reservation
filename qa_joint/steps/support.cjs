const fs = require('node:fs/promises')
const path = require('node:path')
const { execFileSync } = require('node:child_process')

const qaRoot = path.resolve(__dirname, '..')
const fixtures = JSON.parse(require('node:fs').readFileSync(path.join(qaRoot, '.runtime', 'fixtures.json'), 'utf8'))
const fixture = (prefix) => {
  const found = fixtures.find((item) => item.prefix === prefix)
  if (!found) throw new Error('Fixture metadata is missing for ' + prefix)
  return found
}

const password = () => {
  if (!process.env.QA_JOINT_PASSWORD) throw new Error('QA_JOINT_PASSWORD must be set in the local shell')
  return process.env.QA_JOINT_PASSWORD
}

function dateAfter(days) {
  const date = new Date()
  date.setHours(12, 0, 0, 0)
  date.setDate(date.getDate() + days)
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return year + '-' + month + '-' + day
}

function pngBuffer() {
  const zlib = require('node:zlib')
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])
  const crc32 = (buffer) => {
    let crc = 0xffffffff
    for (const byte of buffer) {
      crc ^= byte
      for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0)
    }
    return (crc ^ 0xffffffff) >>> 0
  }
  const chunk = (name, data) => {
    const type = Buffer.from(name, 'ascii')
    const length = Buffer.alloc(4)
    length.writeUInt32BE(data.length)
    const checksum = Buffer.alloc(4)
    checksum.writeUInt32BE(crc32(Buffer.concat([type, data])))
    return Buffer.concat([length, type, data, checksum])
  }
  const header = Buffer.alloc(13)
  header.writeUInt32BE(1, 0)
  header.writeUInt32BE(1, 4)
  header[8] = 8
  header[9] = 6
  const imageData = zlib.deflateSync(Buffer.from([0, 35, 112, 210, 255, 255]))
  return Buffer.concat([signature, chunk('IHDR', header), chunk('IDAT', imageData), chunk('IEND', Buffer.alloc(0))])
}

async function snap(page, folder, step, role, action, result = 'ok') {
  const directory = path.join(qaRoot, 'screenshots', folder)
  await fs.mkdir(directory, { recursive: true })
  const file = path.join(directory, step + '_' + role + '_' + action + '_' + result + '.png')
  await page.screenshot({ path: file, fullPage: true, animations: 'disabled' })
  return file
}

async function signIn(page, username, folder = '00-preflight', role = username.endsWith('admin') ? 'admin' : 'user') {
  await page.goto('/login')
  await page.getByLabel('用户名').fill(username)
  await page.getByLabel('密码').fill(password())
  await snap(page, folder, '01', role, 'login_before')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.waitForURL(/\/dashboard(?:\?.*)?$/, { timeout: 20_000 })
  await page.getByText('实验室预约系统', { exact: true }).waitFor()
  await snap(page, folder, '02', role, 'login_result')
}

async function openReservation(page, deviceId, deviceName) {
  await page.goto('/devices')
  const card = page.locator('.device-card').filter({
    has: page.locator('.device-card__brand').getByText(deviceName, { exact: true }),
  })
  await card.waitFor({ state: 'visible' })
  await card.getByRole('button', { name: '预约', exact: true }).click()
  await page.waitForURL(/\/reservations\/create/)
  await page.getByRole('heading', { name: '预约设备', exact: true }).waitFor()
  if (deviceId) await page.locator('.reserve-create-v2__device').getByText(deviceName, { exact: true }).waitFor()
}

async function fillDateRange(page, startDate, endDate) {
  const start = page.locator('input[placeholder="开始日期"]')
  const end = page.locator('input[placeholder="结束日期"]')
  await start.click()
  await start.fill(startDate)
  await start.press('Enter')
  await end.fill(endDate)
  await end.press('Enter')
}

async function fillReservationForm(page, startDate, endDate, purpose) {
  await fillDateRange(page, startDate, endDate)
  await page.getByPlaceholder('例如：完成材料拉伸实验并采集三组数据').fill(purpose)
  await page.locator('.preflight-card').waitFor()
  await page.waitForFunction(() => {
    const text = document.querySelector('.preflight-card')?.innerText || ''
    return /可用|冲突/.test(text) && !document.querySelector('.preflight-card.is-loading')
  }, null, { timeout: 25_000 })
}

async function api(page, endpoint, { method = 'GET', body, csrf = true, idempotencyKey } = {}) {
  return page.evaluate(async ({ endpoint, method, body, csrf, idempotencyKey }) => {
    const headers = { Accept: 'application/json' }
    if (body !== undefined) headers['Content-Type'] = 'application/json'
    if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey
    if (csrf && !['GET', 'HEAD', 'OPTIONS'].includes(method.toUpperCase())) {
      const token = localStorage.getItem('lab-auth-csrf-token')
      if (token) headers['X-CSRF-Token'] = token
    }
    try {
      const response = await fetch(endpoint.startsWith('/api/v2/') ? endpoint : '/api/v2' + endpoint, {
        method,
        headers,
        credentials: 'include',
        body: body === undefined ? undefined : JSON.stringify(body),
      })
      const text = await response.text()
      let payload
      try {
        payload = JSON.parse(text)
      } catch {
        payload = { detail: text.slice(0, 500) }
      }
      return { status: response.status, payload }
    } catch (error) {
      return { status: 0, payload: { code: 'NETWORK_ERROR', message: String(error) } }
    }
  }, { endpoint, method, body, csrf, idempotencyKey })
}

function databaseReservationsForPurpose(purpose) {
  const backend = path.resolve(qaRoot, '..', 'backend')
  const script = path.join(qaRoot, 'scripts', 'db_assertions.py')
  const stdout = execFileSync('uv', ['run', 'python', script, '--purpose', purpose], {
    cwd: backend,
    encoding: 'utf8',
    timeout: 30_000,
    windowsHide: true,
  })
  return JSON.parse(stdout.trim())
}

async function showApiResult(page, result, method, endpoint) {
  const safe = {
    status: result.status,
    code: result.payload?.code || result.payload?.detail?.[0]?.type || 'HTTP_ERROR',
    message: result.payload?.message || result.payload?.detail?.[0]?.msg || result.payload?.detail || '',
  }
  await page.evaluate((details) => {
    let panel = document.querySelector('[data-qa-joint-api-result]')
    if (!panel) {
      panel = document.createElement('aside')
      panel.setAttribute('data-qa-joint-api-result', 'true')
      panel.style.cssText = 'position:fixed;z-index:99999;right:20px;bottom:20px;max-width:720px;padding:16px 20px;border:2px solid #ef4444;border-radius:12px;background:#111827;color:#fff;font:14px/1.6 ui-monospace,monospace;white-space:pre-wrap;box-shadow:0 12px 40px #0008;pointer-events:none'
      document.body.appendChild(panel)
    }
    panel.textContent = '真实 API 失败响应\n' + details.method + ' ' + details.endpoint + '\nHTTP ' + details.status + ' · ' + details.code + '\n' + String(details.message)
  }, { ...safe, method, endpoint })
}

function listenApiErrors(page) {
  const errors = []
  page.on('response', async (response) => {
    const url = response.url()
    if (!url.includes('/api/v2/')) return
    if (response.status() < 400) return
    let body = {}
    try {
      body = await response.json()
    } catch {
      // Keep status and path even when a failed response is not JSON.
    }
    errors.push({ status: response.status(), path: new URL(url).pathname, code: body.code || 'HTTP_ERROR', message: body.message || '' })
  })
  return errors
}

module.exports = {
  api,
  dateAfter,
  databaseReservationsForPurpose,
  fillDateRange,
  fillReservationForm,
  fixture,
  listenApiErrors,
  openReservation,
  password,
  pngBuffer,
  qaRoot,
  showApiResult,
  signIn,
  snap,
}

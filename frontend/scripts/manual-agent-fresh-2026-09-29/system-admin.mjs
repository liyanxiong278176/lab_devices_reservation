import { chromium } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import readline from 'node:readline'
import { fileURLToPath } from 'node:url'

const BASE_URL = 'http://127.0.0.1:5173'
const PREFIX = 'e2e-manual-agent-qa260929a'
const USERNAME = `${PREFIX}-admin`
const PASSWORD = 'E2e-123456'
const TARGET_DATE = '2026-09-29'
const EXPECTED_RESERVATIONS = new Map([['71538', '11935'], ['71539', '11936']])
const EXPECTED_DEVICE_IDS = new Set(EXPECTED_RESERVATIONS.values())
const EXPECTED_COLLEGE = 'E2E 测试学院 e2e-manual-agent-qa260929a'
const ALREADY_APPROVED_RESERVATIONS = [
  { reservationId: '71538', deviceId: '11935', deviceName: `${PREFIX}-device`, date: TARGET_DATE, username: `${PREFIX}-user`, userId: '2366', applicant: 'E2E 普通用户', college: EXPECTED_COLLEGE },
  { reservationId: '71539', deviceId: '11936', deviceName: `${PREFIX}-device-2`, date: TARGET_DATE, username: `${PREFIX}-user2`, userId: '2367', applicant: 'E2E 候补用户', college: EXPECTED_COLLEGE },
]
const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url))
const ARTIFACT_DIR = path.resolve(SCRIPT_DIR, '../../.artifacts/manual-agent-fresh-2026-09-29/system-admin')

await mkdir(ARTIFACT_DIR, { recursive: true })

const log = []
const pageErrors = []
const browser = await chromium.launch({ headless: false })
const context = await browser.newContext({ viewport: { width: 1536, height: 1050 }, deviceScaleFactor: 1 })
const page = await context.newPage()

function record(event, details = {}) {
  const entry = { at: new Date().toISOString(), event, ...details }
  log.push(entry)
  console.log(JSON.stringify(entry))
}

function watchPage(target, label) {
  target.on('pageerror', (error) => {
    const detail = { type: 'pageerror', page: label, message: error.message }
    pageErrors.push(detail)
    record('browser-error', detail)
  })
  target.on('console', (message) => {
    if (message.type() === 'error') {
      const detail = { type: 'console', page: label, message: message.text() }
      pageErrors.push(detail)
      record('browser-error', detail)
    }
  })
  target.on('requestfailed', (request) => {
    const detail = { type: 'requestfailed', page: label, url: request.url(), error: request.failure()?.errorText }
    pageErrors.push(detail)
    record('browser-error', detail)
  })
}

watchPage(page, 'admin')

async function screenshot(name, target = page) {
  const output = path.join(ARTIFACT_DIR, name)
  await target.screenshot({ path: output, fullPage: true, animations: 'disabled' })
  record('screenshot', { path: output })
}

async function waitForUi(condition, description, timeoutMs = 180000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (await condition()) return
    await page.waitForTimeout(2500)
  }
  throw new Error(`Timed out waiting for ${description}`)
}

function extractReservationId(text) {
  const match = text.match(/RESERVATION\s+#(\d+)/i)
  if (match) return match[1]
  const alt = text.match(/预约申请\s+#(\d+)/)
  return alt?.[1]
}

function deviceIdFromApproval(text) {
  return text.match(/设备编号\s*#(\d+)/)?.[1]
}

function verifyReservationSet(records, phase) {
  const ids = records.map((item) => String(item.deviceId))
  const unique = new Set(ids)
  if (records.length !== 2 || unique.size !== 2 || [...unique].some((id) => !EXPECTED_DEVICE_IDS.has(id))) {
    throw new Error(`${phase}: expected exactly device IDs 11935 and 11936; got ${JSON.stringify(records)}`)
  }
  if (records.some((item) => item.date !== TARGET_DATE)) {
    throw new Error(`${phase}: expected date ${TARGET_DATE}; got ${JSON.stringify(records)}`)
  }
}

async function approvalCards() {
  const cards = page.locator('.approval__card')
  const result = []
  for (let i = 0; i < await cards.count(); i += 1) {
    const card = cards.nth(i)
    const text = await card.innerText()
    const reservationId = (await card.locator('.approval__card-id').innerText()).match(/#(\d+)/)?.[1]
    if (!reservationId || !EXPECTED_RESERVATIONS.has(reservationId) || !text.includes(TARGET_DATE)) continue
    result.push({ card, text, reservationId: `#${reservationId}` })
  }
  return result
}

async function verifyCollegeUiNoTransientGlobal() {
  const username = `${PREFIX}-user2`
  await page.getByRole('menuitem', { name: '用户管理' }).click()
  await page.waitForURL('**/users')
  await page.evaluate((targetUsername) => {
    const samples = []
    const sample = () => {
      const rows = [...document.querySelectorAll('.umanage__table .el-table__body tr')]
        .map((row) => row.innerText.replace(/\s+/g, ' ').trim())
        .filter((text) => text.includes(targetUsername))
      if (rows.length) samples.push({ at: performance.now(), rows })
    }
    const root = document.querySelector('.umanage__table') || document.body
    const observer = new MutationObserver(sample)
    observer.observe(root, { subtree: true, childList: true, characterData: true, attributes: true })
    window.__manualCollegeUiObservation = { samples, observer }
    sample()
  }, username)
  await page.locator('input[placeholder="用户名"]').fill(username)
  await page.getByRole('button', { name: '查询', exact: true }).click()
  const row = page.locator('.umanage__table .el-table__body tr').filter({ hasText: username })
  await row.waitFor({ state: 'visible', timeout: 20000 })
  await waitForUi(async () => (await row.innerText()).includes(EXPECTED_COLLEGE), 'user2 row to render college 656 after options load', 30000)
  await page.waitForTimeout(300)
  const rowText = (await row.innerText()).replace(/\s+/g, ' ').trim()
  const observedRows = await page.evaluate(() => {
    const observation = window.__manualCollegeUiObservation
    observation?.observer.disconnect()
    return observation?.samples.flatMap((sample) => sample.rows) || []
  })
  if (observedRows.some((text) => text.includes('全局'))) {
    throw new Error(`UI briefly rendered user2 as global before college mapping: ${JSON.stringify(observedRows)}`)
  }
  const apiResponses = await page.evaluate(async (targetUsername) => {
    const requests = [
      { key: 'colleges', url: '/api/v2/colleges' },
      { key: 'user', url: `/api/v2/users?username=${encodeURIComponent(targetUsername)}` },
    ]
    const entries = await Promise.all(requests.map(async ({ key, url }) => {
      const response = await fetch(url, { method: 'GET', credentials: 'same-origin' })
      return { key, url, status: response.status, json: await response.json() }
    }))
    return Object.fromEntries(entries.map((entry) => [entry.key, entry]))
  }, username)
  const collegeRows = Array.isArray(apiResponses.colleges.json)
    ? apiResponses.colleges.json
    : apiResponses.colleges.json?.records || apiResponses.colleges.json?.items || apiResponses.colleges.json?.data || []
  const userRows = Array.isArray(apiResponses.user.json)
    ? apiResponses.user.json
    : apiResponses.user.json?.records || apiResponses.user.json?.items || apiResponses.user.json?.data?.records || []
  const user = userRows.find((candidate) => candidate.username === username)
  const college = collegeRows.find((candidate) => Number(candidate.id) === 656)
  const evidence = {
    rowText,
    rowSnapshots: observedRows,
    colleges: { status: apiResponses.colleges.status, college656: college || null },
    user: {
      status: apiResponses.user.status,
      record: user ? { id: user.id, username: user.username, college_id: user.college_id, roles: user.roles } : null,
    },
  }
  if (apiResponses.colleges.status !== 200 || apiResponses.user.status !== 200 || Number(user?.college_id) !== 656 || Number(college?.id) !== 656) {
    throw new Error(`Same-origin UI diagnostic does not confirm user/college 656: ${JSON.stringify(evidence)}`)
  }
  await screenshot('11-user2-college-after-load-fix.png')
  await writeFile(path.join(ARTIFACT_DIR, 'college-ui-after-load-fix.json'), JSON.stringify(evidence, null, 2), 'utf8')
  record('college-ui-after-load-fix', evidence)
}

async function handoverCards() {
  const cards = page.locator('.handover-card')
  const result = []
  for (let i = 0; i < await cards.count(); i += 1) {
    const card = cards.nth(i)
    const text = await card.innerText()
    const reservationId = extractReservationId(text)
    if (reservationId && EXPECTED_RESERVATIONS.has(reservationId) && text.includes(TARGET_DATE)) {
      result.push({ card, text, reservationId })
    }
  }
  return result
}

async function createPngEvidence(reservationId) {
  const pngDataUrl = await page.evaluate((caption) => {
    const canvas = document.createElement('canvas')
    canvas.width = 960
    canvas.height = 540
    const context = canvas.getContext('2d')
    if (!context) throw new Error('Canvas 2D context unavailable')
    const gradient = context.createLinearGradient(0, 0, 960, 540)
    gradient.addColorStop(0, '#0d2638')
    gradient.addColorStop(1, '#176b83')
    context.fillStyle = gradient
    context.fillRect(0, 0, 960, 540)
    context.strokeStyle = 'rgba(127, 239, 236, .7)'
    context.lineWidth = 5
    context.strokeRect(38, 38, 884, 464)
    context.fillStyle = '#b5f7f1'
    context.font = '600 30px sans-serif'
    context.fillText('LABFLOW · 现场交接记录', 76, 132)
    context.fillStyle = '#ffffff'
    context.font = '700 46px sans-serif'
    context.fillText(caption, 76, 230)
    context.font = '26px sans-serif'
    context.fillStyle = '#d4e9ef'
    context.fillText('系统管理员现场核对 · 配件状态正常', 76, 306)
    context.fillText('2026-09-29  |  Fresh UI journey', 76, 368)
    return canvas.toDataURL('image/png')
  }, `预约 ${reservationId}`)
  const output = path.join(ARTIFACT_DIR, `handover-evidence-reservation-${reservationId}.png`)
  await writeFile(output, Buffer.from(pngDataUrl.split(',')[1], 'base64'))
  return output
}

async function enterApp() {
  await page.goto(`${BASE_URL}/login`, { waitUntil: 'domcontentloaded' })
  await page.locator('input[placeholder="请输入用户名"]').fill(USERNAME)
  await page.locator('input[type="password"]').fill(PASSWORD)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.waitForURL((url) => url.pathname !== '/login' && url.pathname !== '/register', { timeout: 30000 })
  await page.getByRole('menuitem', { name: '待审批' }).waitFor({ state: 'visible', timeout: 30000 })
  record('login-success', { username: USERNAME, path: new URL(page.url()).pathname })
  await screenshot('01-login-dashboard.png')
}

async function approveTwo() {
  await page.getByRole('menuitem', { name: '待审批' }).click()
  await page.waitForURL('**/approvals/pending')
  // The approval list loads only on entry. Refresh after both users submit so
  // this runner sees the current database-backed list through the real UI.
  await page.reload({ waitUntil: 'domcontentloaded' })
  await waitForUi(async () => (await approvalCards()).length === 2, 'reservations #71538 and #71539 in pending approvals')
  const candidates = await approvalCards()
  const approvalRecords = []
  for (const candidate of candidates) {
    const cardId = candidate.reservationId.match(/#(\d+)/)?.[1]
    if (!cardId) throw new Error(`Could not read reservation id from ${candidate.reservationId}`)
    await candidate.card.click()
    const drawer = page.locator('.approval-drawer')
    await drawer.waitFor({ state: 'visible' })
    const detailText = await drawer.innerText()
    const deviceId = deviceIdFromApproval(detailText)
    const dateRange = detailText.match(/预约日期\s*([\d-]+)\s*至\s*([\d-]+)/)
    const date = dateRange?.[1]
    const endDate = dateRange?.[2]
    const heroLines = (await drawer.locator('.approval-drawer__hero').innerText()).split('\n').map((line) => line.trim()).filter(Boolean)
    const username = heroLines.at(-1)
    const applicant = heroLines.slice(1, -1).join(' ')
    const userId = detailText.match(/用户编号\s*#(\d+)/)?.[1]
    const checks = [
      ['reservationId', `#${cardId}`, detailText.includes(`#${cardId}`)],
      ['username', username, Boolean(username && detailText.includes(username) && username.includes(PREFIX))],
      ['deviceId', EXPECTED_RESERVATIONS.get(cardId), deviceId === EXPECTED_RESERVATIONS.get(cardId)],
      ['startDate', TARGET_DATE, date === TARGET_DATE],
      ['endDate', TARGET_DATE, endDate === TARGET_DATE],
      ['userId', 'present', Boolean(userId)],
    ]
    for (const [field, expected, matches] of checks) {
      record('approval-detail-field', { reservationId: cardId, field, expected, actual: field === 'reservationId' ? cardId : field === 'username' ? username : field === 'deviceId' ? deviceId : field === 'startDate' ? date : field === 'endDate' ? endDate : userId, matches })
    }
    if (
      !detailText.includes(`#${cardId}`)
      || !username
      || !detailText.includes(username)
      || !username.includes(PREFIX)
      || !deviceId
      || deviceId !== EXPECTED_RESERVATIONS.get(cardId)
      || date !== TARGET_DATE
      || endDate !== TARGET_DATE
      || !userId
    ) {
      throw new Error(`Approval #${cardId} did not match the fresh account/date: ${detailText}`)
    }
    approvalRecords.push({ reservationId: cardId, deviceId, date, username, userId, applicant, detail: detailText })
    await screenshot(`02-approval-detail-${cardId}.png`)
    await drawer.getByRole('button', { name: '关闭' }).click()
  }
  verifyReservationSet(approvalRecords, 'approval queue')
  if (new Set(approvalRecords.map((row) => row.reservationId)).size !== EXPECTED_RESERVATIONS.size) {
    throw new Error(`Expected only reservations ${[...EXPECTED_RESERVATIONS.keys()].join(', ')}`)
  }
  await verifyApplicantColleges(approvalRecords)
  await page.getByRole('menuitem', { name: '待审批' }).click()
  await page.waitForURL('**/approvals/pending')
  await waitForUi(async () => (await approvalCards()).length === 2, 'the two verified reservations after returning to approvals')
  await screenshot('03-approval-targets-ready.png')
  for (const approvalRecord of approvalRecords) {
    const cardIdElement = page.locator('.approval__card-id').filter({ hasText: `#${approvalRecord.reservationId}` })
    const card = page.locator('.approval__card').filter({ has: cardIdElement })
    await card.getByRole('button', { name: '通过', exact: true }).click()
    await page.getByText('已通过，预约进入设备交接队列', { exact: true }).waitFor({ state: 'visible', timeout: 12000 })
    record('approved', { reservationId: approvalRecord.reservationId, deviceId: approvalRecord.deviceId, date: approvalRecord.date, username: approvalRecord.username, applicant: approvalRecord.applicant, college: EXPECTED_COLLEGE, uiState: 'APPROVED' })
    await page.waitForTimeout(600)
  }
  await screenshot('03-approvals-complete.png')
  return approvalRecords
}

async function verifyApplicantColleges(approvalRecords) {
  await page.getByRole('menuitem', { name: '用户管理' }).click()
  await page.waitForURL('**/users')
  for (const approvalRecord of approvalRecords) {
    await page.locator('input[placeholder="用户名"]').fill(approvalRecord.username)
    await page.getByRole('button', { name: '查询', exact: true }).click()
    const row = page.locator('.umanage__table .el-table__body tr').filter({ hasText: approvalRecord.username })
    await row.waitFor({ state: 'visible', timeout: 20000 })
    await waitForUi(async () => (await row.innerText()).includes(EXPECTED_COLLEGE), `${approvalRecord.username} college label to load`, 30000)
    const rowText = (await row.innerText()).replace(/\s+/g, ' ').trim()
    if (!rowText.includes(EXPECTED_COLLEGE)) {
      throw new Error(`User ${approvalRecord.username} is outside the expected college; UI row: ${rowText}`)
    }
    approvalRecord.college = EXPECTED_COLLEGE
    approvalRecord.collegeUiRow = rowText
    await screenshot(`college-verification-user-${approvalRecord.userId}.png`)
    record('applicant-college-verified', { reservationId: approvalRecord.reservationId, username: approvalRecord.username, userId: approvalRecord.userId, college: EXPECTED_COLLEGE, uiRow: rowText })
  }
}

async function runReadonlyCollegeDiagnostic() {
  const username = `${PREFIX}-user2`
  await enterApp()
  await page.getByRole('menuitem', { name: '用户管理' }).click()
  await page.waitForURL('**/users')
  await page.locator('input[placeholder="用户名"]').fill(username)
  await page.getByRole('button', { name: '查询', exact: true }).click()
  const row = page.locator('.umanage__table .el-table__body tr').filter({ hasText: username })
  await row.waitFor({ state: 'visible', timeout: 20000 })
  await waitForUi(async () => (await row.innerText()).includes(EXPECTED_COLLEGE), 'user row to finish rendering its college label', 30000)
  const loadedRowText = (await row.innerText()).replace(/\s+/g, ' ').trim()
  await screenshot('08-user2-college-row-after-load.png')

  const apiEvidence = await page.evaluate(async (targetUsername) => {
    const requests = [
      { key: 'colleges', url: '/api/v2/colleges' },
      { key: 'user', url: `/api/v2/users?username=${encodeURIComponent(targetUsername)}` },
    ]
    const entries = await Promise.all(requests.map(async (request) => {
      const response = await fetch(request.url, { method: 'GET', credentials: 'same-origin' })
      const bodyText = await response.text()
      let json
      try { json = JSON.parse(bodyText) } catch { json = null }
      return { key: request.key, url: request.url, status: response.status, bodyText, json }
    }))
    return Object.fromEntries(entries.map((entry) => [entry.key, entry]))
  }, username)

  const collegePayload = apiEvidence.colleges.json
  const collegeRows = Array.isArray(collegePayload)
    ? collegePayload
    : collegePayload?.records || collegePayload?.items || collegePayload?.data || []
  const userPayload = apiEvidence.user.json
  const userRows = Array.isArray(userPayload)
    ? userPayload
    : userPayload?.records || userPayload?.items || userPayload?.data?.records || []
  const apiUser = userRows.find((candidate) => candidate.username === username)
  const apiCollege = collegeRows.find((candidate) => Number(candidate.id) === 656)
  const conciseEvidence = {
    capturedAt: new Date().toISOString(),
    page: page.url(),
    uiRowTextAfterCollegeOptionsLoaded: loadedRowText,
    collegesResponse: {
      url: apiEvidence.colleges.url,
      status: apiEvidence.colleges.status,
      college656: apiCollege || null,
      returnedIds: collegeRows.map((candidate) => candidate.id),
    },
    userResponse: {
      url: apiEvidence.user.url,
      status: apiEvidence.user.status,
      user: apiUser ? {
        id: apiUser.id,
        username: apiUser.username,
        college_id: apiUser.college_id,
        college_name: apiUser.college_name,
        status: apiUser.status,
        roles: apiUser.roles,
      } : null,
    },
  }
  await writeFile(path.join(ARTIFACT_DIR, 'readonly-college-api-evidence.json'), JSON.stringify(conciseEvidence, null, 2), 'utf8')
  record('readonly-college-api-capture', conciseEvidence)

  await row.getByRole('button', { name: '编辑', exact: true }).click()
  const drawer = page.locator('.umanage-drawer')
  await drawer.waitFor({ state: 'visible', timeout: 15000 })
  const collegeField = drawer.locator('.el-form-item').filter({ hasText: '所属学院' })
  const selectedCollegeText = (await collegeField.innerText()).replace(/\s+/g, ' ').trim()
  await screenshot('09-user2-edit-college-field.png')
  await collegeField.locator('.el-select').click()
  const dropdownOptions = await page.locator('.el-select-dropdown__item').evaluateAll((options) => options.map((option) => ({
    text: option.textContent?.trim() || '',
    selected: option.classList.contains('is-selected') || option.getAttribute('aria-selected') === 'true',
  })))
  await screenshot('10-user2-edit-college-options.png')
  await page.keyboard.press('Escape')
  const diagnostic = {
    ...conciseEvidence,
    selectedCollegeText,
    dropdownOptions,
    noChangesSaved: true,
  }
  await writeFile(path.join(ARTIFACT_DIR, 'readonly-college-diagnostic.json'), JSON.stringify(diagnostic, null, 2), 'utf8')
  record('readonly-edit-drawer-captured', { username, selectedCollegeText, dropdownOptions, noChangesSaved: true })
  console.log('\nRead-only diagnostic complete; edit drawer remains open. No changes were saved. Browser context remains open for review.')
  await waitForCommand('close-browser', 'root finishes reviewing the read-only diagnostic')
}

async function completeHandovers(approvalRecords) {
  await page.getByRole('menuitem', { name: '设备交接' }).click()
  await page.waitForURL('**/handovers')
  await waitForUi(async () => (await handoverCards()).length === 2, 'two approved reservations in handover queue')
  const records = []
  for (const approval of approvalRecords) {
    const item = (await handoverCards()).find((candidate) => candidate.reservationId === approval.reservationId)
    if (!item) throw new Error(`Approved reservation #${approval.reservationId} missing from the pending handover page`)
    if (!item.text.includes(TARGET_DATE)) {
      throw new Error(`Handover card #${approval.reservationId} mismatch: ${item.text}`)
    }
    await item.card.getByRole('button', { name: '核对并完成交接' }).click()
    const dialog = page.locator('.handover-dialog')
    await dialog.waitFor({ state: 'visible' })
    const accessoryRows = dialog.locator('.handover-dialog__check')
    const accessories = []
    for (let i = 0; i < await accessoryRows.count(); i += 1) {
      const row = accessoryRows.nth(i)
      accessories.push((await row.locator('span').first().innerText()).trim())
      if (!(await row.innerText()).includes('正常')) throw new Error(`Accessory did not default to normal: ${await row.innerText()}`)
    }
    const evidenceFile = await createPngEvidence(approval.reservationId)
    await dialog.locator('input[type="file"]').setInputFiles(evidenceFile)
    await page.getByText('1 张已选择', { exact: true }).waitFor({ state: 'visible' })
    await screenshot(`04-handover-dialog-${approval.reservationId}.png`)
    await page.locator('.el-dialog').getByRole('button', { name: '确认', exact: true }).click()
    await page.getByText('设备已完成交接，用户可以开始使用', { exact: true }).waitFor({ state: 'visible', timeout: 30000 })
    await waitForUi(async () => !(await handoverCards()).some((candidate) => candidate.reservationId === approval.reservationId), `reservation #${approval.reservationId} leaves the pending handover queue`, 30000)
    records.push({ ...approval, accessories, evidenceFile, handoverUiState: 'IN_USE (handover completed)' })
    record('handover-completed', { reservationId: approval.reservationId, deviceId: approval.deviceId, date: approval.date, accessories, evidenceFile, uiState: 'IN_USE' })
  }
  await screenshot('05-handover-queue-complete.png')
  if ((await handoverCards()).length !== 0) throw new Error('Pending handover queue was expected to be empty after both actions')
  return records
}

async function inspectReturnPhoto(card, reservationId, photoIndex) {
  const links = card.locator('.handover-card__evidence a')
  const photoLink = links.nth(photoIndex)
  const href = await photoLink.getAttribute('href')
  if (!href) throw new Error(`Reservation #${reservationId} photo link has no href`)
  const imageInfo = await page.evaluate(async ({ source, label }) => {
    const response = await fetch(source, { method: 'GET', credentials: 'include' })
    const blob = await response.blob()
    const objectUrl = URL.createObjectURL(blob)
    const image = new Image()
    await new Promise((resolve, reject) => {
      image.onload = resolve
      image.onerror = reject
      image.src = objectUrl
    })
    const preview = document.createElement('section')
    preview.dataset.manualReturnPhotoPreview = label
    Object.assign(preview.style, {
      position: 'fixed', zIndex: '999999', right: '24px', bottom: '24px',
      maxWidth: 'min(720px, 80vw)', maxHeight: '80vh', padding: '14px',
      background: '#ffffff', color: '#17202a', border: '2px solid #176b83',
      borderRadius: '12px', boxShadow: '0 12px 40px rgba(0,0,0,.35)',
      display: 'grid', gap: '8px',
    })
    const caption = document.createElement('strong')
    caption.textContent = `${label} · HTTP ${response.status} · ${response.headers.get('content-type') || blob.type} · ${blob.size} bytes`
    const renderedImage = document.createElement('img')
    renderedImage.src = objectUrl
    renderedImage.alt = label
    Object.assign(renderedImage.style, { display: 'block', maxWidth: 'min(680px, 76vw)', maxHeight: '68vh', objectFit: 'contain' })
    preview.append(caption, renderedImage)
    document.body.append(preview)
    window.__manualReturnPhotoPreview = { preview, objectUrl }
    return { status: response.status, contentType: response.headers.get('content-type') || blob.type, bytes: blob.size, width: image.naturalWidth, height: image.naturalHeight }
  }, { source: href, label: `归还照片 #${reservationId} 第 ${photoIndex + 1} 张` })
  if (imageInfo.status !== 200 || !imageInfo.contentType?.startsWith('image/') || imageInfo.bytes <= 0 || imageInfo.width <= 0 || imageInfo.height <= 0) {
    throw new Error(`Return photo could not be inspected for #${reservationId}: ${JSON.stringify(imageInfo)}`)
  }
  await screenshot(`return-photo-${reservationId}-${photoIndex + 1}.png`)
  await page.evaluate(() => {
    const preview = window.__manualReturnPhotoPreview
    preview?.preview.remove()
    if (preview?.objectUrl) URL.revokeObjectURL(preview.objectUrl)
    delete window.__manualReturnPhotoPreview
  })
  record('return-photo-inspected', { reservationId, photoIndex: photoIndex + 1, href, imageInfo })
}

async function acceptReturns(approvedRecords) {
  const acceptTab = page.getByRole('radio', { name: '待验收' })
  await acceptTab.click()
  await waitForUi(async () => {
    const cards = page.locator('.handover-card')
    let count = 0
    for (let i = 0; i < await cards.count(); i += 1) {
      const text = await cards.nth(i).innerText()
      if (approvedRecords.some((record) => text.includes(`RESERVATION #${record.reservationId}`))) count += 1
    }
    return count === 2
  }, 'both user returns in the return acceptance queue', 120000)

  const accepted = []
  for (const reservation of approvedRecords) {
    const cards = page.locator('.handover-card')
    let card = null
    for (let i = 0; i < await cards.count(); i += 1) {
      const candidate = cards.nth(i)
      if ((await candidate.innerText()).includes(`RESERVATION #${reservation.reservationId}`)) card = candidate
    }
    if (!card) throw new Error(`Reservation #${reservation.reservationId} not found in return acceptance queue`)
    const cardText = await card.innerText()
    if (!cardText.includes(`${TARGET_DATE} 至 ${TARGET_DATE}`)) throw new Error(`Return acceptance card date mismatch: ${cardText}`)
    if (!cardText.includes(`#${reservation.userId}`) || !cardText.includes(reservation.deviceName)) {
      throw new Error(`Return acceptance card applicant/device mismatch for #${reservation.reservationId}: ${cardText}`)
    }
    const photoCount = await card.locator('.handover-card__evidence a').count()
    if (photoCount < 1 || !cardText.includes(`用户归还现场（${photoCount} 张）`)) {
      throw new Error(`Reservation #${reservation.reservationId} has no inspectable return photo`)
    }
    for (let index = 0; index < photoCount; index += 1) {
      await inspectReturnPhoto(card, reservation.reservationId, index)
    }
    await card.getByRole('button', { name: '核对并确认验收' }).click()
    const dialog = page.locator('.handover-dialog')
    await dialog.waitFor({ state: 'visible' })
    const visiblePhotoCount = await dialog.locator('.handover-dialog__evidence-links a').count()
    if (visiblePhotoCount !== photoCount) throw new Error(`Dialog exposes ${visiblePhotoCount}/${photoCount} return photos for #${reservation.reservationId}`)
    const accessoryRows = dialog.locator('.handover-dialog__check')
    const accessories = []
    for (let i = 0; i < await accessoryRows.count(); i += 1) {
      const row = accessoryRows.nth(i)
      accessories.push((await row.locator('span').first().innerText()).trim())
      if (!(await row.innerText()).includes('正常')) throw new Error(`Accessory did not remain normal for return: ${await row.innerText()}`)
    }
    const acceptanceNote = `管理员验收：已查看 ${photoCount} 张归还照片，${accessories.join('、') || '设备配件'}正常，设备状态正常。`
    await dialog.locator('textarea[placeholder="补充交接或验收说明"]').fill(acceptanceNote)
    await screenshot(`06-return-inspection-${reservation.reservationId}.png`)
    await page.locator('.el-dialog').getByRole('button', { name: '确认', exact: true }).click()
    await page.getByText('归还已验收，预约已完成', { exact: true }).waitFor({ state: 'visible', timeout: 30000 })
    await waitForUi(async () => {
      const visibleCards = page.locator('.handover-card')
      for (let i = 0; i < await visibleCards.count(); i += 1) {
        if ((await visibleCards.nth(i).innerText()).includes(`RESERVATION #${reservation.reservationId}`)) return false
      }
      return true
    }, `reservation #${reservation.reservationId} leaves return acceptance queue`, 30000)
    accepted.push({ reservationId: reservation.reservationId, deviceId: reservation.deviceId, deviceName: reservation.deviceName, userId: reservation.userId, college: reservation.college, date: reservation.date, photoCount, accessories, acceptanceNote, uiState: 'COMPLETED' })
    record('return-accepted', accepted.at(-1))
  }
  await screenshot('07-return-acceptance-queue-empty.png')
  const remaining = await page.locator('.handover-card').count()
  const emptyText = await page.locator('.handover-page__empty').innerText()
  if (remaining !== 0 || !emptyText.includes('暂无待验收设备')) {
    throw new Error(`Expected empty return acceptance queue, cards=${remaining}, message=${emptyText}`)
  }
  return accepted
}

async function waitForCommand(expected, reason = 'the requested next step is ready') {
  console.log(`WAITING: enter "${expected}" when ${reason}.`)
  const terminal = readline.createInterface({ input: process.stdin, output: process.stdout })
  for await (const rawLine of terminal) {
    const command = rawLine.trim()
    if (command === expected) {
      terminal.close()
      return
    }
    console.log(`Ignored command "${command}"; waiting for "${expected}".`)
  }
  throw new Error('Standard input closed while waiting for return submissions')
}

try {
  if (process.argv.includes('--readonly-college-diagnostic')) {
    await runReadonlyCollegeDiagnostic()
  } else if (process.argv.includes('--handover-only')) {
    await enterApp()
    const approvalRecords = ALREADY_APPROVED_RESERVATIONS
    const handovers = await completeHandovers(approvalRecords)
    await writeFile(path.join(ARTIFACT_DIR, 'admin-stage-1.json'), JSON.stringify({ approvals: approvalRecords, handovers }, null, 2), 'utf8')
    record('stage-1-complete', { approvals: approvalRecords, handovers, artifactDir: ARTIFACT_DIR, resumedAfterApproval: true })
    console.log('\nAdmin browser context remains open. When root confirms both user returns are submitted, type: accept-returns')
    await waitForCommand('accept-returns', 'root confirms both user returns have been submitted')
    await page.getByRole('menuitem', { name: '设备交接' }).click()
    await page.waitForURL('**/handovers')
    const acceptedReturns = await acceptReturns(approvalRecords)
    await writeFile(path.join(ARTIFACT_DIR, 'admin-final.json'), JSON.stringify({ approvals: approvalRecords, handovers, acceptedReturns, pageErrors }, null, 2), 'utf8')
    await writeFile(path.join(ARTIFACT_DIR, 'browser-errors.json'), JSON.stringify(pageErrors, null, 2), 'utf8')
    await writeFile(path.join(ARTIFACT_DIR, 'journey-log.json'), JSON.stringify(log, null, 2), 'utf8')
    record('all-admin-work-complete', { approvals: approvalRecords.map(({ reservationId, deviceId }) => ({ reservationId, deviceId })), acceptedReturns, pageErrors, finalPath: new URL(page.url()).pathname })
    console.log('\nAll admin UI work is complete. Browser context remains open for final review. Type close-browser when root authorizes closing it.')
    await waitForCommand('close-browser', 'root finishes final review')
  } else if (process.argv.includes('--accept-returns-only')) {
    await enterApp()
    await page.getByRole('menuitem', { name: '设备交接' }).click()
    await page.waitForURL('**/handovers')
    const acceptedReturns = await acceptReturns(ALREADY_APPROVED_RESERVATIONS)
    await writeFile(path.join(ARTIFACT_DIR, 'admin-return-acceptance.json'), JSON.stringify({ acceptedReturns, pageErrors }, null, 2), 'utf8')
    await writeFile(path.join(ARTIFACT_DIR, 'browser-errors.json'), JSON.stringify(pageErrors, null, 2), 'utf8')
    await writeFile(path.join(ARTIFACT_DIR, 'journey-log.json'), JSON.stringify(log, null, 2), 'utf8')
    record('all-returns-accepted', { acceptedReturns, pageErrors, finalPath: new URL(page.url()).pathname })
    console.log('\nAll return acceptances are complete. Browser context remains open for final review. Type close-browser when root authorizes closing it.')
    await waitForCommand('close-browser', 'root finishes final review')
  } else {
    await enterApp()
    await verifyCollegeUiNoTransientGlobal()
    const approvals = await approveTwo()
    const handovers = await completeHandovers(approvals)
    await writeFile(path.join(ARTIFACT_DIR, 'admin-stage-1.json'), JSON.stringify({ approvals, handovers }, null, 2), 'utf8')
    record('stage-1-complete', { approvals, handovers, artifactDir: ARTIFACT_DIR })
    console.log('\nAdmin browser context remains open. When root confirms both user returns are submitted, type: accept-returns')
    await waitForCommand('accept-returns', 'root confirms both user returns have been submitted')

    await page.getByRole('menuitem', { name: '设备交接' }).click()
    await page.waitForURL('**/handovers')
    const acceptedReturns = await acceptReturns(approvals)
    await writeFile(path.join(ARTIFACT_DIR, 'admin-final.json'), JSON.stringify({ approvals, handovers, acceptedReturns, pageErrors }, null, 2), 'utf8')
    await writeFile(path.join(ARTIFACT_DIR, 'browser-errors.json'), JSON.stringify(pageErrors, null, 2), 'utf8')
    await writeFile(path.join(ARTIFACT_DIR, 'journey-log.json'), JSON.stringify(log, null, 2), 'utf8')
    record('all-admin-work-complete', { approvals: approvals.map(({ reservationId, deviceId }) => ({ reservationId, deviceId })), acceptedReturns, pageErrors, finalPath: new URL(page.url()).pathname })
    console.log('\nAll admin UI work is complete. Browser context remains open for final review. Type close-browser when root authorizes closing it.')
    await waitForCommand('close-browser', 'root finishes final review')
  }
} catch (error) {
  record('runner-failure', { message: error.message, stack: error.stack })
  const failureSuffix = new Date().toISOString().replaceAll(':', '-')
  await screenshot(`failure-current-page-${failureSuffix}.png`).catch(() => undefined)
  await writeFile(path.join(ARTIFACT_DIR, `failure-${failureSuffix}.json`), JSON.stringify({ message: error.message, stack: error.stack, pageErrors, log }, null, 2), 'utf8')
  console.error(error)
  console.log('\nBrowser remains open after a runner failure. Type close-browser after recording the page state.')
  await waitForCommand('close-browser').catch(() => undefined)
} finally {
  await context.close()
  await browser.close()
  await writeFile(path.join(ARTIFACT_DIR, 'browser-errors.json'), JSON.stringify(pageErrors, null, 2), 'utf8')
  await writeFile(path.join(ARTIFACT_DIR, 'journey-log.json'), JSON.stringify(log, null, 2), 'utf8')
}

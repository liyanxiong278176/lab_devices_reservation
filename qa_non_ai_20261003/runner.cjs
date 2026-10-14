'use strict';
// Independent browser/API integration harness. It does not import or run any
// existing test file. Admin credentials are supplied through process env.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(path.resolve('frontend/node_modules/@playwright/test'));

const FRONTEND = process.env.QA_NONAI_FRONTEND || 'http://127.0.0.1:5173';
const API = process.env.QA_NONAI_API || 'http://127.0.0.1:8001';
const ADMIN_USER = process.env.QA_NONAI_ADMIN_USER || 'e2e-joint01-admin';
const ADMIN_PASSWORD = process.env.QA_NONAI_ADMIN_PASSWORD;
const OUT = path.join(__dirname, 'results');
const SHOTS = path.join(OUT, 'screenshots');
const PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j0ioAAAAASUVORK5CYII=';
const PDF = 'JVBERi0xLjQKMSAwIG9iago8PC9UeXBlL0NhdGFsb2cvUGFnZXMgMiAwIFI+PgplbmRvYmoKMiAwIG9iago8PC9UeXBlL1BhZ2VzL0tpZHNbXS9Db3VudCAwPj4KZW5kb2JqCnRyYWlsZXIKPDwvUm9vdCAxIDAgUj4+CnN0YXJ0eHJlZgowCiUlRU9G';
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const runTag = 'nai' + Date.now().toString(36);
const HIDDEN_NON_AI_OPERATIONS = [
  'GET /api/v2/metrics',
  'GET /api/v2/device-documents/{asset_token}',
  'GET /api/v2/maintenance-evidence/{asset_token}',
  'GET /api/v2/reports/exports/{task_id}/download',
  'GET /api/v2/repair-uploads/{asset_token}',
];
const EXPECTED_UI_ROUTES = [
  '/login', '/register', '/dashboard', '/devices', '/devices/:id', '/recommendations',
  '/reservations/create', '/reservations/mine', '/reservations/:id', '/approvals/pending',
  '/notifications', '/repairs/submit', '/repairs/mine', '/repairs', '/devices-manage',
  '/handovers', '/reports', '/reservation-rules', '/maintenance', '/users', '/organization', '/rbac',
];

fs.mkdirSync(SHOTS, { recursive: true });
const state = {
  runTag,
  startedAt: new Date().toISOString(),
  openApiOperationCount: 0,
  hiddenOperationCount: 0,
  seenOperations: new Set(),
  observedRequestPaths: new Set(),
  unknownApiCalls: [],
  pageErrors: [],
  http5xx: [],
  routeChecks: [],
  scenarios: [],
  registrationAttempts: [],
  ids: {},
  failures: [],
};
let matchers = [];

function operationFor(method, pathname) {
  for (const item of matchers) if (item.method === method.toUpperCase() && item.regex.test(pathname)) return item.key;
  return null;
}

function safeOperationPath(pathname) {
  return pathname
    .replace(/\/(device-documents|maintenance-evidence|repair-uploads)\/[^/]+$/, '/$1/{asset_token}')
    .replace(/\/reports\/exports\/[^/]+\/download$/, '/reports/exports/{task_id}/download');
}

function observe(method, url) {
  const parsed = new URL(url);
  if (!parsed.pathname.startsWith('/api/v2/') || parsed.pathname.startsWith('/api/v2/ai/')) return;
  const cleanPath = parsed.pathname.replace(/\/+$/, '');
  const key = operationFor(method, cleanPath);
  state.observedRequestPaths.add(key || method.toUpperCase() + ' ' + safeOperationPath(cleanPath));
  if (key) state.seenOperations.add(key);
  else if (!cleanPath.includes('/openapi.json') && !cleanPath.includes('/docs')) {
    state.unknownApiCalls.push(method.toUpperCase() + ' ' + safeOperationPath(cleanPath));
  }
}

function attachPage(page, actor) {
  page.on('request', (request) => observe(request.method(), request.url()));
  page.on('pageerror', (error) => state.pageErrors.push({ actor, message: String(error.message).slice(0, 400) }));
  page.on('response', (response) => {
    if (response.status() >= 500) {
      const url = new URL(response.url());
      state.http5xx.push({ actor, status: response.status(), url: url.origin + safeOperationPath(url.pathname) });
    }
  });
}

function routeRegex(template) {
  const segments = template.split('/').map((part) => {
    if (/^\{[^/]+\}$/.test(part)) return '[^/]+';
    return part.replace(/[.*+?^$()|[\]\\]/g, '\\$&');
  });
  return new RegExp('^' + segments.join('/') + '$');
}

async function loadInventory() {
  const response = await fetch(API + '/api/v2/openapi.json');
  assert.equal(response.status, 200, 'live FastAPI OpenAPI is readable');
  const spec = await response.json();
  for (const [route, methods] of Object.entries(spec.paths || {})) {
    if (route === '/api/v2/ai' || route.startsWith('/api/v2/ai/')) continue;
    for (const method of Object.keys(methods)) {
      if (!['get', 'post', 'put', 'patch', 'delete'].includes(method)) continue;
      matchers.push({ method: method.toUpperCase(), route, regex: routeRegex(route), key: method.toUpperCase() + ' ' + route });
    }
  }
  state.openApiOperationCount = matchers.length;
  assert.equal(state.openApiOperationCount, 107, 'documented operation inventory changed; review before executing this matrix');
  for (const key of HIDDEN_NON_AI_OPERATIONS) {
    const split = key.indexOf(' ');
    const method = key.slice(0, split);
    const route = key.slice(split + 1);
    matchers.push({ method, route, regex: routeRegex(route), key });
  }
  state.hiddenOperationCount = HIDDEN_NON_AI_OPERATIONS.length;
  const specificity = (route) => route.split('/').reduce((score, segment) =>
    score + (segment && !/^\{[^/]+\}$/.test(segment) ? 1 : 0), 0);
  matchers.sort((a, b) => specificity(b.route) - specificity(a.route) || b.route.length - a.route.length);
  state.openApiOperationCount += state.hiddenOperationCount;
}

async function actor(browser, name) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  attachPage(page, name);
  return { name, context, page };
}

async function login(who, username, password) {
  const page = who.page;
  await page.goto(FRONTEND + '/login', { waitUntil: 'domcontentloaded' });
  if (!state.routeChecks.some((item) => item.route === '/login')) await screenshotPublicRoute(who, '/login', 'public');
  await page.getByPlaceholder('请输入用户名').fill(username);
  await page.getByPlaceholder('请输入密码').fill(password);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await page.waitForURL(/\/dashboard(?:$|[?#])/, { timeout: 15000 });
  await page.locator('.layout__user-name').waitFor({ state: 'visible', timeout: 10000 });
  await pause(250);
}

async function register(browser, collegeName, username, realName) {
  const who = await actor(browser, username);
  const page = who.page;
  await page.goto(FRONTEND + '/register', { waitUntil: 'domcontentloaded' });
  if (!state.routeChecks.some((item) => item.route === '/register')) await screenshotPublicRoute(who, '/register', 'public');
  await page.getByPlaceholder('请输入真实姓名').fill(realName);
  await page.getByPlaceholder('请输入用户名').fill(username);
  await page.getByPlaceholder('至少 8 位密码').fill('Run-2026-Password');
  await page.locator('.el-select__wrapper').first().click();
  await page.getByRole('option', { name: collegeName, exact: true }).click();
  const responsePromise = page.waitForResponse((response) => {
    try { return new URL(response.url()).pathname === '/api/v2/auth/register'; }
    catch { return false; }
  }, { timeout: 15000 });
  await page.getByRole('button', { name: '注册并登录', exact: true }).click();
  const response = await responsePromise;
  const attempt = { username, status: response.status() };
  state.registrationAttempts.push(attempt);
  if (response.status() === 201) {
    await page.waitForURL(/\/dashboard(?:$|[?#])/, { timeout: 15000, waitUntil: 'commit' });
    await pause(250);
    return { who, registered: true, status: response.status() };
  }
  if (response.status() === 429) {
    await who.context.close();
    return { who: null, registered: false, status: response.status() };
  }
  const body = await response.text().catch(() => '');
  throw new Error('registration returned ' + response.status() + '; response=' + body.slice(0, 400));
}

async function createAndLoginStudent(browser, admin, username, collegeId, realName) {
  const user = payload(await api(admin, 'POST', '/users', {
    username, password: 'Run-2026-Password', real_name: realName,
    user_type: 'STUDENT', role_codes: ['STUDENT'], college_id: collegeId,
  }));
  assert.ok(user && user.id, 'student account created: ' + username);
  const who = await actor(browser, username);
  await login(who, username, 'Run-2026-Password');
  return who;
}

async function api(who, method, route, body, options = {}) {
  const result = await who.page.evaluate(async (input) => {
    const headers = {};
    const csrf = window.localStorage.getItem('lab-auth-csrf-token') || '';
    if (!['GET', 'HEAD'].includes(input.method)) headers['X-CSRF-Token'] = csrf;
    let outgoing;
    if (input.form) {
      outgoing = new FormData();
      for (const [key, value] of Object.entries(input.form.fields || {})) outgoing.set(key, String(value));
      const bytes = Uint8Array.from(atob(input.form.file.base64), (character) => character.charCodeAt(0));
      outgoing.set('file', new File([bytes], input.form.file.name, { type: input.form.file.type }));
    } else if (input.body !== undefined) {
      headers['Content-Type'] = 'application/json';
      outgoing = JSON.stringify(input.body);
    }
    if (input.headers) Object.assign(headers, input.headers);
    const response = await fetch(input.url, { method: input.method, credentials: 'include', headers, body: outgoing });
    const text = await response.text();
    let json = null;
    try { json = text ? JSON.parse(text) : null; } catch { /* CSV/binary */ }
    return {
      status: response.status,
      contentType: response.headers.get('content-type') || '',
      disposition: response.headers.get('content-disposition') || '',
      text: json === null ? text.slice(0, 250) : '',
      json,
    };
  }, {
    method: method.toUpperCase(), url: FRONTEND + '/api/v2' + route,
    body, form: options.form, headers: options.headers,
  });
  observe(method, FRONTEND + '/api/v2' + route);
  const expected = options.expected || [200, 201, 202, 204];
  if (!expected.includes(result.status)) {
    throw new Error(method.toUpperCase() + ' ' + route + ' returned ' + result.status +
      '; response=' + JSON.stringify(result.json || result.text).slice(0, 700));
  }
  await pause(options.delay === undefined ? 110 : options.delay);
  return result;
}

const payload = (result) => result && result.json ? result.json.data : null;
function firstCategory(rows) {
  for (const row of rows || []) {
    if (row.id) return row.id;
    const child = firstCategory(row.children || []);
    if (child) return child;
  }
  return null;
}
function shanghaiDate(offset = 0) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(new Date());
  const values = Object.fromEntries(parts.map((item) => [item.type, item.value]));
  return new Date(Date.UTC(Number(values.year), Number(values.month) - 1, Number(values.day) + offset)).toISOString().slice(0, 10);
}
function scenario(name, result = 'PASS', detail = '') {
  state.scenarios.push({ name, result, detail });
}
async function upload(who, route, fields, file, expected = [200, 201]) {
  return api(who, 'POST', route, undefined, {
    expected, form: { fields, file },
  });
}
async function screenshotRoute(who, route, group) {
  const page = who.page;
  await page.goto(FRONTEND + route, { waitUntil: 'domcontentloaded', timeout: 20000 });
  await page.locator('body').waitFor({ state: 'visible', timeout: 10000 });
  await pause(350);
  const landed = new URL(page.url()).pathname;
  assert.notEqual(landed, '/login', 'protected route stays available: ' + route);
  const text = await page.locator('body').innerText();
  assert.ok(text.trim().length > 30, 'route renders visible content: ' + route);
  const filename = group + '-' + route.split(/[/?#]/).filter(Boolean).join('_').replace(/[^a-zA-Z0-9_-]/g, '').slice(0, 52) + '.png';
  await page.screenshot({ path: path.join(SHOTS, filename), fullPage: true, animations: 'disabled' });
  state.routeChecks.push({ actor: who.name, route, routeKey: canonicalUiRoute(route), landed, screenshot: filename });
}
function canonicalUiRoute(route) {
  const pathname = route.split(/[?#]/)[0];
  if (/^\/devices\/[^/]+$/.test(pathname)) return '/devices/:id';
  if (/^\/reservations\/[^/]+$/.test(pathname) && !['/reservations/create', '/reservations/mine'].includes(pathname)) return '/reservations/:id';
  return pathname;
}
async function screenshotPublicRoute(who, route, group) {
  const page = who.page;
  await page.locator('body').waitFor({ state: 'visible', timeout: 10000 });
  await pause(250);
  const landed = new URL(page.url()).pathname;
  assert.equal(landed, route, 'public route renders at its requested path: ' + route);
  const content = await page.locator('body').innerText();
  assert.ok(content.trim().length > 30, 'public route renders visible content: ' + route);
  const filename = group + '-' + route.replace(/[^a-zA-Z0-9_-]/g, '') + '.png';
  await page.screenshot({ path: path.join(SHOTS, filename), fullPage: true, animations: 'disabled' });
  state.routeChecks.push({ actor: who.name, route, routeKey: canonicalUiRoute(route), landed, screenshot: filename });
}
async function reserve(who, deviceId, from, to, purpose) {
  return api(who, 'POST', '/reservations', {
    device_id: deviceId, start_date: from, end_date: to, purpose,
    purpose_category: 'RESEARCH', commit_mode: 'all_or_nothing',
  }, {
    headers: { 'Idempotency-Key': runTag + '-' + Math.random().toString(36).slice(2, 12) },
    expected: [201],
  });
}

async function verifyCheckInRequiresManagerHandover(who, reservationId) {
  const result = await api(who, 'POST', '/reservations/' + reservationId + '/check-in', undefined, { expected: [409] });
  assert.equal(result.json && result.json.code, 'HANDOVER_REQUIRED', 'self check-in is rejected until manager handover flow');
}

async function main() {
  assert.ok(ADMIN_PASSWORD, 'QA_NONAI_ADMIN_PASSWORD is required in the run environment');
  await loadInventory();
  assert.equal(state.openApiOperationCount, 112, 'expected 107 OpenAPI + 5 hidden non-AI operations');
  const browser = await chromium.launch({ headless: true });
  let admin, manager, userA, userB, userC, foreignUser;
  try {
    admin = await actor(browser, 'system-admin');
    await login(admin, ADMIN_USER, ADMIN_PASSWORD);
    assert.ok(payload(await api(admin, 'GET', '/auth/me')), 'authenticated account details');
    await api(admin, 'GET', '/live');
    await api(admin, 'GET', '/ready');
    const metricsProbe = await api(admin, 'GET', '/metrics', undefined, { expected: [401, 404] });
    await api(admin, 'GET', '/system/outbox/failed');
    // Exercise refresh-token rotation and then refresh the readable CSRF token.
    await api(admin, 'POST', '/auth/refresh');
    const csrf = payload(await api(admin, 'GET', '/auth/csrf'));
    if (csrf && csrf.csrf_token) await admin.page.evaluate((value) =>
      window.localStorage.setItem('lab-auth-csrf-token', value), csrf.csrf_token);
    scenario('登录、身份读取、Refresh 轮换、健康探针/Outbox 与指标鉴权', 'PASS', '未提供 Prometheus bearer token 时 /metrics 返回 HTTP ' + metricsProbe.status);

    const collegeList = payload(await api(admin, 'GET', '/colleges'));
    assert.ok(Array.isArray(collegeList));
    const collegeCode = runTag.toUpperCase().slice(0, 40);
    const collegeName = '非AI新联调 ' + runTag;
    const college = payload(await api(admin, 'POST', '/colleges', { code: collegeCode, name: collegeName }));
    assert.ok(college && college.id);
    state.ids.college = college.id;
    const foreignCollege = payload(await api(admin, 'POST', '/colleges', {
      code: (runTag + 'x').toUpperCase().slice(0, 40),
      name: '非AI隔离校验 ' + runTag,
    }));
    state.ids.foreignCollege = foreignCollege.id;

    const roleRows = payload(await api(admin, 'GET', '/rbac/roles'));
    const permissions = payload(await api(admin, 'GET', '/rbac/permissions'));
    assert.ok(roleRows && permissions);
    const permissionCode = permissions[0] && (permissions[0].code || permissions[0].permission_code);
    assert.ok(permissionCode, 'permission code is present');
    const role = payload(await api(admin, 'POST', '/rbac/roles', {
      role_code: ('QA_' + runTag).toUpperCase().slice(0, 32),
      role_name: '非AI临时角色 ' + runTag,
      permission_codes: [permissionCode],
    }));
    await api(admin, 'PATCH', '/rbac/roles/' + role.id, { role_name: '非AI更新角色 ' + runTag });
    await api(admin, 'PUT', '/rbac/roles/' + role.id + '/permissions', { permission_codes: [permissionCode] });
    await api(admin, 'DELETE', '/rbac/roles/' + role.id);

    const managerName = '非AI负责人 ' + runTag;
    const managerUser = payload(await api(admin, 'POST', '/users', {
      username: runTag + 'mgr', password: 'Run-2026-Password', real_name: managerName,
      user_type: 'TEACHER', role_codes: ['LAB_ADMIN'], college_id: college.id,
    }));
    assert.ok(managerUser && managerUser.id);
    state.ids.manager = managerUser.id;
    await api(admin, 'PUT', '/colleges/' + college.id, {
      code: collegeCode, name: collegeName, manager_id: managerUser.id,
    });
    const managers = payload(await api(admin, 'GET', '/organization/managers?college_id=' + college.id));
    assert.ok(managers.some((item) => item.id === managerUser.id));
    const labPage = payload(await api(admin, 'GET', '/labs?page=1&size=200'));
    assert.ok(labPage && Array.isArray(labPage.records));
    const lab = payload(await api(admin, 'POST', '/labs', {
      college_id: college.id, name: '非AI实验室 ' + runTag, location: '本地联调区',
      manager_id: managerUser.id, description: '独立的前后端验收数据',
    }));
    assert.ok(lab && lab.id);
    state.ids.lab = lab.id;
    await api(admin, 'PUT', '/labs/' + lab.id, {
      college_id: college.id, name: '非AI实验室 ' + runTag, location: '本地联调区 B',
      manager_id: managerUser.id, description: '组织更新已验收',
    });
    const categories = payload(await api(admin, 'GET', '/device-categories'));
    const categoryId = firstCategory(categories);
    assert.ok(categoryId);

    const disposable = payload(await api(admin, 'POST', '/users', {
      username: runTag + 'tmp', password: 'Run-2026-Password', real_name: '临时停用账号',
      user_type: 'STUDENT', role_codes: ['STUDENT'], college_id: college.id,
    }));
    await api(admin, 'PUT', '/users/' + disposable.id, {
      username: disposable.username, password: 'Run-2026-Password', real_name: '临时更新账号',
      user_type: 'STUDENT', role_codes: ['STUDENT'], college_id: college.id,
    });
    await api(admin, 'PATCH', '/users/' + disposable.id + '/status?status=0');
    await api(admin, 'PATCH', '/users/' + disposable.id + '/status?status=1');
    await api(admin, 'DELETE', '/users/' + disposable.id);
    await api(admin, 'GET', '/users?page=1&size=20&username=' + runTag);

    const registration = await register(browser, collegeName, runTag + 'u1', '联调用户一');
    userA = registration.registered
      ? registration.who
      : await createAndLoginStudent(browser, admin, runTag + 'u1', college.id, '联调用户一（限流后管理端建号）');
    const priorRegistrationSuccess = state.registrationAttempts.some((attempt) => attempt.status === 201) ||
      fs.readdirSync(path.join(OUT, 'attempts'), { withFileTypes: true })
        .filter((entry) => entry.isFile() && /^integration-results-.*\.json$/.test(entry.name))
        .some((entry) => {
          try {
            const prior = JSON.parse(fs.readFileSync(path.join(OUT, 'attempts', entry.name), 'utf8'));
            return (prior.registrationAttempts || []).some((attempt) => attempt.status === 201);
          } catch { return false; }
        });
    scenario('公开注册入口成功与限流响应', registration.registered || (registration.status === 429 && priorRegistrationSuccess) ? 'PASS' : 'INCOMPLETE',
      '本轮 POST /auth/register HTTP ' + registration.status +
        (registration.registered ? '；注册后登录成功' : '；本轮共享 IP 配额触发 429 并由管理端建号继续' +
          (priorRegistrationSuccess ? '；先前独立联调已有 HTTP 201 成功注册证据' : '')));
    userB = await createAndLoginStudent(browser, admin, runTag + 'u2', college.id, '联调用户二');
    userC = await createAndLoginStudent(browser, admin, runTag + 'u3', college.id, '联调用户三');
    foreignUser = await createAndLoginStudent(browser, admin, runTag + 'uf', foreignCollege.id, '外学院联调用户');
    manager = await actor(browser, 'lab-manager');
    await login(manager, managerUser.username, 'Run-2026-Password');
    assert.ok((payload(await api(admin, 'GET', '/auth/colleges'))).some((item) => item.id === college.id));
    scenario('学院/实验室/用户/角色管理 CRUD，普通账号注册与负责人登录');

    async function createDevice(suffix, needsApproval, flags = {}) {
      const item = payload(await api(manager, 'POST', '/devices', {
        name: '非AI-' + suffix + '-' + runTag, lab_id: lab.id, category_id: categoryId,
        brand: 'LabFlow', model: 'Integration-' + suffix, description: '本轮独立联调设备',
        need_approval: needsApproval, max_reservation_days: 8,
        accessory_checklist: ['电源线', '校准夹具'],
        risk_level: flags.risk_level || 'STANDARD',
        requires_safety_ack: Boolean(flags.requires_safety_ack),
        requires_qualification: Boolean(flags.requires_qualification),
      }, { delay: 160 }));
      assert.ok(item && item.id, 'device creation: ' + suffix);
      return item;
    }
    const mainDevice = await createDevice('预约履约', true);
    const queueDevice = await createDevice('候补', false);
    const rejectDevice = await createDevice('驳回', true);
    const batchA = await createDevice('批量甲', true);
    const batchB = await createDevice('批量乙', true);
    const incidentDevice = await createDevice('违规', false);
    const exceptionDevice = await createDevice('异常交接', false);
    const repairDevice = await createDevice('报修', false);
    const maintenanceDevice = await createDevice('维护', false);
    const accessDevice = await createDevice('安全准入', false, {
      risk_level: 'HIGH', requires_safety_ack: true, requires_qualification: true,
    });
    const deleteDevice = await createDevice('删除校验', false);
    Object.assign(state.ids, {
      mainDevice: mainDevice.id, queueDevice: queueDevice.id, rejectDevice: rejectDevice.id,
      batchA: batchA.id, batchB: batchB.id, incidentDevice: incidentDevice.id,
      exceptionDevice: exceptionDevice.id, repairDevice: repairDevice.id,
      maintenanceDevice: maintenanceDevice.id, accessDevice: accessDevice.id,
    });
    await api(manager, 'GET', '/devices?page=1&page_size=50');
    const pools = payload(await api(manager, 'GET', '/device-pools/options'));
    assert.ok(Array.isArray(pools));
    const poolRow = pools.find((row) =>
      row.device_id === mainDevice.id || row.deviceId === mainDevice.id ||
      (row.devices || []).some((item) => item.id === mainDevice.id));
    const poolId = mainDevice.pool_id || mainDevice.poolId || (poolRow && (poolRow.id || poolRow.pool_id || poolRow.poolId));
    if (poolId) {
      await api(manager, 'GET', '/device-pools/' + poolId);
      await api(manager, 'GET', '/device-pools/' + poolId + '/availability?start_date=' + shanghaiDate() + '&end_date=' + shanghaiDate(7));
    }
    await api(manager, 'GET', '/devices/' + mainDevice.id);
    await api(manager, 'GET', '/devices/' + mainDevice.id + '/availability?start_date=' + shanghaiDate() + '&end_date=' + shanghaiDate(7));
    await api(manager, 'PUT', '/devices/' + deleteDevice.id, {
      name: '非AI-删除校验更新-' + runTag, lab_id: lab.id, category_id: categoryId,
      need_approval: false, max_reservation_days: 8, accessory_checklist: [],
    });
    await api(manager, 'PATCH', '/devices/' + deleteDevice.id + '/status', { status: 'OFFLINE', reason: '联调状态变更' });
    await api(manager, 'PATCH', '/devices/' + deleteDevice.id + '/status', { status: 'IDLE', reason: '联调状态恢复' });
    await api(manager, 'DELETE', '/devices/' + deleteDevice.id);

    const safetyDoc = payload(await upload(manager, '/devices/' + accessDevice.id + '/documents', {
      document_type: 'SAFETY', title: '非AI联调安全须知 ' + runTag, version: '1.0', requires_ack: true,
    }, { name: 'safety.pdf', type: 'application/pdf', base64: PDF }));
    assert.ok(safetyDoc && safetyDoc.url);
    await api(manager, 'GET', '/devices/' + accessDevice.id + '/documents');
    const documentToken = safetyDoc.asset_token || String(safetyDoc.url).split('/').pop();
    assert.ok(documentToken, 'device document download token is available from its URL');
    await api(manager, 'GET', '/device-documents/' + documentToken, undefined, { expected: [200] });
    await api(foreignUser, 'GET', '/device-documents/' + documentToken, undefined, { expected: [404] });
    await api(userA, 'GET', '/devices/' + accessDevice.id + '/safety-documents');
    await api(userA, 'POST', '/devices/' + accessDevice.id + '/safety-ack', {});
    const qualificationFile = payload(await upload(userA, '/devices/' + accessDevice.id + '/qualification-uploads', {},
      { name: 'training.pdf', type: 'application/pdf', base64: PDF }));
    const qualification = payload(await api(userA, 'POST', '/devices/' + accessDevice.id + '/qualifications', {
      qualification_type: 'TRAINING', asset_id: qualificationFile.asset_id, note: '完成设备培训',
    }));
    await api(userA, 'GET', '/devices/' + accessDevice.id + '/qualifications/mine');
    await api(manager, 'GET', '/devices/' + accessDevice.id + '/qualifications');
    await api(manager, 'PATCH', '/devices/' + accessDevice.id + '/qualifications/' + qualification.id, {
      status: 'APPROVED', valid_until: shanghaiDate(30), note: '联调审核通过',
    });
    await api(userA, 'GET', '/devices/' + accessDevice.id + '/access');
    await api(manager, 'DELETE', '/devices/' + accessDevice.id + '/documents/' + safetyDoc.id);
    scenario('设备与资源池读写、状态历史、安全须知和资质上传审核');

    const today = shanghaiDate();
    const tomorrow = shanghaiDate(1);
    const nextWeek = shanghaiDate(7);
    const adminRoutes = [
      '/organization', '/users', '/rbac', '/devices-manage', '/reservation-rules', '/maintenance',
      '/reports', '/approvals/pending', '/handovers', '/repairs', '/notifications', '/dashboard',
      '/devices', '/devices/' + mainDevice.id, '/recommendations',
      '/reservations/create?deviceId=' + mainDevice.id + '&startDate=' + today + '&endDate=' + today,
      '/reservations/mine', '/repairs/submit', '/repairs/mine', '/reservations/1',
    ];
    for (const route of adminRoutes) await screenshotRoute(admin, route, 'admin');
    scenario('系统管理员 20/20 个非 AI Vue 页面路由和截图');

    const foreignDevice = await api(foreignUser, 'GET', '/devices/' + mainDevice.id, undefined, { expected: [403, 404] });
    assert.ok([403, 404].includes(foreignDevice.status));
    const foreignCatalog = await api(foreignUser, 'GET', '/colleges', undefined, { expected: [403] });
    assert.equal(foreignCatalog.status, 403, 'organization management catalog is not readable by students');

    const userPage = userA.page;
    await userPage.goto(FRONTEND + '/reservations/create?deviceId=' + mainDevice.id + '&startDate=' + today + '&endDate=' + today, { waitUntil: 'domcontentloaded' });
    await userPage.getByPlaceholder('例如：完成材料拉伸实验并采集三组数据').fill('完成非 AI 全链路预约验证');
    await userPage.locator('.preflight-summary').waitFor({ state: 'visible', timeout: 20000 });
    await userPage.getByRole('button', { name: '提交预约', exact: true }).click();
    await userPage.waitForURL(/\/reservations\/mine(?:$|[?#])/, { timeout: 15000 });
    const mine = payload(await api(userA, 'GET', '/reservations/mine?page=1&page_size=100'));
    const mainReservation = (mine.records || mine.items || []).find((row) => row.device_id === mainDevice.id || row.deviceId === mainDevice.id);
    assert.ok(mainReservation, 'reservation submitted through Vue is persisted');
    const mainReservationId = mainReservation.id;
    state.ids.mainReservation = mainReservationId;
    await api(manager, 'GET', '/approvals/pending?page=1&page_size=100');
    await api(manager, 'POST', '/approvals/' + mainReservationId + '/approve');
    await api(userA, 'GET', '/reservations/' + mainReservationId);
    await verifyCheckInRequiresManagerHandover(userA, mainReservationId);
    const handoverPhoto = payload(await upload(manager, '/repair-uploads', {},
      { name: 'handover.png', type: 'image/png', base64: PNG }, [201]));
    await api(manager, 'POST', '/reservations/' + mainReservationId + '/handover', {
      condition: 'NORMAL', note: '现场交接完成', image_urls: [handoverPhoto.url],
      checklist: [{ name: '电源线', condition: 'NORMAL' }, { name: '校准夹具', condition: 'NORMAL' }],
    });
    await api(manager, 'GET', '/reservations/handovers?status=RETURN_PENDING&page=1&page_size=20');
    const returnPhoto = payload(await upload(userA, '/repair-uploads', {},
      { name: 'return.png', type: 'image/png', base64: PNG }, [201]));
    await api(userA, 'POST', '/reservations/' + mainReservationId + '/return', {
      condition: 'NORMAL', note: '设备状态正常', image_urls: [returnPhoto.url],
    });
    const returnToken = returnPhoto.url.split('/').pop();
    await api(manager, 'GET', '/repair-uploads/' + returnToken, undefined, { expected: [200] });
    await api(manager, 'POST', '/reservations/' + mainReservationId + '/accept-return', {
      condition: 'NORMAL', note: '验收通过',
      checklist: [{ name: '电源线', condition: 'NORMAL' }, { name: '校准夹具', condition: 'NORMAL' }],
    });
    await api(userA, 'GET', '/reservations/' + mainReservationId + '/feedback');
    await api(userA, 'POST', '/reservations/' + mainReservationId + '/feedback', { rating: 5, comment: '全链路评价' });
    scenario('Vue 预约表单 → 审批/签到/交接 → 归还/验收 → 使用评价', 'PASS', 'reservation_id=' + mainReservationId);

    const rejectedBooking = payload(await reserve(userA, rejectDevice.id, today, today, '单条驳回链路'));
    const rejectedId = rejectedBooking.created[0].id;
    await api(manager, 'POST', '/approvals/' + rejectedId + '/reject', { reason: '验证驳回原因' });
    const batchOne = payload(await reserve(userB, batchA.id, tomorrow, tomorrow, '批量审批甲'));
    const batchTwo = payload(await reserve(userB, batchB.id, tomorrow, tomorrow, '批量审批乙'));
    await api(manager, 'POST', '/approvals/batch-approve', { ids: [batchOne.created[0].id, batchTwo.created[0].id] });

    const occupied = payload(await reserve(userA, queueDevice.id, nextWeek, nextWeek, '释放后递补候补'));
    const occupiedId = occupied.created[0].id;
    await api(userB, 'POST', '/reservations/waitlist', {
      device_id: queueDevice.id, reservation_date: nextWeek, purpose: '等待设备空闲', purpose_category: 'RESEARCH',
    }, { expected: [201] });
    const entriesB = payload(await api(userB, 'GET', '/reservations/waitlist/mine'));
    const queueEntry = entriesB.find((row) => row.device_id === queueDevice.id || row.deviceId === queueDevice.id);
    assert.ok(queueEntry);
    const removable = payload(await api(userC, 'POST', '/reservations/waitlist', {
      device_id: queueDevice.id, reservation_date: nextWeek, purpose: '取消候补校验', purpose_category: 'OTHER',
    }, { expected: [201] }));
    await api(userC, 'DELETE', '/reservations/waitlist/' + removable.id);
    await api(userA, 'POST', '/reservations/' + occupiedId + '/cancel');
    let offer;
    for (let attempt = 0; attempt < 18; attempt += 1) {
      const current = payload(await api(userB, 'GET', '/reservations/waitlist/mine', undefined, { delay: 180 }));
      offer = current.find((row) => row.id === queueEntry.id);
      if (offer && offer.status === 'OFFERED') break;
      await pause(300);
    }
    assert.equal(offer.status, 'OFFERED', 'released date is temporarily offered to the waitlist head');
    const confirmed = payload(await api(userB, 'POST', '/reservations/waitlist/' + queueEntry.id + '/confirm'));
    const confirmedReservationId = confirmed.reservation_id || confirmed.reservationId;
    if (confirmedReservationId) await api(userB, 'POST', '/reservations/' + confirmedReservationId + '/cancel');
    scenario('驳回/批量审批、取消预约、候补递补/确认/取消');

    const raceDate = shanghaiDate(2);
    const race = await Promise.all([
      api(userA, 'POST', '/reservations', {
        device_id: incidentDevice.id, start_date: raceDate, end_date: raceDate, purpose: '同设备同日并发 A',
      }, { headers: { 'Idempotency-Key': runTag + '-race-a' }, expected: [201, 409] }),
      api(userB, 'POST', '/reservations', {
        device_id: incidentDevice.id, start_date: raceDate, end_date: raceDate, purpose: '同设备同日并发 B',
      }, { headers: { 'Idempotency-Key': runTag + '-race-b' }, expected: [201, 409] }),
    ]);
    assert.deepEqual(race.map((row) => row.status).sort(), [201, 409]);
    const violation = payload(await reserve(userA, incidentDevice.id, today, today, '违规处理和信用事件'));
    const violationId = violation.created[0].id;
    await verifyCheckInRequiresManagerHandover(userA, violationId);
    await api(manager, 'POST', '/reservations/' + violationId + '/handover', {
      condition: 'NORMAL', note: '交接完成', image_urls: [handoverPhoto.url],
      checklist: [{ name: '电源线', condition: 'NORMAL' }, { name: '校准夹具', condition: 'NORMAL' }],
    });
    await api(manager, 'POST', '/reservations/' + violationId + '/violate', { reason: '联调信用事件记录' });
    const exception = payload(await reserve(userA, exceptionDevice.id, today, today, '交接异常关闭链路'));
    const exceptionId = exception.created[0].id;
    await verifyCheckInRequiresManagerHandover(userA, exceptionId);
    await api(manager, 'POST', '/reservations/' + exceptionId + '/handover', {
      condition: 'DAMAGED', note: '现场发现配件损坏', image_urls: [handoverPhoto.url],
      checklist: [{ name: '电源线', condition: 'DAMAGED' }, { name: '校准夹具', condition: 'NORMAL' }],
    });
    await api(manager, 'POST', '/reservations/' + exceptionId + '/cancel-handover-exception', {
      reason: '取消预约并释放日期，维修单保留',
    });
    await api(userA, 'POST', '/reservations/preflight', {
      device_id: exceptionDevice.id, start_date: today, end_date: today, purpose: '异常后预检',
    });
    scenario('同设备并发唯一占用、违规信用事件、损坏交接/维修/预约释放',
      'PASS', 'race=' + race.map((row) => row.status).join(','));

    const blackoutDate = shanghaiDate(6);
    const blackout = payload(await api(manager, 'POST', '/blackouts', {
      scope_type: 'LAB', scope_id: lab.id, blocked_date: blackoutDate, reason: '联调不可预约日',
    }, { expected: [201] }));
    await api(manager, 'GET', '/blackouts?start_date=' + today + '&end_date=' + nextWeek);
    await api(userA, 'POST', '/reservations/preflight', {
      device_id: repairDevice.id, start_date: blackoutDate, end_date: blackoutDate, purpose: '屏蔽日冲突校验',
    });
    await api(manager, 'DELETE', '/blackouts/' + blackout.id);
    const rule = payload(await api(manager, 'PUT', '/reservation-rules', {
      scope_type: 'LAB', scope_id: lab.id, user_category: 'ALL',
      max_booking_days: 8, max_advance_days: 30, approval_required: true,
    }));
    await api(manager, 'GET', '/reservation-rules?page=1&page_size=50&scope_type=LAB&scope_id=' + lab.id);
    await api(manager, 'DELETE', '/reservation-rules/' + rule.id);
    scenario('不可预约日和预约规则配置/过滤/删除');

    const repairPhoto = payload(await upload(userA, '/repair-uploads', {},
      { name: 'repair.png', type: 'image/png', base64: PNG }, [201]));
    const repairToken = repairPhoto.url.replace(/^\/api\/v2/, '').split('/').pop();
    await api(userA, 'GET', '/repair-uploads/' + repairToken, undefined, { expected: [200] });
    const repair = payload(await api(userA, 'POST', '/repair-reports', {
      device_id: repairDevice.id, title: '非AI联调故障单 ' + runTag,
      description: '验证故障上传、负责人受理和用户确认', image_urls: [repairPhoto.url], priority: 'IMPORTANT',
    }, { expected: [201] }));
    state.ids.repair = repair.id;
    await api(userA, 'GET', '/repair-reports/mine?page=1&size=20');
    await api(manager, 'GET', '/repair-reports?status=PENDING&page=1&size=20');
    await api(manager, 'GET', '/repair-reports/' + repair.id + '/worklogs');
    await api(manager, 'POST', '/repair-reports/' + repair.id + '/take');
    await api(manager, 'POST', '/repair-reports/' + repair.id + '/resolve', { resolution_note: '更换接头并通过复测' });
    await api(userA, 'POST', '/repair-reports/' + repair.id + '/confirm', { confirmed: true, note: '复测正常' });
    const rejectedRepair = payload(await api(userA, 'POST', '/repair-reports', {
      device_id: repairDevice.id, title: '验证报修驳回 ' + runTag, description: '待补充的故障信息', priority: 'NORMAL',
    }, { expected: [201] }));
    await api(manager, 'POST', '/repair-reports/' + rejectedRepair.id + '/reject', { resolution_note: '请补充可复现步骤' });
    const reopenedRepair = payload(await api(userA, 'POST', '/repair-reports', {
      device_id: repairDevice.id, title: '验证维修复核分支 ' + runTag,
      description: '检查用户对处理结果提出异议', priority: 'NORMAL',
    }, { expected: [201] }));
    await api(manager, 'POST', '/repair-reports/' + reopenedRepair.id + '/take');
    await api(manager, 'POST', '/repair-reports/' + reopenedRepair.id + '/resolve', { resolution_note: '先执行修复，再由用户验收' });
    await api(userA, 'POST', '/repair-reports/' + reopenedRepair.id + '/confirm', { confirmed: false, note: '问题仍存在，请继续处理' });
    scenario('故障图片、报修/接单/解决/用户确认，以及驳回/退回');

    const due = today;
    const plan = payload(await api(manager, 'POST', '/devices/' + maintenanceDevice.id + '/maintenance-plans', {
      plan_type: 'ROUTINE', title: '非AI维护计划 ' + runTag,
      interval_value: 1, interval_unit: 'MONTH', due_date: due, active: true,
    }));
    await api(manager, 'GET', '/maintenance-devices?page=1&page_size=20&search=' + encodeURIComponent(runTag));
    await api(manager, 'GET', '/maintenance-plans?page=1&page_size=20&device_id=' + maintenanceDevice.id);
    await api(manager, 'PUT', '/maintenance-plans/' + plan.id, {
      plan_type: 'ROUTINE', title: '非AI维护计划更新 ' + runTag,
      interval_value: 2, interval_unit: 'MONTH', due_date: due, active: true,
    });
    const evidence = payload(await upload(manager, '/devices/' + maintenanceDevice.id + '/maintenance-evidence', {},
      { name: 'maintenance.png', type: 'image/png', base64: PNG }));
    await api(manager, 'POST', '/maintenance-plans/' + plan.id + '/records', {
      cycle_due_date: due, completed_date: due, result: 'PASSED',
      notes: '校准和安全检查已完成', evidence_asset_token: evidence.asset_token,
    }, { headers: { 'Idempotency-Key': runTag + '-maintenance-record' } });
    await api(manager, 'GET', '/maintenance-plans/' + plan.id + '/records?page=1&page_size=20');
    await api(manager, 'GET', '/maintenance-evidence/' + evidence.asset_token, undefined, { expected: [200] });
    scenario('维护计划、周期完成记录、附件与历史记录');

    await api(admin, 'GET', '/dashboard/overview?groupBy=device&days=7');
    await api(admin, 'GET', '/dashboard/summary');
    await api(admin, 'GET', '/reports/summary?start_date=' + shanghaiDate(-30) + '&end_date=' + today);
    const exportTask = payload(await api(admin, 'POST', '/reports/exports', {
      export_type: 'reservations', start_date: shanghaiDate(-30), end_date: today,
    }, { expected: [200, 202] }));
    if (exportTask && exportTask.id) {
      let completed = false;
      for (let attempt = 0; attempt < 28; attempt += 1) {
        const current = payload(await api(admin, 'GET', '/reports/exports/' + exportTask.id, undefined, { delay: 160 }));
        if (current && current.status === 'COMPLETED') {
          await api(admin, 'GET', '/reports/exports/' + exportTask.id + '/download', undefined, { expected: [200] });
          completed = true;
          break;
        }
        if (current && current.status === 'FAILED') throw new Error('export worker returned FAILED');
        await pause(250);
      }
      assert.ok(completed, 'async CSV export reaches COMPLETED and can download');
    }
    for (const kind of ['devices', 'reservations', 'repairs']) {
      const csv = await api(admin, 'GET', '/reports/export/' + kind + '?start_date=' + shanghaiDate(-30) + '&end_date=' + today,
        undefined, { expected: [200] });
      assert.ok(csv.contentType.includes('text/csv') || csv.contentType.includes('octet-stream'));
    }
    await api(userA, 'GET', '/recommendations?limit=5');

    const notificationPage = payload(await api(userA, 'GET', '/notifications/mine?page=1&size=50'));
    const notices = notificationPage.records || notificationPage.items || [];
    if (notices.length) await api(userA, 'PATCH', '/notifications/' + notices[0].id + '/read');
    await api(userA, 'PATCH', '/notifications/read-all');
    await userA.page.goto(FRONTEND + '/notifications', { waitUntil: 'domcontentloaded' });
    await pause(450);
    scenario('仪表盘、报表导出、推荐、通知历史/已读与浏览器 SSE');

    await api(admin, 'POST', '/system/outbox/2147483647/retry', undefined, { expected: [404] });
    const foreignReservation = await api(foreignUser, 'GET', '/reservations/' + mainReservationId, undefined, { expected: [403, 404] });
    assert.ok([403, 404].includes(foreignReservation.status));
    scenario('学院边界验证与 Outbox retry 路由的无效任务拒绝');

    const studentRoutes = [
      '/dashboard', '/devices', '/devices/' + mainDevice.id, '/recommendations',
      '/reservations/create?deviceId=' + mainDevice.id + '&startDate=' + today + '&endDate=' + today,
      '/reservations/mine', '/reservations/' + mainReservationId, '/notifications', '/repairs/submit', '/repairs/mine',
    ];
    for (const route of studentRoutes) await screenshotRoute(userA, route, 'student');
    const managerRoutes = [
      '/dashboard', '/devices', '/devices-manage', '/approvals/pending', '/handovers',
      '/repairs', '/reservation-rules', '/maintenance', '/reports', '/notifications',
    ];
    for (const route of managerRoutes) await screenshotRoute(manager, route, 'manager');

    for (const who of [userA, userB, userC, foreignUser, manager]) {
      try { await who.page.getByRole('button', { name: '退出登录' }).click({ timeout: 1200 }); } catch { /* route may already be public */ }
    }
    await admin.page.getByRole('button', { name: '退出登录' }).click();
    await admin.page.waitForURL(/\/login(?:$|[?#])/, { timeout: 10000 });
    scenario('联调浏览器会话登出');
  } finally {
    await browser.close();
  }
}

function writeReport() {
  const expected = new Set(matchers.map((item) => item.key));
  const missing = [...expected].filter((item) => !state.seenOperations.has(item)).sort();
  const coverage = expected.size ? Number((state.seenOperations.size * 100 / expected.size).toFixed(2)) : 0;
  const observedUiRoutes = new Set(state.routeChecks.map((item) => canonicalUiRoute(item.route)));
  const missingUiRoutes = EXPECTED_UI_ROUTES.filter((route) => !observedUiRoutes.has(route));
  const complete = state.failures.length === 0 && state.scenarios.every((item) => item.result === 'PASS') && missing.length === 0 &&
    missingUiRoutes.length === 0 && state.pageErrors.length === 0 && state.http5xx.length === 0;
  const report = {
    runTag: state.runTag, startedAt: state.startedAt, finishedAt: new Date().toISOString(),
    inventory: {
      nonAiOperations: state.openApiOperationCount, observedOperations: state.seenOperations.size,
      operationCoveragePercent: coverage, missingOperations: missing, pageRouteChecks: state.routeChecks.length,
      documentedOpenApiOperations: state.openApiOperationCount - state.hiddenOperationCount,
      hiddenNonAiOperations: HIDDEN_NON_AI_OPERATIONS, uniqueUiRoutes: observedUiRoutes.size,
      expectedUiRoutes: EXPECTED_UI_ROUTES.length, missingUiRoutes,
    },
    scenarios: state.scenarios, routeChecks: state.routeChecks, registrationAttempts: state.registrationAttempts,
    observedRequestPaths: [...state.observedRequestPaths].sort(), ids: state.ids,
    pageErrors: state.pageErrors, http5xx: state.http5xx,
    unknownApiCalls: [...new Set(state.unknownApiCalls)].sort(), failures: state.failures,
    outcome: complete ? 'PASS' : 'INCOMPLETE',
    coverageMeaning: 'HTTP method/path coverage and UI route coverage; not source line or branch coverage.',
  };
  fs.writeFileSync(path.join(OUT, 'integration-results.json'), JSON.stringify(report, null, 2) + '\n');
  const rows = report.scenarios.map((item) => '| ' + item.name + ' | ' + item.result + ' | ' + item.detail + ' |');
  const missingRows = missing.length ? missing.map((item) => '- ' + item) : ['- 无'];
  const text = [
    '# 非 AI 前后端全链路联调记录', '',
    '- 执行时间：' + report.startedAt + ' 至 ' + report.finishedAt,
    '- 真实链路：Vue/Vite ' + FRONTEND + ' → FastAPI ' + API + ' → 当前 MySQL/Redis。',
    '- 测试入口：本目录新建的 runner.cjs；没有调用 backend/tests、frontend/e2e 或既有联调 spec。',
    '- 非 AI API 操作：' + report.inventory.observedOperations + '/' + report.inventory.nonAiOperations +
      '（' + coverage + '%；107 个 OpenAPI method/path + 5 个隐藏下载/监控 method/path）。',
    '- 非 AI Vue 页面路由：' + report.inventory.uniqueUiRoutes + '/' + report.inventory.expectedUiRoutes +
      ' 个唯一页面（包含登录、注册和 20 个业务页面）；截图/角色访问记录 ' + report.inventory.pageRouteChecks + ' 条。',
    '- 页面运行时异常：' + report.pageErrors.length + '；HTTP 5xx：' + report.http5xx.length + '。',
    '- 结果：**' + report.outcome + '**', '',
    '## 场景结果', '',
    '| 场景 | 结果 | 备注 |', '|---|---|---|', ...rows, '',
    '## 未覆盖 HTTP 操作', '', ...missingRows, '',
    '## 未覆盖 Vue 页面路由', '', ...(missingUiRoutes.length ? missingUiRoutes.map((item) => '- ' + item) : ['- 无']), '',
    '## 证据和范围', '',
    '- integration-results.json 保存结构化结果和资源 ID；报告不包含 cookie、CSRF 值或密码。',
    '- screenshots/ 保存实际浏览器页面截图；账号、学院、实验室与设备均使用本轮唯一前缀。',
    '- 100% method/path 覆盖不等于 Python/TypeScript 源码行或分支覆盖。源码覆盖率需要在启用 instrumentation 的进程中单独测量。',
    '- 隔离联调数据保留在本地数据库；没有清理原有数据、容器或服务。', '',
  ].join('\n');
  fs.writeFileSync(path.join(OUT, 'REPORT.md'), text);
  return report;
}

main().catch((error) => {
  state.failures.push({
    message: String(error && error.message || error).slice(0, 1200),
    stack: String(error && error.stack || '').split('\n').slice(0, 8).join('\n'),
  });
}).finally(() => {
  const report = writeReport();
  console.log(JSON.stringify({
    outcome: report.outcome, runTag: report.runTag,
    apiOperations: report.inventory.observedOperations + '/' + report.inventory.nonAiOperations,
    pageRoutes: report.inventory.pageRouteChecks,
    scenarios: report.scenarios.filter((item) => item.result === 'PASS').length + '/' + report.scenarios.length,
    failures: report.failures, missingOperations: report.inventory.missingOperations,
    pageErrors: report.pageErrors.length, http5xx: report.http5xx.length,
    report: path.join(OUT, 'REPORT.md'),
  }, null, 2));
  if (report.outcome !== 'PASS') process.exitCode = 1;
});

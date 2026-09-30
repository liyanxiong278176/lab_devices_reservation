import http from 'k6/http'
import { check, sleep } from 'k6'
import { Counter, Rate } from 'k6/metrics'

const api = (__ENV.K6_BASE_URL || 'http://host.docker.internal:18000/api/v2').replace(/\/$/, '')
const origin = __ENV.K6_ORIGIN || 'http://127.0.0.1:5173'
const username = __ENV.K6_USERNAME
const password = __ENV.K6_PASSWORD
const profile = __ENV.PROFILE || 'smoke'
const authFailures = new Rate('auth_failures')
const unexpectedResponses = new Rate('unexpected_api_responses')
const shedResponses = new Counter('bounded_503_responses')
const successfulReads = new Counter('successful_reads')
const readStatuses = new Counter('read_http_status')
const recoveryFailures = new Rate('post_load_recovery_failures')

const profiles = {
  smoke: [{ duration: '5s', target: 1 }],
  average: [
    { duration: '15s', target: 5 },
    { duration: '30s', target: 10 },
    { duration: '60s', target: 10 },
    { duration: '15s', target: 0 },
  ],
  stress: [
    { duration: '15s', target: 10 },
    { duration: '30s', target: 25 },
    { duration: '30s', target: 50 },
    { duration: '60s', target: 50 },
    { duration: '15s', target: 0 },
  ],
  spike: [
    { duration: '15s', target: 10 },
    { duration: '5s', target: 100 },
    { duration: '20s', target: 100 },
    { duration: '5s', target: 10 },
    { duration: '30s', target: 10 },
    { duration: '10s', target: 0 },
  ],
  breakpoint: [
    { duration: '15s', target: 10 },
    { duration: '30s', target: 20 },
    { duration: '30s', target: 40 },
    { duration: '30s', target: 80 },
    { duration: '30s', target: 120 },
    { duration: '15s', target: 0 },
  ],
  soak: [
    { duration: '15s', target: 10 },
    { duration: '10m', target: 10 },
    { duration: '15s', target: 0 },
  ],
}

if (!profiles[profile]) throw new Error(`Unsupported PROFILE: ${profile}`)

export const options = {
  discardResponseBodies: false,
  scenarios: {
    mixed_read_workload: {
      executor: 'ramping-vus',
      startVUs: profile === 'smoke' ? 1 : 0,
      stages: profiles[profile],
      gracefulRampDown: '10s',
    },
  },
  thresholds: {
    auth_failures: ['rate<0.001'],
    unexpected_api_responses: ['rate<0.001'],
    post_load_recovery_failures: ['rate<0.001'],
  },
}

function authenticate() {
  if (!username || !password) {
    authFailures.add(1)
    return false
  }

  const csrf = http.get(`${api}/auth/csrf`, { tags: { phase: 'auth' } })
  if (csrf.status !== 200) {
    authFailures.add(1)
    return false
  }

  const csrfToken = csrf.json('data.csrf_token')
  const response = http.post(
    `${api}/auth/login`,
    JSON.stringify({ username, password }),
    {
      headers: {
        Origin: origin,
        'Content-Type': 'application/json',
        'X-CSRF-Token': csrfToken,
      },
      tags: { phase: 'auth' },
    },
  )
  const ok = response.status === 200
  authFailures.add(ok ? 0 : 1)
  if (ok) {
    __VU_COOKIE_HEADER = cookieHeader(`${api}/devices`)
    const probe = http.get(`${api}/auth/me`, {
      headers: { Cookie: __VU_COOKIE_HEADER },
      tags: { phase: 'auth-probe' },
    })
    if (typeof __ITER !== 'undefined' && __ITER === 0) {
      console.log(`Authenticated session probe: HTTP ${probe.status}`)
    }
  }
  return ok
}

function cookieHeader(url) {
  const cookies = http.cookieJar().cookiesForURL(url)
  return Object.entries(cookies)
    .flatMap(([name, values]) => (Array.isArray(values) ? values : [values]).map((value) => `${name}=${value}`))
    .join('; ')
}

const reads = [
  '/devices?page=1&page_size=20',
  '/devices?page=2&page_size=20',
  '/reservations/mine?page=1&page_size=20',
  '/reservations/mine?page=450&page_size=20',
  '/dashboard/me',
]

export function setup() {
  const live = http.get(`${api}/live`, { tags: { phase: 'setup' } })
  if (!check(live, { 'API liveness endpoint is healthy': (response) => response.status === 200 })) {
    throw new Error(`API liveness failed with HTTP ${live.status}`)
  }
  return { profile }
}

export default function () {
  if (__VU_AUTHENTICATED !== true) {
    if (!authenticate()) return
    __VU_AUTHENTICATED = true
  }

  const path = reads[Math.floor(Math.random() * reads.length)]
  const response = http.get(`${api}${path}`, {
    headers: { Cookie: __VU_COOKIE_HEADER },
    tags: { phase: 'read', profile },
    timeout: '20s',
  })
  readStatuses.add(1, { status: String(response.status), path: path.split('?')[0] })
  if (response.status === 200) successfulReads.add(1)
  if (response.status === 503) shedResponses.add(1)
  const expected = response.status === 200 || response.status === 503
  unexpectedResponses.add(expected ? 0 : 1)
  if (!expected && __ITER < 3) {
    console.log(`Unexpected read response: status=${response.status} path=${path} body=${String(response.body).slice(0, 240)}`)
  }
  check(response, { 'read returns success or bounded overload': () => expected })
  sleep(0.1 + Math.random() * 0.3)
}

let __VU_AUTHENTICATED = false
let __VU_COOKIE_HEADER = ''

export function teardown(data) {
  const authenticated = authenticate()
  if (!authenticated) {
    recoveryFailures.add(1)
    return
  }
  const response = http.get(`${api}/devices?page=1&page_size=20`, {
    headers: { Cookie: __VU_COOKIE_HEADER },
    tags: { phase: 'recovery', profile: data.profile },
    timeout: '20s',
  })
  recoveryFailures.add(response.status === 200 ? 0 : 1)
  check(response, { 'service recovers after profile': (result) => result.status === 200 })
}

/**
 * Local-only fault injector for the browser SSE test. It proxies requests to the
 * QA backend and can reset only active EventSource sockets while HTTP continues.
 * Bind to loopback; do not expose this helper to a shared or production network.
 */
import http from 'node:http'

const upstreamPort = Number(process.env.QA_UPSTREAM_PORT || 8001)
const listenPort = Number(process.env.QA_PROXY_PORT || 8002)
let streamsBlocked = false
const activeStreams = new Set()
const blockedClients = new Set()
const reconnects = []
const streamResponses = []

const server = http.createServer((request, response) => {
  const path = request.url || '/'
  if (path.startsWith('/__qa/')) {
    if (request.method !== 'POST' && path !== '/__qa/status') {
      response.writeHead(405).end()
      return
    }
    const body = []
    request.on('data', (chunk) => body.push(chunk))
    request.on('end', () => {
      let clientId
      try {
        clientId = JSON.parse(Buffer.concat(body).toString('utf8')).clientId
      } catch {
        clientId = undefined
      }
      if (path === '/__qa/cut') {
        if (clientId) blockedClients.add(clientId)
        streamsBlocked = blockedClients.size > 0
        const matching = [...activeStreams].filter((stream) => !clientId || stream.clientId === clientId)
        for (const stream of matching) {
          activeStreams.delete(stream)
          stream.upstream.destroy()
          stream.downstream.destroy()
        }
        json(response, 200, { blocked: streamsBlocked, cutCount: matching.length })
        return
      }
      if (path === '/__qa/release') {
        if (clientId) blockedClients.delete(clientId)
        else blockedClients.clear()
        streamsBlocked = blockedClients.size > 0
        json(response, 200, { blocked: streamsBlocked })
        return
      }
      if (path === '/__qa/status') {
        json(response, 200, {
          blocked: streamsBlocked,
          blockedClients: [...blockedClients],
          activeStreams: activeStreams.size,
          reconnects: reconnects.slice(-40),
          streamResponses: streamResponses.slice(-40),
        })
        return
      }
      response.writeHead(404).end()
    })
    return
  }

  const isStream = path.startsWith('/api/v2/notifications/stream')
  const clientId = request.headers['x-qa-client']
  if (isStream && request.method === 'OPTIONS') {
    response.writeHead(204, {
      'access-control-allow-origin': request.headers.origin || 'null',
      'access-control-allow-credentials': 'true',
      'access-control-allow-methods': 'GET, OPTIONS',
      'access-control-allow-headers': request.headers['access-control-request-headers'] || 'last-event-id',
      'access-control-max-age': '60',
      vary: 'Origin',
    })
    response.end()
    return
  }
  if (isStream) {
    reconnects.push({ at: new Date().toISOString(), clientId: clientId || null, lastEventId: request.headers['last-event-id'] || null })
    if (reconnects.length > 100) reconnects.shift()
    if (clientId && blockedClients.has(clientId)) {
      response.writeHead(200, {
        'content-type': 'text/event-stream; charset=utf-8',
        'cache-control': 'no-store',
        'access-control-allow-origin': request.headers.origin || 'null',
        'access-control-allow-credentials': 'true',
        vary: 'Origin',
      })
      // A valid but immediately closed SSE response keeps native EventSource in
      // CONNECTING/retry mode; a 4xx/5xx or CORS failure would close it permanently.
      response.end('retry: 1000\n\n: QA fault injection\n\n')
      return
    }
  }

  const upstream = http.request({
    hostname: '127.0.0.1',
    port: upstreamPort,
    path,
    method: request.method,
    headers: {
      ...request.headers,
      // The app intentionally trusts its configured local test origin for all writes.
      origin: 'http://127.0.0.1:5173',
      // Keep the browser host so the notification endpoint recognizes a same-site origin.
      host: request.headers.host,
    },
  }, (upstreamResponse) => {
    if (isStream) {
      streamResponses.push({
        at: new Date().toISOString(),
        clientId: clientId || null,
        status: upstreamResponse.statusCode || 502,
        browserSentCookie: Boolean(request.headers.cookie),
        upstreamSentCookie: Boolean(request.headers.cookie),
      })
      if (streamResponses.length > 100) streamResponses.shift()
    }
    if (!isStream) {
      response.writeHead(upstreamResponse.statusCode || 502, upstreamResponse.headers)
      upstreamResponse.pipe(response)
      return
    }

    const stream = { upstream, downstream: response, clientId }
    activeStreams.add(stream)
    const remove = () => activeStreams.delete(stream)
    response.on('close', remove)
    upstreamResponse.on('close', remove)
    upstreamResponse.on('error', remove)
    const headers = { ...upstreamResponse.headers }
    if (request.headers.origin) {
      headers['access-control-allow-origin'] = request.headers.origin
      headers['access-control-allow-credentials'] = 'true'
      headers.vary = 'Origin'
    }
    response.writeHead(upstreamResponse.statusCode || 502, headers)
    upstreamResponse.pipe(response)
  })

  upstream.on('error', (error) => {
    if (isStream) {
      streamResponses.push({
        at: new Date().toISOString(),
        clientId: clientId || null,
        errorType: error.code || error.name || 'Error',
      })
      if (streamResponses.length > 100) streamResponses.shift()
    }
    if (!response.headersSent) json(response, 502, { error: error.message })
    else response.destroy()
  })
  request.pipe(upstream)
})

function json(response, status, body) {
  response.writeHead(status, { 'content-type': 'application/json', 'cache-control': 'no-store' })
  response.end(JSON.stringify(body))
}

server.listen(listenPort, '127.0.0.1', () => {
  process.stdout.write(`QA SSE fault proxy listening on 127.0.0.1:${listenPort} -> ${upstreamPort}\n`)
})

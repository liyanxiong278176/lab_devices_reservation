/**
 * 生成 RFC4122 v4 UUID。
 *
 * <p>优先 {@code crypto.randomUUID()};不可用时(非"安全上下文":prod 经服务器 IP + 纯 HTTP 访问,
 * window.crypto.randomUUID 为 undefined,会抛 TypeError)回退到 {@code crypto.getRandomValues}
 * (后者在非安全 HTTP 上下文也可用)。
 *
 * <p>本地 localhost 即使走 HTTP 也算安全上下文,故 dev 不受影响;只有 prod HTTP 会触发回退。
 */
export function uuid(): string {
  const c = globalThis.crypto
  if (typeof c?.randomUUID === 'function') {
    return c.randomUUID()
  }
  // 回退:用 getRandomValues 手搓 v4
  const b = c.getRandomValues(new Uint8Array(16))
  b[6] = (b[6] & 0x0f) | 0x40 // version 4
  b[8] = (b[8] & 0x3f) | 0x80 // variant 10
  const h = Array.from(b, (x) => x.toString(16).padStart(2, '0'))
  return `${h.slice(0, 4).join('')}-${h.slice(4, 6).join('')}-${h.slice(6, 8).join('')}-${h.slice(8, 10).join('')}-${h.slice(10, 16).join('')}`
}

import assert from 'node:assert/strict'
import test from 'node:test'
import { webcrypto } from 'node:crypto'
import { createUuid } from '../src/lib/uuid.ts'

function withCrypto(value: unknown, callback: () => void) {
  const original = Object.getOwnPropertyDescriptor(globalThis, 'crypto')
  Object.defineProperty(globalThis, 'crypto', { configurable: true, value })
  try { callback() }
  finally {
    if (original) Object.defineProperty(globalThis, 'crypto', original)
    else Reflect.deleteProperty(globalThis, 'crypto')
  }
}

test('uses the native UUID method when available', () => {
  const expected = 'b6390618-3796-460f-99f8-53eeac390f26'
  const cryptoApi = {
    randomUUID() {
      assert.equal(this, cryptoApi)
      return expected
    },
  }
  withCrypto(cryptoApi, () => assert.equal(createUuid(), expected))
})

test('HTTP-like context without randomUUID still produces valid v4 UUIDs', () => {
  withCrypto({ getRandomValues: webcrypto.getRandomValues.bind(webcrypto) }, () => {
    const ids = Array.from({ length: 100 }, () => createUuid())
    for (const id of ids) {
      assert.match(id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
    }
    assert.equal(new Set(ids).size, ids.length)
  })
})

test('reports an unsupported browser clearly when no crypto API is available', () => {
  withCrypto(undefined, () => assert.throws(() => createUuid(), /浏览器不支持/))
})

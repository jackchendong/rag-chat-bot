import assert from 'node:assert/strict'
import test from 'node:test'
import { mergeMessageUpdates } from '../src/lib/message-updates.ts'
import { refreshVisiblePages } from '../src/lib/pagination.ts'
import type { Message } from '../src/types/chat.ts'

function message(id: string, status: Message['status'], content = ''): Message {
  return { id, role: 'assistant', status, content, created_at: '2026-10-19T00:00:00Z' }
}

test('a background answer changes from generating to its saved result without losing older history', () => {
  const current = [message('1', 'completed', '早期记录'), message('2', 'generating')]
  const updated = mergeMessageUpdates(current, [message('2', 'completed', '任务执行结果')])
  assert.equal(updated.length, 2)
  assert.equal(updated[0]?.content, '早期记录')
  assert.equal(updated[1]?.status, 'completed')
  assert.equal(updated[1]?.content, '任务执行结果')
})

test('new background messages appear once and matching text does not merge different message IDs', () => {
  const current = [message('1', 'completed', '相同内容')]
  const incoming = [message('1', 'completed', '相同内容'), message('2', 'completed', '相同内容')]
  const once = mergeMessageUpdates(current, incoming)
  assert.deepEqual(mergeMessageUpdates(once, incoming).map(row => row.id), ['1', '2'])
})

test('a delayed poll cannot replace an already completed SSE answer with an empty generating row', () => {
  const completed = message('2', 'completed', '最终结果')
  assert.deepEqual(mergeMessageUpdates([completed], [message('2', 'generating')]), [completed])
})

test('refresh keeps two pages of executions visible while updating the active run', async () => {
  const records = Array.from({ length: 45 }, (_, id) => ({ id, status: 'completed', result: `结果${id}` }))
  const result = await refreshVisiblePages(40, 20, async offset => records.slice(offset, offset + 20))
  assert.equal(result.rows.length, 40)
  assert.equal(result.rows[0]?.status, 'completed')
  assert.equal(result.rows[0]?.result, '结果0')
  assert.equal(result.rows.at(-1)?.id, 39)
  assert.equal(result.hasMore, true)
})

test('a short final page clears load-more and remains visible after refresh', async () => {
  const records = Array.from({ length: 23 }, (_, id) => ({ id }))
  const result = await refreshVisiblePages(23, 20, async offset => records.slice(offset, offset + 20))
  assert.equal(result.rows.length, 23)
  assert.equal(result.hasMore, false)
})

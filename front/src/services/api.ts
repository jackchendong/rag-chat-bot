import type { ChatEvent, Conversation, Message, User } from '@/types/chat'

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('服务器返回格式无效')
  return value as Record<string, unknown>
}

function text(value: unknown): string {
  if (typeof value !== 'string') throw new Error('服务器返回字段无效')
  return value
}

function parseUser(value: unknown): User {
  const data = record(value)
  const user_id = text(data.user_id)
  if (!/^[1-9]\d*$/.test(user_id)) throw new Error('用户 ID 无效')
  return { user_id, account: text(data.account) }
}

function parseConversation(value: unknown): Conversation {
  const data = record(value)
  return { conversation_id: text(data.conversation_id), title: text(data.title), updated_at: text(data.updated_at) }
}

function parseMessage(value: unknown): Message {
  const data = record(value)
  if (data.role !== 'user' && data.role !== 'assistant') throw new Error('消息角色无效')
  if (data.status !== 'generating' && data.status !== 'completed' && data.status !== 'failed' && data.status !== 'cancelled') {
    throw new Error('消息状态无效')
  }
  return { id: text(data.id), role: data.role, content: text(data.content), status: data.status, created_at: text(data.created_at) }
}

async function ensureSuccess(response: Response): Promise<void> {
  if (response.ok) return
  let message = `请求失败（${response.status}）`
  try {
    const data = record(await response.json())
    if (typeof data.message === 'string') message = data.message
    else if (response.status === 422) message = '输入格式不正确，请检查后重试'
  } catch {
    message = response.status === 503 ? '后端或数据库暂不可用，请稍后重试' : message
  }
  throw new ApiError(message, response.status)
}

async function request(path: string, userId: string | null, signal: AbortSignal, body?: unknown): Promise<unknown> {
  const response = await fetch(`/api${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { ...(userId ? { 'X-User-Id': userId } : {}), ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  })
  await ensureSuccess(response)
  return response.json()
}

export async function login(account: string, signal: AbortSignal): Promise<User> {
  return parseUser(await request('/login', null, signal, { account }))
}

export async function currentUser(userId: string, signal: AbortSignal): Promise<User> {
  return parseUser(await request('/users/me', userId, signal))
}

export async function createConversation(userId: string, signal: AbortSignal): Promise<Conversation> {
  return parseConversation(await request('/conversations', userId, signal, {}))
}

export async function listConversations(userId: string, offset: number, signal: AbortSignal): Promise<Conversation[]> {
  const data = await request(`/conversations?offset=${offset}&limit=30`, userId, signal)
  if (!Array.isArray(data)) throw new Error('对话列表格式无效')
  return data.map(parseConversation)
}

export async function listMessages(userId: string, conversationId: string, signal: AbortSignal, before?: string): Promise<Message[]> {
  const query = new URLSearchParams({ limit: '50' })
  if (before) query.set('before', before)
  const data = await request(`/conversations/${encodeURIComponent(conversationId)}/messages?${query}`, userId, signal)
  if (!Array.isArray(data)) throw new Error('消息列表格式无效')
  return data.map(parseMessage)
}

export async function stopChat(userId: string, conversationId: string, assistantMessageId: string, signal: AbortSignal): Promise<boolean> {
  const data = record(await request('/chat/stop', userId, signal, {
    conversation_id: conversationId, assistant_message_id: assistantMessageId,
  }))
  if (typeof data.stopped !== 'boolean') throw new Error('停止响应格式无效')
  return data.stopped
}

export async function streamChat(
  userId: string, conversationId: string, message: string, signal: AbortSignal,
  onEvent: (event: ChatEvent) => void,
): Promise<void> {
  const response = await fetch('/api/chat', {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-User-Id': userId },
    body: JSON.stringify({ conversation_id: conversationId, message }), signal,
  })
  await ensureSuccess(response)
  if (!response.headers.get('content-type')?.includes('text/event-stream') || !response.body) {
    throw new Error('服务器未返回流式回答')
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (true) {
      const chunk = await reader.read()
      buffer += decoder.decode(chunk.value, { stream: !chunk.done })
      buffer = buffer.replace(/\r\n/g, '\n')
      if (buffer.length > 1024 * 1024) throw new Error('回答数据过大')
      let separator = buffer.indexOf('\n\n')
      while (separator >= 0) {
        const frame = buffer.slice(0, separator)
        buffer = buffer.slice(separator + 2)
        const lines = frame.split('\n')
        const event = lines.find(line => line.startsWith('event:'))?.slice(6).trim()
        const payload = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).replace(/^ /, '')).join('\n')
        if (payload) {
          const data = record(JSON.parse(payload))
          if (event === 'error') throw new Error(text(data.message))
          if (event === 'meta') onEvent({ event, user_message_id: text(data.user_message_id), assistant_message_id: text(data.assistant_message_id) })
          else if (event === 'message') onEvent({ event, content: text(data.content) })
          else if (event === 'done') {
            if (typeof data.truncated !== 'boolean') throw new Error('结束事件格式无效')
            if (data.cancelled !== undefined && typeof data.cancelled !== 'boolean') throw new Error('结束事件格式无效')
            onEvent({ event, truncated: data.truncated, cancelled: data.cancelled === true })
            return
          }
        }
        separator = buffer.indexOf('\n\n')
      }
      if (chunk.done) throw new Error('回答连接中断，未收到完成事件')
    }
  } finally {
    await reader.cancel().catch(() => undefined)
    reader.releaseLock()
  }
}

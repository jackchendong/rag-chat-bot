import type { Message } from '@/types/chat'

export function mergeMessageUpdates(current: Message[], incoming: Message[]): Message[] {
  const updates = new Map(incoming.map(message => [message.id, message]))
  const existing = new Set(current.map(message => message.id))
  return [
    ...current.map(message => {
      const update = updates.get(message.id)
      // An older poll response must not regress an answer already finished by SSE.
      if (!update || (message.status !== 'generating' && update.status === 'generating')) return message
      return update
    }),
    ...incoming.filter(message => !existing.has(message.id)),
  ]
}

export interface User {
  user_id: string
  account: string
}

export interface Conversation {
  conversation_id: string
  title: string
  updated_at: string
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  status: 'generating' | 'completed' | 'failed' | 'cancelled'
  created_at: string
}

export type ChatEvent =
  | { event: 'meta'; user_message_id: string; assistant_message_id: string }
  | { event: 'message'; content: string }
  | { event: 'done'; truncated: boolean }

<script setup lang="ts">
import { nextTick, ref } from 'vue'
import DOMPurify from 'dompurify'
import { ArrowUp, Bot, LoaderCircle, Sparkles, UserRound } from 'lucide-vue-next'
import MarkdownIt from 'markdown-it'
import {
  ScrollAreaRoot,
  ScrollAreaScrollbar,
  ScrollAreaThumb,
  ScrollAreaViewport,
} from 'radix-vue'

import Button from './components/ui/Button.vue'

type ChatRole = 'user' | 'assistant'

interface ChatMessage {
  id: string
  role: ChatRole
  content: string
}

const conversationId = 'default'
const messages = ref<ChatMessage[]>([
  {
    id: crypto.randomUUID(),
    role: 'assistant',
    content: 'Hi, I am your chat assistant. Ask me anything and I will respond in stream mode.',
  },
])

const messageInput = ref('')
const pending = ref(false)

const md = new MarkdownIt({
  html: false,
  breaks: true,
  linkify: true,
  typographer: true,
})

function renderMarkdown(content: string): string {
  return DOMPurify.sanitize(md.render(content))
}

function scrollToBottom() {
  nextTick(() => {
    const viewport = document.getElementById('chat-viewport')
    if (!viewport) return
    viewport.scrollTop = viewport.scrollHeight
  })
}

function appendAssistantDelta(targetId: string, delta: string) {
  const idx = messages.value.findIndex((m) => m.id === targetId)
  if (idx < 0) return
  messages.value[idx] = {
    ...messages.value[idx],
    content: messages.value[idx].content + delta,
  }
}

function parseEventBlock(block: string): { event: string; data: string } {
  let event = 'message'
  const dataLines: string[] = []

  for (const line of block.replace(/\r\n/g, '\n').split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
  }

  return { event, data: dataLines.join('\n') }
}

function extractSseEvents(buffer: string): { events: string[]; rest: string } {
  const normalized = buffer.replace(/\r\n/g, '\n')
  const events: string[] = []
  let cursor = 0

  while (true) {
    const boundary = normalized.indexOf('\n\n', cursor)
    if (boundary === -1) {
      return {
        events,
        rest: normalized.slice(cursor),
      }
    }

    events.push(normalized.slice(cursor, boundary))
    cursor = boundary + 2
  }
}

async function sendMessage() {
  const content = messageInput.value.trim()
  if (!content || pending.value) return

  pending.value = true
  messageInput.value = ''

  const userMessage: ChatMessage = {
    id: crypto.randomUUID(),
    role: 'user',
    content,
  }
  const assistantMessageId = crypto.randomUUID()
  messages.value.push(userMessage)
  messages.value.push({ id: assistantMessageId, role: 'assistant', content: '' })
  scrollToBottom()

  try {
    const response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: content,
        conversation_id: conversationId,
      }),
    })

    if (!response.ok || !response.body) {
      throw new Error(`request failed with status ${response.status}`)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''

    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done })
      const extracted = extractSseEvents(buffer)
      const events = extracted.events
      buffer = extracted.rest

      for (const rawEvent of events) {
        if (!rawEvent.trim()) continue

        const event = parseEventBlock(rawEvent)
        if (!event.data) continue

        const payload = JSON.parse(event.data) as {
          delta?: string
          done?: boolean
          error?: string
        }

        if (event.event === 'error' || payload.error) {
          throw new Error(payload.error ?? 'stream error')
        }

        if (payload.done) continue
        if (payload.delta) {
          appendAssistantDelta(assistantMessageId, payload.delta)
          scrollToBottom()
        }
      }

      if (done) break
    }

    const tailEvent = buffer.trim()
    if (tailEvent) {
      const event = parseEventBlock(tailEvent)
      if (event.data) {
        const payload = JSON.parse(event.data) as {
          delta?: string
          done?: boolean
          error?: string
        }
        if (payload.delta) {
          appendAssistantDelta(assistantMessageId, payload.delta)
          scrollToBottom()
        }
      }
    }
  } catch (error) {
    const text = error instanceof Error ? error.message : 'unknown error'
    appendAssistantDelta(assistantMessageId, `\n[error] ${text}`)
  } finally {
    if (!messages.value.find((m) => m.id === assistantMessageId)?.content.trim()) {
      appendAssistantDelta(assistantMessageId, 'No response from model.')
    }
    pending.value = false
    scrollToBottom()
  }
}

function onSubmit(event: Event) {
  event.preventDefault()
  void sendMessage()
}
</script>

<template>
  <main class="mx-auto flex min-h-screen w-full max-w-6xl flex-col px-3 py-4 sm:px-6 sm:py-7">
    <section
      class="glass-panel flex flex-1 flex-col overflow-hidden rounded-3xl shadow-[0_20px_70px_rgba(80,64,42,0.14)]">
      <header
        class="flex items-center justify-between border-b border-[rgb(var(--border))] bg-gradient-to-r from-amber-50/90 via-emerald-50/80 to-cyan-50/70 px-4 py-3 sm:px-6">
        <div class="flex items-center gap-3">
          <div class="flex h-9 w-9 items-center justify-center rounded-xl bg-zinc-900 text-zinc-50 shadow-sm">
            <Sparkles class="h-4 w-4" />
          </div>
          <div>
            <h1 class="m-0 text-lg font-semibold text-zinc-900 sm:text-xl">Dialog Studio</h1>
            <p class="m-0 text-xs text-zinc-500 sm:text-sm">SSE streaming · conversation_id=default</p>
          </div>
        </div>
        <span class="rounded-full bg-emerald-100 px-3 py-1 text-xs font-medium text-emerald-800">
          /api/chat/stream
        </span>
      </header>

      <ScrollAreaRoot class="relative flex-1">
        <ScrollAreaViewport id="chat-viewport" class="h-[58vh] w-full px-3 py-4 sm:h-[64vh] sm:px-6">
          <div class="mx-auto flex w-full max-w-3xl flex-col gap-3 pb-8">
            <article v-for="message in messages" :key="message.id" class="bubble-animate flex"
              :class="message.role === 'user' ? 'justify-end' : 'justify-start'">
              <div class="flex max-w-[85%] gap-2 rounded-2xl px-3 py-2.5 sm:max-w-[72%] sm:px-4" :class="message.role === 'user'
                ? 'bg-zinc-900 text-zinc-50 shadow-[0_10px_28px_rgba(24,24,27,0.34)]'
                : 'border border-zinc-200 bg-white text-zinc-800 shadow-[0_8px_22px_rgba(125,110,90,0.16)]'
                ">
                <span class="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-lg"
                  :class="message.role === 'user' ? 'bg-zinc-700/70' : 'bg-zinc-100'">
                  <UserRound v-if="message.role === 'user'" class="h-3.5 w-3.5" />
                  <Bot v-else class="h-3.5 w-3.5 text-zinc-600" />
                </span>
                <div class="md-content min-w-0 text-sm leading-relaxed sm:text-[15px]"
                  v-html="renderMarkdown(message.content)" />
              </div>
            </article>
          </div>
        </ScrollAreaViewport>

        <ScrollAreaScrollbar
          class="flex touch-none select-none p-0.5 transition-colors duration-150 data-[orientation=vertical]:w-2"
          orientation="vertical">
          <ScrollAreaThumb class="relative flex-1 rounded-full bg-zinc-300" />
        </ScrollAreaScrollbar>
      </ScrollAreaRoot>

      <footer class="border-t border-[rgb(var(--border))] bg-white/90 px-3 py-3 sm:px-6 sm:py-4">
        <form class="mx-auto flex w-full max-w-3xl items-end gap-2 sm:gap-3" @submit="onSubmit">
          <label class="sr-only" for="message-input">Message</label>
          <textarea id="message-input" v-model="messageInput" rows="2" placeholder="Type your message..."
            class="max-h-32 min-h-11 flex-1 resize-y rounded-2xl border border-zinc-300 bg-zinc-50 px-4 py-2.5 text-sm leading-6 text-zinc-900 placeholder:text-zinc-400 focus:border-emerald-600 focus:ring-2 focus:ring-emerald-600/20"
            :disabled="pending" />
          <Button class="h-11 rounded-2xl px-4 sm:px-5" :disabled="pending || !messageInput.trim()" type="submit">
            <LoaderCircle v-if="pending" class="mr-1 h-4 w-4 animate-spin" />
            <ArrowUp v-else class="mr-1 h-4 w-4" />
            Send
          </Button>
        </form>
      </footer>
    </section>
  </main>
</template>

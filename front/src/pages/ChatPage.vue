<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { ApiError, createConversation, listConversations, listMessages, stopChat, streamChat } from '@/services/api'
import type { Conversation, Message, User } from '@/types/chat'
import SchedulePanel from '@/components/SchedulePanel.vue'
import { mergeMessageUpdates } from '@/lib/message-updates'
import { createUuid } from '@/lib/uuid'

const props = defineProps<{ user: User }>()
const emit = defineEmits<{ logout: [] }>()
const conversations = ref<Conversation[]>([])
const messages = ref<Message[]>([])
const selectedId = ref<string | null>(null)
const draft = ref('')
const error = ref('')
const notice = ref('')
const busy = ref(false)
const stopping = ref(false)
const activeAssistantId = ref<string | null>(null)
const loading = ref(false)
const loadingHistory = ref(false)
const moreConversations = ref(false)
const moreMessages = ref(false)
const sidebarOpen = ref(false)
const messageArea = ref<HTMLElement | null>(null)
const follow = ref(true)
const tasksVisible = ref(false)
const taskPanel = ref<InstanceType<typeof SchedulePanel> | null>(null)
const highlightedMessage = ref<string | null>(null)
const viewingRecord = ref(false)
const backgroundError = ref('')
const title = computed(() => conversations.value.find(item => item.conversation_id === selectedId.value)?.title || '新对话')
let version = 0
let streamController: AbortController | null = null
let stopController: AbortController | null = null
let viewController: AbortController | null = null
let listController: AbortController | null = null
let backgroundController: AbortController | null = null
let backgroundTimer: ReturnType<typeof setInterval> | undefined

async function refreshBackgroundMessages() {
  if (!selectedId.value || tasksVisible.value || busy.value || loading.value || document.hidden || backgroundController) return
  const currentVersion = version
  const controller = new AbortController()
  backgroundController = controller
  try {
    const before = viewingRecord.value && highlightedMessage.value ? (BigInt(highlightedMessage.value) + 1n).toString() : undefined
    const rows = await listMessages(props.user.user_id, selectedId.value, controller.signal, before)
    if (currentVersion !== version || controller.signal.aborted || busy.value || loading.value) return
    const currentBefore = viewingRecord.value && highlightedMessage.value ? (BigInt(highlightedMessage.value) + 1n).toString() : undefined
    if (currentBefore !== before) return
    backgroundError.value = ''
    messages.value = mergeMessageUpdates(messages.value, rows)
    await scrollToBottom()
  } catch (failure) {
    if (currentVersion !== version || controller.signal.aborted) return
    if (failure instanceof ApiError && failure.status === 401) report(failure)
    else backgroundError.value = failure instanceof Error ? `消息自动刷新失败：${failure.message}` : '消息自动刷新失败，请稍后重试'
  } finally {
    if (backgroundController === controller) backgroundController = null
  }
}

function report(failure: unknown) {
  if (failure instanceof ApiError && failure.status === 401) {
    emit('logout')
    return
  }
  error.value = failure instanceof Error ? failure.message : '请求失败，请稍后重试'
}

async function scrollToBottom(force = false) {
  await nextTick()
  if ((follow.value || force) && messageArea.value) messageArea.value.scrollTop = messageArea.value.scrollHeight
}

function trackScroll() {
  const element = messageArea.value
  if (element) follow.value = element.scrollHeight - element.scrollTop - element.clientHeight < 100
}

async function refreshConversations(append = false) {
  listController?.abort()
  const controller = new AbortController()
  listController = controller
  loadingHistory.value = true
  try {
    const rows = await listConversations(props.user.user_id, append ? conversations.value.length : 0, controller.signal)
    if (controller.signal.aborted) return
    conversations.value = append ? [...conversations.value, ...rows] : rows
    moreConversations.value = rows.length === 30
  } catch (failure) {
    if (!controller.signal.aborted) report(failure)
  } finally {
    if (listController === controller) loadingHistory.value = false
  }
}

function resetView() {
  version += 1
  streamController?.abort()
  stopController?.abort()
  viewController?.abort()
  backgroundController?.abort()
  backgroundController = null
  backgroundError.value = ''
  busy.value = false
  stopping.value = false
  activeAssistantId.value = null
  loading.value = false
  error.value = ''
  notice.value = ''
  draft.value = ''
  sidebarOpen.value = false
  follow.value = true
  tasksVisible.value = false
  highlightedMessage.value = null
  viewingRecord.value = false
}

function showTasks() {
  resetView()
  tasksVisible.value = true
}

async function jumpToRecord(conversationId: string, messageId?: string) {
  let conversation = conversations.value.find(item => item.conversation_id === conversationId)
  if (!conversation) {
    conversation = { conversation_id: conversationId, title: '任务对话', updated_at: new Date().toISOString() }
    conversations.value.unshift(conversation)
  }
  const currentVersion = version + 1
  await selectConversation(conversation)
  if (currentVersion !== version) return
  if (selectedId.value !== conversationId || tasksVisible.value || !messageId) return
  try {
    if (!messages.value.some(item => item.id === messageId)) {
      loading.value = true
      const controller = new AbortController()
      viewController = controller
      const rows = await listMessages(props.user.user_id, conversationId, controller.signal, (BigInt(messageId) + 1n).toString())
      if (currentVersion !== version) return
      messages.value = rows
      moreMessages.value = rows.length === 50
      viewingRecord.value = true
    }
    highlightedMessage.value = messageId
    follow.value = false
    await nextTick()
    document.getElementById(`message-${messageId}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  } catch (failure) { if (currentVersion === version) report(failure) }
  finally { if (currentVersion === version) loading.value = false }
}

function newConversation() {
  resetView()
  selectedId.value = null
  messages.value = []
  moreMessages.value = false
}

async function selectConversation(conversation: Conversation) {
  resetView()
  const currentVersion = version
  selectedId.value = conversation.conversation_id
  messages.value = []
  moreMessages.value = false
  loading.value = true
  const controller = new AbortController()
  viewController = controller
  try {
    const rows = await listMessages(props.user.user_id, conversation.conversation_id, controller.signal)
    if (currentVersion !== version || controller.signal.aborted) return
    messages.value = rows
    moreMessages.value = rows.length === 50
    await scrollToBottom(true)
  } catch (failure) {
    if (currentVersion === version && !controller.signal.aborted) report(failure)
  } finally {
    if (currentVersion === version) loading.value = false
  }
}

async function loadOlderMessages() {
  const first = messages.value[0]
  if (!selectedId.value || !first || loading.value || busy.value) return
  const currentVersion = version
  const controller = new AbortController()
  viewController = controller
  loading.value = true
  const oldHeight = messageArea.value?.scrollHeight || 0
  try {
    const rows = await listMessages(props.user.user_id, selectedId.value, controller.signal, first.id)
    if (currentVersion !== version || controller.signal.aborted) return
    messages.value = [...rows, ...messages.value]
    moreMessages.value = rows.length === 50
    await nextTick()
    if (messageArea.value) messageArea.value.scrollTop += messageArea.value.scrollHeight - oldHeight
  } catch (failure) {
    if (currentVersion === version && !controller.signal.aborted) report(failure)
  } finally {
    if (currentVersion === version) loading.value = false
  }
}

async function send() {
  const content = draft.value.trim()
  if (!content || content.length > 10000 || busy.value || loading.value || viewingRecord.value) return
  let localId: string
  try {
    localId = createUuid()
  } catch (failure) {
    report(failure)
    return
  }
  backgroundController?.abort()
  backgroundController = null
  const currentVersion = version
  const controller = new AbortController()
  streamController = controller
  busy.value = true
  stopping.value = false
  activeAssistantId.value = null
  error.value = ''
  notice.value = ''
  follow.value = true
  let accepted = false
  const userMessage: Message = { id: `local-user-${localId}`, role: 'user', content, status: 'completed', created_at: new Date().toISOString() }
  const assistantMessage: Message = { id: `local-assistant-${localId}`, role: 'assistant', content: '', status: 'generating', created_at: new Date().toISOString() }
  try {
    if (!selectedId.value) {
      const conversation = await createConversation(props.user.user_id, controller.signal)
      if (currentVersion !== version || controller.signal.aborted) return
      selectedId.value = conversation.conversation_id
      conversations.value.unshift(conversation)
    }
    messages.value.push(userMessage, assistantMessage)
    await scrollToBottom(true)
    await streamChat(props.user.user_id, selectedId.value, content, controller.signal, event => {
      if (currentVersion !== version || controller.signal.aborted) return
      const userRow = messages.value.find(item => item.id === userMessage.id)
      const assistantRow = messages.value.find(item => item.id === assistantMessage.id)
      if (event.event === 'meta') {
        accepted = true
        draft.value = ''
        if (userRow) userRow.id = event.user_message_id
        if (assistantRow) assistantRow.id = event.assistant_message_id
        userMessage.id = event.user_message_id
        assistantMessage.id = event.assistant_message_id
        activeAssistantId.value = event.assistant_message_id
        void refreshConversations()
      } else if (event.event === 'message' && assistantRow) {
        assistantRow.content += event.content
        void scrollToBottom()
      } else if (event.event === 'done' && assistantRow) {
        assistantRow.status = event.cancelled ? 'cancelled' : 'completed'
        if (event.cancelled) notice.value = '已停止生成，已保留生成内容。'
        if (event.truncated) notice.value = '回答达到输出长度上限，可以继续追问。'
      }
    })
  } catch (failure) {
    if (currentVersion !== version) return
    const assistantRow = messages.value.find(item => item.id === assistantMessage.id)
    if (controller.signal.aborted) {
      if (assistantRow) assistantRow.status = 'cancelled'
      notice.value = '已停止生成。'
    } else {
      if (assistantRow) assistantRow.status = 'failed'
      draft.value = content
      if (!accepted) messages.value = messages.value.filter(item => item.id !== userMessage.id && item.id !== assistantMessage.id)
      report(failure)
    }
  } finally {
    if (currentVersion === version) {
      busy.value = false
      stopping.value = false
      activeAssistantId.value = null
      void refreshConversations()
      void taskPanel.value?.refresh()
    }
  }
}

async function stop() {
  const conversationId = selectedId.value
  const assistantId = activeAssistantId.value
  if (!busy.value || stopping.value || !conversationId || !assistantId) return
  const currentVersion = version
  const activeStream = streamController
  const controller = new AbortController()
  stopController = controller
  stopping.value = true
  error.value = ''
  let accepted = false
  const timeout = window.setTimeout(() => controller.abort(), 15000)
  try {
    const stopped = await stopChat(props.user.user_id, conversationId, assistantId, controller.signal)
    if (currentVersion !== version || activeStream !== streamController) return
    accepted = stopped
    if (!stopped) notice.value = '回答已结束。'
    // Keep the SSE connection until the server has saved partial text and sent done.
  } catch (failure) {
    if (currentVersion !== version || activeStream !== streamController) return
    if (controller.signal.aborted) error.value = '停止请求超时，请重试。'
    else report(failure)
  } finally {
    window.clearTimeout(timeout)
    if (stopController === controller) {
      stopController = null
      if (!accepted || !busy.value) stopping.value = false
    }
  }
}

function handleEnter(event: KeyboardEvent) {
  if (event.isComposing || event.shiftKey) return
  event.preventDefault()
  void send()
}

function logout() {
  resetView()
  listController?.abort()
  emit('logout')
}

onMounted(() => {
  void refreshConversations()
  backgroundTimer = setInterval(() => void refreshBackgroundMessages(), 5000)
})
onBeforeUnmount(() => {
  version += 1
  streamController?.abort()
  stopController?.abort()
  viewController?.abort()
  listController?.abort()
  backgroundController?.abort()
  clearInterval(backgroundTimer)
})
</script>

<template>
  <div class="flex h-svh overflow-hidden bg-background">
    <button v-if="sidebarOpen" aria-label="关闭侧栏" class="fixed inset-0 z-20 bg-black/30 md:hidden" @click="sidebarOpen = false" />
    <aside :class="sidebarOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'"
      class="fixed inset-y-0 left-0 z-30 flex w-64 shrink-0 flex-col border-r bg-muted p-3 transition-transform md:static">
      <div class="flex items-center justify-between px-3 py-4"><span class="font-semibold">✦ Chat Demo</span><button aria-label="关闭侧栏" class="md:hidden" @click="sidebarOpen = false">✕</button></div>
      <button class="rounded-xl border bg-background px-4 py-3 text-left text-sm font-medium hover:bg-accent" @click="newConversation">＋ 新建对话</button>
      <button :aria-current="tasksVisible ? 'page' : undefined" class="mt-2 rounded-xl px-4 py-3 text-left text-sm font-medium hover:bg-accent" :class="tasksVisible ? 'bg-accent' : ''" @click="showTasks">◷ 定时任务</button>
      <div class="mt-6 flex items-center justify-between px-3 text-xs text-muted-foreground"><span>你的对话</span><button :disabled="loadingHistory" aria-label="刷新对话历史" @click="refreshConversations()">刷新</button></div>
      <nav aria-label="对话历史" class="mt-2 flex-1 space-y-1 overflow-y-auto">
        <p v-if="!conversations.length" class="px-3 py-4 text-xs text-muted-foreground">{{ loadingHistory ? '正在加载…' : '还没有对话，开始聊聊吧' }}</p>
        <button v-for="conversation in conversations" :key="conversation.conversation_id" :title="conversation.title"
          :aria-current="selectedId === conversation.conversation_id ? 'page' : undefined"
          :class="selectedId === conversation.conversation_id ? 'bg-accent font-medium' : 'hover:bg-accent/70'"
          class="block w-full truncate rounded-lg px-3 py-3 text-left text-sm" @click="selectConversation(conversation)">{{ conversation.title }}</button>
        <button v-if="moreConversations" :disabled="loadingHistory" class="w-full py-3 text-xs text-muted-foreground" @click="refreshConversations(true)">加载更多</button>
      </nav>
      <div class="mt-3 border-t pt-3"><p class="truncate px-3 text-sm font-medium" :title="user.account">{{ user.account }}</p><button class="mt-2 w-full rounded-lg px-3 py-2 text-left text-sm text-muted-foreground hover:bg-accent" @click="logout">退出登录</button></div>
    </aside>
    <main class="flex min-w-0 flex-1 flex-col">
      <header class="flex h-16 shrink-0 items-center gap-3 border-b px-5"><button aria-label="打开对话历史" class="rounded-lg p-2 md:hidden" @click="sidebarOpen = true">☰</button><h1 class="truncate text-sm font-medium">{{ tasksVisible ? '定时任务' : title }}</h1></header>
      <div v-if="tasksVisible" class="flex-1 overflow-y-auto p-4 md:p-8"><SchedulePanel :user-id="user.user_id" class="mx-auto max-w-4xl" @jump="jumpToRecord" @logout="logout" /></div>
      <template v-else>
      <details v-if="selectedId" class="shrink-0 border-b px-5 py-3" open>
        <summary class="cursor-pointer text-xs text-muted-foreground">对话任务</summary>
        <div class="mt-3 max-h-[30svh] overflow-y-auto"><SchedulePanel :key="selectedId" ref="taskPanel" :user-id="user.user_id" :conversation-id="selectedId" @jump="jumpToRecord" @logout="logout" /></div>
      </details>
      <div ref="messageArea" class="flex-1 overflow-y-auto px-4 py-8" @scroll="trackScroll">
        <div class="mx-auto max-w-3xl">
          <button v-if="viewingRecord && selectedId" class="mb-4 w-full text-sm text-primary" @click="jumpToRecord(selectedId)">返回最新消息</button>
          <button v-if="moreMessages" :disabled="loading || busy" class="mb-6 w-full text-sm text-muted-foreground" @click="loadOlderMessages">加载更早消息</button>
          <p v-if="loading && !messages.length" class="py-12 text-center text-muted-foreground">正在加载消息…</p>
          <div v-else-if="!messages.length" class="flex min-h-64 flex-col items-center justify-center text-center"><span class="mb-5 text-4xl">✦</span><h2 class="text-2xl font-semibold tracking-tight">有什么可以帮你？</h2><p class="mt-3 text-sm text-muted-foreground">支持多轮对话，也可以说“北京时间每天早上九点查询武汉天气”。</p></div>
          <article v-for="message in messages" :id="`message-${message.id}`" :key="message.id" class="mb-8 flex scroll-mt-4 rounded-lg" :class="[message.role === 'user' ? 'justify-end' : 'justify-start', highlightedMessage === message.id ? 'ring-2 ring-primary ring-offset-4' : '']">
            <div :class="message.role === 'user' ? 'max-w-[85%] rounded-3xl bg-muted px-5 py-3' : 'w-full min-w-0'">
              <p v-if="message.role === 'assistant'" class="mb-3 text-xs font-semibold text-muted-foreground">✦ 助手</p>
              <p class="whitespace-pre-wrap break-words [overflow-wrap:anywhere] leading-7">{{ message.content || (message.status === 'generating' ? '正在思考…' : '未生成回答') }}</p>
              <p v-if="message.status !== 'completed' && message.role === 'assistant'" class="mt-2 text-xs text-muted-foreground">{{ message.status === 'generating' ? '生成中' : message.status === 'failed' ? '回答失败，可重新发送' : '已停止' }}</p>
            </div>
          </article>
        </div>
      </div>
      <footer class="shrink-0 px-4 pb-4 pt-2">
        <div class="mx-auto max-w-3xl">
          <p v-if="error" role="alert" class="mb-3 text-sm text-destructive">{{ error }}</p>
          <p v-if="notice" role="status" class="mb-3 text-sm text-muted-foreground">{{ notice }}</p>
          <p v-if="backgroundError" role="status" class="mb-3 text-sm text-destructive">{{ backgroundError }}</p>
          <form class="rounded-3xl border bg-muted/50 p-3 shadow-sm" @submit.prevent="send">
            <label for="message" class="sr-only">消息</label>
            <textarea id="message" v-model="draft" maxlength="10000" rows="2" :disabled="busy || loading || viewingRecord" placeholder="发送消息，Enter 发送，Shift + Enter 换行"
              class="w-full resize-none bg-transparent px-2 py-2 outline-none disabled:opacity-60" @keydown.enter="handleEnter" />
            <div class="flex items-center justify-between"><span class="pl-2 text-xs text-muted-foreground">{{ draft.length }}/10000</span><button v-if="busy" type="button" :disabled="stopping || !activeAssistantId" class="rounded-full border px-4 py-2 text-sm disabled:opacity-40" @click="stop">{{ stopping ? '正在停止…' : '停止生成' }}</button><button v-else :disabled="!draft.trim() || loading || viewingRecord" class="rounded-full bg-primary px-5 py-2 text-sm text-primary-foreground disabled:opacity-40">发送 ↑</button></div>
          </form>
          <p class="mt-3 text-center text-xs text-muted-foreground">AI 回答可能不准确。Demo 无密码登录，请勿输入敏感信息。</p>
        </div>
      </footer>
      </template>
    </main>
  </div>
</template>

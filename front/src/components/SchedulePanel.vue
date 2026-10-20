<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ApiError, listSchedules, listScheduleRuns, runSchedule, saveSchedule, setScheduleState } from '@/services/api'
import type { ScheduledTask, ScheduledRun, ScheduleInput } from '@/types/schedule'
import { formatTime, localTime, zonedTime } from '@/lib/time'
import { refreshVisiblePages } from '@/lib/pagination'

const props = defineProps<{ userId: string; conversationId?: string }>()
const emit = defineEmits<{ jump: [conversationId: string, messageId?: string]; logout: [] }>()
const tasks = ref<ScheduledTask[]>([])
const expanded = ref<string | null>(null)
const runs = reactive<Record<string, ScheduledRun[]>>({})
const moreRuns = reactive<Record<string, boolean>>({})
const more = ref(false)
const loading = ref(false)
const actionBusy = ref(false)
const recordsBusy = ref(false)
const error = ref('')
const notice = ref('')
const dialog = ref<HTMLDialogElement | null>(null)
const editing = ref<ScheduledTask | null>(null)
const formError = ref('')
const form = reactive({ name: '', prompt: '', kind: 'cron' as 'once' | 'cron', timezone: 'Asia/Shanghai', cron: '0 9 * * *', time: '' })
const frequency = ref('daily')
const clock = ref('09:00')
const weekday = ref('mon')
const runRequestIds = new Map<string, string>()
const controller = new AbortController()
let timer: ReturnType<typeof setInterval> | undefined

function report(failure: unknown) {
  if (controller.signal.aborted) return
  if (failure instanceof ApiError && failure.status === 401) emit('logout')
  error.value = failure instanceof Error ? failure.message : '请求失败，请稍后重试'
}

function status(value: string): string {
  return ({ active: '启用', paused: '已停止', completed: '已完成', queued: '排队中', running: '执行中', failed: '失败', cancelled: '已取消' } as Record<string, string>)[value] || value
}

async function refresh(append = false) {
  if (loading.value) return
  loading.value = true
  error.value = ''
  try {
    if (append) {
      const rows = await listSchedules(props.userId, props.conversationId, tasks.value.length, controller.signal)
      tasks.value.push(...rows)
      more.value = rows.length === 30
    } else {
      const result = await refreshVisiblePages(tasks.value.length, 30,
        offset => listSchedules(props.userId, props.conversationId, offset, controller.signal))
      tasks.value = result.rows
      more.value = result.hasMore
    }
  } catch (failure) { report(failure) }
  finally { loading.value = false }
}

async function loadRuns(taskId: string, append = false) {
  if (recordsBusy.value) return
  recordsBusy.value = true
  try {
    if (append) {
      const rows = await listScheduleRuns(props.userId, taskId, runs[taskId]?.length || 0, controller.signal)
      runs[taskId] = [...(runs[taskId] || []), ...rows]
      moreRuns[taskId] = rows.length === 20
    } else {
      // Refresh every visible page; reading older records must not freeze a running record.
      const result = await refreshVisiblePages(runs[taskId]?.length || 0, 20,
        offset => listScheduleRuns(props.userId, taskId, offset, controller.signal))
      runs[taskId] = result.rows
      moreRuns[taskId] = result.hasMore
    }
  } catch (failure) { report(failure) }
  finally { recordsBusy.value = false }
}

async function refreshPanel() {
  await refresh()
  if (expanded.value) await loadRuns(expanded.value)
}

async function toggleRecords(task: ScheduledTask) {
  expanded.value = expanded.value === task.id ? null : task.id
  if (expanded.value) await loadRuns(task.id)
}

async function openEditor(task: ScheduledTask) {
  editing.value = task
  formError.value = ''
  Object.assign(form, { name: task.name, prompt: task.prompt, kind: task.kind, timezone: task.timezone,
    cron: task.cron || '0 9 * * *', time: task.run_at ? localTime(task.run_at, task.timezone) : '' })
  const parts = form.cron.split(/\s+/)
  const simple = parts.length === 5 && /^\d+$/.test(parts[0] || '') && /^\d+$/.test(parts[1] || '') && parts[2] === '*' && parts[3] === '*'
  frequency.value = simple && parts[4] === '*' ? 'daily' : simple && /^(mon|tue|wed|thu|fri|sat|sun)$/.test(parts[4] || '') ? 'weekly' : 'custom'
  clock.value = simple ? `${parts[1]?.padStart(2, '0')}:${parts[0]?.padStart(2, '0')}` : '09:00'
  weekday.value = frequency.value === 'weekly' ? (parts[4] || 'mon') : 'mon'
  await nextTick()
  dialog.value?.showModal()
}

async function save() {
  if (actionBusy.value || !editing.value) return
  actionBusy.value = true
  formError.value = ''
  try {
    if (form.kind === 'cron' && frequency.value !== 'custom') {
      const [hour, minute] = clock.value.split(':')
      form.cron = `${Number(minute)} ${Number(hour)} * * ${frequency.value === 'weekly' ? weekday.value : '*'}`
    }
    const input: ScheduleInput = { name: form.name.trim(), prompt: form.prompt.trim(), kind: form.kind,
      timezone: form.timezone.trim(), cron: form.kind === 'cron' ? form.cron.trim() : null,
      run_at: form.kind === 'once' ? zonedTime(form.time, form.timezone.trim()) : null }
    await saveSchedule(props.userId, input, controller.signal, editing.value.id)
    dialog.value?.close()
    notice.value = '任务已保存'
    await refresh()
  } catch (failure) {
    if (failure instanceof ApiError && failure.status === 401) emit('logout')
    formError.value = failure instanceof Error ? failure.message : '保存失败，请重试'
  } finally { actionBusy.value = false }
}

async function act(task: ScheduledTask, action: 'state' | 'run') {
  if (actionBusy.value) return
  actionBusy.value = true
  error.value = ''
  notice.value = ''
  try {
    if (action === 'state') {
      await setScheduleState(props.userId, task.id, task.status === 'active' ? 'paused' : 'active', controller.signal)
      notice.value = task.status === 'active' ? '任务已停止，已经开始的执行会继续完成' : '任务已恢复'
    } else {
      const requestId = runRequestIds.get(task.id) || crypto.randomUUID()
      runRequestIds.set(task.id, requestId)
      await runSchedule(props.userId, task.id, requestId, controller.signal)
      runRequestIds.delete(task.id)
      notice.value = '运行请求已保存，等待后台执行'
      expanded.value = task.id
      await loadRuns(task.id)
    }
    await refresh()
  } catch (failure) { report(failure) }
  finally { actionBusy.value = false }
}

onMounted(() => {
  void refreshPanel()
  timer = setInterval(() => {
    if (document.hidden || actionBusy.value) return
    void refreshPanel()
  }, 5000)
})
onBeforeUnmount(() => { controller.abort(); clearInterval(timer); dialog.value?.close() })
defineExpose({ refresh: refreshPanel })
</script>

<template>
  <section aria-label="定时任务" class="min-w-0 space-y-3">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <h2 class="text-sm font-semibold">{{ conversationId ? '当前对话的定时任务' : '全部定时任务' }}</h2>
      <div class="flex gap-3 text-sm">
        <button :disabled="loading || recordsBusy" @click="refreshPanel()">{{ loading || recordsBusy ? '刷新中…' : '刷新' }}</button>
      </div>
    </div>
    <p v-if="error" role="alert" class="text-sm text-destructive">{{ error }}</p>
    <p v-if="notice" role="status" class="text-sm text-muted-foreground">{{ notice }}</p>
    <p v-if="!tasks.length && !error" class="py-3 text-sm text-muted-foreground">{{ loading ? '正在加载任务…' : conversationId ? '还没有任务，直接在对话中告诉 AI 要做什么、何时执行和时区即可。' : '还没有任务，请在对话中告诉 AI 创建定时任务。' }}</p>
    <article v-for="task in tasks" :key="task.id" class="rounded-xl border bg-background p-4">
      <div class="flex flex-wrap items-start justify-between gap-2">
        <h3 class="min-w-0 break-words font-medium">{{ task.name }}</h3>
        <span class="rounded-full bg-muted px-2 py-1 text-xs">{{ status(task.status) }}</span>
      </div>
      <p class="mt-2 line-clamp-2 whitespace-pre-wrap break-words text-sm text-muted-foreground">{{ task.prompt }}</p>
      <p class="mt-3 text-xs text-muted-foreground">{{ task.kind === 'once' ? '一次性' : `Cron：${task.cron}` }} · {{ task.timezone }}</p>
      <p class="mt-1 text-xs">下次运行：{{ formatTime(task.next_run_at, task.timezone) }}（{{ task.timezone }}）</p>
      <div class="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-sm">
        <button :disabled="actionBusy" @click="openEditor(task)">编辑任务</button>
        <button :disabled="actionBusy" @click="act(task, 'run')">立即运行</button>
        <button v-if="task.status !== 'completed'" :disabled="actionBusy" @click="act(task, 'state')">{{ task.status === 'active' ? '停止' : '恢复' }}</button>
        <button @click="emit('jump', task.conversation_id)">跳转对话 ↗</button>
        <button :aria-expanded="expanded === task.id" @click="toggleRecords(task)">{{ expanded === task.id ? '收起' : '展开' }}执行记录</button>
      </div>
      <div v-if="expanded === task.id" class="mt-4 space-y-2 border-t pt-3">
        <p v-if="!runs[task.id]?.length" class="text-xs text-muted-foreground">{{ recordsBusy ? '加载中…' : '暂无执行记录' }}</p>
        <div v-for="run in runs[task.id]" :key="run.id" class="rounded-lg bg-muted/50 p-3 text-xs">
          <button :disabled="!run.assistant_message_id" class="text-left disabled:opacity-70" @click="emit('jump', task.conversation_id, run.assistant_message_id || undefined)">
            {{ run.source === 'manual' ? '手动' : '定时' }} · {{ formatTime(run.scheduled_at, task.timezone) }} · {{ status(run.status) }}
            <span v-if="run.assistant_message_id" class="ml-2 underline">查看对话记录 ↗</span>
          </button>
          <p class="mt-1 text-muted-foreground">开始 {{ formatTime(run.started_at, task.timezone) }} · 结束 {{ formatTime(run.finished_at, task.timezone) }}</p>
          <p v-if="run.error" class="mt-1 text-destructive">{{ run.error }}</p>
          <p v-if="run.result_preview" class="mt-2 whitespace-pre-wrap break-words leading-6 [overflow-wrap:anywhere]">{{ run.result_preview }}</p>
          <p v-else-if="run.status === 'running'" class="mt-2 text-muted-foreground">后台正在执行，结果会自动更新。</p>
          <p v-else-if="run.status === 'completed'" class="mt-2 text-muted-foreground">任务已结束，未返回文本内容，可查看对话记录。</p>
          <p v-if="run.result_truncated" class="mt-1 text-muted-foreground">仅显示部分结果，点击“查看对话记录”阅读全文。</p>
        </div>
        <button v-if="moreRuns[task.id]" :disabled="recordsBusy" class="text-xs" @click="loadRuns(task.id, true)">加载更早执行记录</button>
      </div>
    </article>
    <button v-if="more" :disabled="loading" class="w-full py-2 text-sm" @click="refresh(true)">加载更多任务</button>
    <dialog ref="dialog" class="m-auto max-h-[90svh] w-[calc(100%-2rem)] max-w-lg overflow-y-auto rounded-2xl border bg-background p-6 text-foreground shadow-xl backdrop:bg-black/40" aria-labelledby="schedule-title" @cancel="actionBusy && $event.preventDefault()">
      <form class="space-y-4" @submit.prevent="save">
        <h2 id="schedule-title" class="text-lg font-semibold">编辑定时任务</h2>
        <label class="block text-sm">任务名称<input v-model="form.name" required maxlength="80" class="mt-1 w-full rounded-lg border bg-background p-2" /></label>
        <label class="block text-sm">提示词<textarea v-model="form.prompt" required maxlength="10000" rows="4" class="mt-1 w-full rounded-lg border bg-background p-2" /></label>
        <label class="block text-sm">执行方式<select v-model="form.kind" class="mt-1 w-full rounded-lg border bg-background p-2"><option value="cron">周期执行</option><option value="once">一次性执行</option></select></label>
        <label class="block text-sm">IANA 时区<input v-model="form.timezone" required placeholder="Asia/Shanghai" class="mt-1 w-full rounded-lg border bg-background p-2" /></label>
        <label v-if="form.kind === 'once'" class="block text-sm">执行时间（上述时区）<input v-model="form.time" type="datetime-local" required class="mt-1 w-full rounded-lg border bg-background p-2" /></label>
        <template v-else>
          <label class="block text-sm">执行频率<select v-model="frequency" class="mt-1 w-full rounded-lg border bg-background p-2"><option value="daily">每天</option><option value="weekly">每周</option><option value="custom">自定义 Cron</option></select></label>
          <label v-if="frequency === 'weekly'" class="block text-sm">星期<select v-model="weekday" class="mt-1 w-full rounded-lg border bg-background p-2"><option value="mon">周一</option><option value="tue">周二</option><option value="wed">周三</option><option value="thu">周四</option><option value="fri">周五</option><option value="sat">周六</option><option value="sun">周日</option></select></label>
          <label v-if="frequency !== 'custom'" class="block text-sm">执行时间（上述时区）<input v-model="clock" required type="time" class="mt-1 w-full rounded-lg border bg-background p-2" /></label>
          <label v-else class="block text-sm">Cron 表达式<input v-model="form.cron" required maxlength="120" class="mt-1 w-full rounded-lg border bg-background p-2" /><span class="mt-1 block text-xs text-muted-foreground">分 时 日 月 星期；0 9 * * * 为每天 09:00。星期使用 mon–sun。</span></label>
        </template>
        <p class="text-xs text-muted-foreground">保存对 AI 已创建任务的修改。执行结果会写入当前任务所属对话。</p>
        <p v-if="formError" role="alert" class="text-sm text-destructive">{{ formError }}</p>
        <div class="flex justify-end gap-3"><button type="button" :disabled="actionBusy" @click="dialog?.close()">取消</button><button :disabled="actionBusy" class="rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground">{{ actionBusy ? '保存中…' : '确认保存' }}</button></div>
      </form>
    </dialog>
  </section>
</template>

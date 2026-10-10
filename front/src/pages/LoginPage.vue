<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { login } from '@/services/api'
import type { User } from '@/types/chat'

const emit = defineEmits<{ login: [user: User] }>()
const account = ref('')
const busy = ref(false)
const error = ref('')
let controller: AbortController | null = null

async function submit() {
  if (busy.value || !account.value.trim()) return
  controller = new AbortController()
  busy.value = true
  error.value = ''
  try {
    const user = await login(account.value.trim(), controller.signal)
    if (!controller.signal.aborted) emit('login', user)
  } catch (failure) {
    if (!controller.signal.aborted) error.value = failure instanceof Error ? failure.message : '登录失败'
  } finally {
    busy.value = false
  }
}

onBeforeUnmount(() => controller?.abort())
</script>

<template>
  <main class="flex min-h-svh items-center justify-center bg-muted/40 px-6">
    <section class="w-full max-w-sm rounded-3xl border bg-card p-8 shadow-sm">
      <div class="mb-6 flex size-12 items-center justify-center rounded-2xl bg-primary text-2xl text-primary-foreground">✦</div>
      <h1 class="text-2xl font-semibold tracking-tight">开始你的对话</h1>
      <p class="mt-2 text-sm text-muted-foreground">输入账号即可登录，新账号会自动创建。</p>
      <form class="mt-8 space-y-4" @submit.prevent="submit">
        <label for="account" class="block text-sm font-medium">账号</label>
        <input id="account" v-model="account" maxlength="255" autocomplete="username" autofocus required :disabled="busy"
          class="w-full rounded-xl border bg-background px-4 py-3 outline-none focus-visible:ring-2 focus-visible:ring-ring" placeholder="请输入你的账号" />
        <p v-if="error" role="alert" class="text-sm text-destructive">{{ error }}</p>
        <button :disabled="busy || !account.trim()" class="w-full rounded-xl bg-primary py-3 font-medium text-primary-foreground disabled:opacity-50">
          {{ busy ? '正在登录…' : '进入对话' }}
        </button>
      </form>
      <p class="mt-6 text-xs leading-5 text-muted-foreground">仅用于 Demo：无密码登录和用户 ID 请求头不能防止他人冒用账号，请勿输入敏感信息。</p>
    </section>
  </main>
</template>

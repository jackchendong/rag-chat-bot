<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import ChatPage from '@/pages/ChatPage.vue'
import LoginPage from '@/pages/LoginPage.vue'
import { ApiError, currentUser } from '@/services/api'
import type { User } from '@/types/chat'

const user = ref<User | null>(null)
const checking = ref(true)
const error = ref('')
let controller: AbortController | null = null

function logout() {
  controller?.abort()
  user.value = null
  error.value = ''
  checking.value = false
  try {
    localStorage.removeItem('account')
    localStorage.removeItem('user_id')
  } catch {
    error.value = '浏览器限制了本地存储，请检查浏览器设置'
  }
}

function loggedIn(value: User) {
  try {
    localStorage.setItem('account', value.account)
    localStorage.setItem('user_id', value.user_id)
  } catch {
    error.value = '登录成功，但浏览器无法保存登录状态，刷新后需重新登录'
  }
  user.value = value
}

async function restore() {
  checking.value = true
  error.value = ''
  controller?.abort()
  const request = new AbortController()
  controller = request
  try {
    const identifier = localStorage.getItem('user_id')
    if (!identifier) return
    const value = await currentUser(identifier, request.signal)
    if (!request.signal.aborted) loggedIn(value)
  } catch (failure) {
    if (request.signal.aborted) return
    if (failure instanceof ApiError && failure.status === 401) logout()
    else error.value = failure instanceof Error ? failure.message : '登录状态校验失败'
  } finally {
    if (!request.signal.aborted) checking.value = false
  }
}

onMounted(() => void restore())
onBeforeUnmount(() => controller?.abort())
</script>

<template>
  <main v-if="checking" class="flex min-h-svh items-center justify-center text-muted-foreground">正在验证登录状态…</main>
  <main v-else-if="error && !user" class="flex min-h-svh flex-col items-center justify-center gap-5 px-6"><p role="alert">{{ error }}</p><button class="rounded-xl border px-5 py-2" @click="restore">重试</button><button class="text-sm text-muted-foreground" @click="logout">返回登录</button></main>
  <ChatPage v-else-if="user" :user="user" @logout="logout" />
  <LoginPage v-else @login="loggedIn" />
</template>

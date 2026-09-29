import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/api/endpoints'
import { ApiError } from '@/api/client'
import { setAuthToken } from '@/api/authtoken'

const LS_KEY = 'fusion-k12-auth'

export interface Teacher {
  id: string
  username: string
  name: string
  school: string
  region: string
  default_edition: string
  created_at: string
}

function load(): { token: string; teacher: Teacher | null } {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (raw) return JSON.parse(raw)
  } catch (e) {}
  return { token: '', teacher: null }
}

export const useAuthStore = defineStore('auth', () => {
  const init = load()
  const token = ref(init.token)
  const teacher = ref<Teacher | null>(init.teacher)
  setAuthToken(init.token)

  const isLoggedIn = computed(() => !!token.value && !!teacher.value)

  function persist() {
    localStorage.setItem(LS_KEY, JSON.stringify({ token: token.value, teacher: teacher.value }))
  }

  async function login(username: string, password: string): Promise<void> {
    const r = await authApi.login({ username, password })
    token.value = r.token
    teacher.value = r.teacher
    setAuthToken(r.token)
    persist()
  }

  async function register(body: {
    username: string; password: string; name: string
    school: string; region: string; default_edition: string
  }): Promise<void> {
    await authApi.register(body)
    await login(body.username, body.password)
  }

  async function fetchMe(): Promise<void> {
    if (!token.value) return
    try {
      const r = await authApi.me()
      teacher.value = r.teacher
      persist()
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        clear()
      }
    }
  }

  async function logout(): Promise<void> {
    try {
      if (token.value) await authApi.logout()
    } catch (e) {}
    clear()
  }

  function clear() {
    token.value = ''
    teacher.value = null
    setAuthToken('')
    localStorage.removeItem(LS_KEY)
  }

  return { token, teacher, isLoggedIn, login, register, fetchMe, logout, clear }
})

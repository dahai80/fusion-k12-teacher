import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

const LS_KEY = 'fusion-k12-settings'

export interface Settings {
  backendUrl: string
  apiKey: string
}

function load(): Settings {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (raw) return JSON.parse(raw)
  } catch (e) {}
  return { backendUrl: '', apiKey: '' }
}

export const useSettingsStore = defineStore('settings', () => {
  const init = load()
  // 子路径部署感知: /fusion/ 反代下 origin 是站点根, API 必须跟随页面子路径
  // (window.location.origin 会打到 linguakids 的 /api/* → 404 "后端不可达")
  const basePath = window.location.pathname.replace(/\/[^/]*$/, '')
  const backendUrl = ref(init.backendUrl || (basePath && basePath !== '/' ? window.location.origin + basePath : window.location.origin))
  const apiKey = ref(init.apiKey || 'k12-test-key')

  watch([backendUrl, apiKey], () => {
    localStorage.setItem(LS_KEY, JSON.stringify({ backendUrl: backendUrl.value, apiKey: apiKey.value }))
  })

  return { backendUrl, apiKey }
})

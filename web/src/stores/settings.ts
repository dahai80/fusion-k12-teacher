import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { inShell } from '@/shell'

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
  const sameOrigin = basePath && basePath !== '/' ? window.location.origin + basePath : window.location.origin
  // issue #30: shell 嵌入态走网关同源代理 /shell/fusion-k12-teacher/ —
  // 忽略 localStorage 旧值 (standalone 时代的 :5174/自定义地址在 iframe 里不可达),
  // 也不回写, 避免污染 standalone 配置
  const embedded = inShell()
  const backendUrl = ref(embedded ? sameOrigin : (init.backendUrl || sameOrigin))
  const apiKey = ref(init.apiKey || 'k12-test-key')

  if (!embedded) {
    watch([backendUrl, apiKey], () => {
      localStorage.setItem(LS_KEY, JSON.stringify({ backendUrl: backendUrl.value, apiKey: apiKey.value }))
    })
  }

  return { backendUrl, apiKey }
})

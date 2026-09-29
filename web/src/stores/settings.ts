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
  const backendUrl = ref(init.backendUrl || window.location.origin)
  const apiKey = ref(init.apiKey || 'k12-test-key')

  watch([backendUrl, apiKey], () => {
    localStorage.setItem(LS_KEY, JSON.stringify({ backendUrl: backendUrl.value, apiKey: apiKey.value }))
  })

  return { backendUrl, apiKey }
})

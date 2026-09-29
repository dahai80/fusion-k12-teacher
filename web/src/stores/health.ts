import { defineStore } from 'pinia'
import { ref } from 'vue'
import { healthApi } from '@/api/endpoints'

export const useHealthStore = defineStore('health', () => {
  const status = ref<'unknown' | 'ok' | 'down'>('unknown')
  const model = ref('')
  const ready = ref(false)
  const lastError = ref('')

  async function poll() {
    try {
      const r = await healthApi.health()
      status.value = 'ok'
      model.value = r.model || ''
      ready.value = !!r.ready
      lastError.value = ''
    } catch (e: any) {
      status.value = 'down'
      ready.value = false
      lastError.value = e?.message || String(e)
    }
  }

  return { status, model, ready, lastError, poll }
})

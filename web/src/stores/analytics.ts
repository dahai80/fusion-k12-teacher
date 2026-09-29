import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

const LS_KEY = 'fusion-k12-data-path'

export const useAnalyticsStore = defineStore('analytics', () => {
  const dataPath = ref(localStorage.getItem(LS_KEY) || '')

  watch(dataPath, () => {
    if (dataPath.value) localStorage.setItem(LS_KEY, dataPath.value)
    else localStorage.removeItem(LS_KEY)
  })

  function clear() { dataPath.value = '' }

  return { dataPath, clear }
})

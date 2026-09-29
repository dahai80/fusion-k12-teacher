import { ref } from 'vue'
import { useMessage } from 'naive-ui'
import { ApiError } from '@/api/client'

export interface EngineResult {
  error?: string
  [k: string]: any
}

export function useGenerator<T extends EngineResult = EngineResult>() {
  const loading = ref(false)
  const result = ref<T | null>(null)
  const errorMsg = ref('')
  const message = useMessage()

  async function run(fn: () => Promise<T>): Promise<T | null> {
    loading.value = true
    errorMsg.value = ''
    result.value = null
    try {
      const r = await fn()
      result.value = r
      if (r && r.error) {
        errorMsg.value = r.error
        message.warning('生成完成但引擎降级: ' + r.error)
      } else {
        message.success('生成成功')
      }
      return r
    } catch (e: any) {
      if (e instanceof ApiError) {
        const d = e.body?.detail
        if (typeof d === 'string') {
          errorMsg.value = d
        } else if (Array.isArray(d) && d.length) {
          errorMsg.value = d.map((x: any) => x?.msg || JSON.stringify(x)).join('; ')
        } else {
          errorMsg.value = e.message
        }
      } else {
        errorMsg.value = e?.message || String(e)
      }
      message.error('生成失败: ' + errorMsg.value)
      return null
    } finally {
      loading.value = false
    }
  }

  function reset() {
    result.value = null
    errorMsg.value = ''
  }

  return { loading, result, errorMsg, run, reset }
}

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { NCard, NSpace, NForm, NFormItem, NInput, NButton, useMessage } from 'naive-ui'
import { personalizationApi } from '@/api/endpoints'
import { useGenerator } from '@/composables/useGenerator'
import { useAuthStore } from '@/stores/auth'
import { useTextbookCtx } from '@/composables/useTextbookCtx'
import ResultViewer from '@/components/ResultViewer.vue'
import HistoryPanel from '@/components/HistoryPanel.vue'

const form = reactive({ records: '' })
const gen = useGenerator()
const auth = useAuthStore()
const message = useMessage()
const { fields } = useTextbookCtx()
const hist = ref<any>(null)

function onHistory(p: any) { gen.result.value = p; gen.errorMsg.value = '' }

async function generate() {
  const responses = form.records.split(/[,\n]/).map(s => s.trim()).filter(Boolean).map((v, i) => ({ item: i + 1, score: Number(v) || 0 }))
  await gen.run(() => personalizationApi.diagnose({
    ...fields(), responses,
  }))
  if (gen.result.value && !gen.result.value.error) {
    hist.value?.refresh()
    if (auth.isLoggedIn) message.info('已保存到资源库 (我的资源库可查看)')
  }
}
</script>
<template>
  <n-card title="技能诊断" size="small">
    <n-form label-placement="left" :show-feedback="false" size="small">
      <n-space>
        <n-button type="primary" :loading="gen.loading.value" @click="generate">诊断</n-button>
      </n-space>
      <n-form-item label="答题记录" style="margin-top: 12px"><n-input v-model:value="form.records" type="textarea" :rows="4" placeholder="粘贴答题记录, JSON 或文本" /></n-form-item>
    </n-form>
    <ResultViewer :loading="gen.loading.value" :result="gen.result.value" :error="gen.errorMsg.value" @retry="generate" />
    <history-panel ref="hist" type="diagnose" @load="onHistory" />
  </n-card>
</template>

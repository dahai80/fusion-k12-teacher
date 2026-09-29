<script setup lang="ts">
import { reactive, ref } from 'vue'
import { NCard, NSpace, NForm, NFormItem, NInput, NButton, useMessage } from 'naive-ui'
import { assessmentApi } from '@/api/endpoints'
import { useGenerator } from '@/composables/useGenerator'
import { useAuthStore } from '@/stores/auth'
import { useTextbookCtx } from '@/composables/useTextbookCtx'
import ResultViewer from '@/components/ResultViewer.vue'
import HistoryPanel from '@/components/HistoryPanel.vue'

const form = reactive({ student_name: '', grade_records: '' })
const gen = useGenerator()
const auth = useAuthStore()
const message = useMessage()
const { fields } = useTextbookCtx()
const hist = ref<any>(null)

function onHistory(p: any) { gen.result.value = p; gen.errorMsg.value = '' }

async function generate() {
  const records = form.grade_records.split(/[,\n]/).map(s => s.trim()).filter(Boolean).map((v, i) => ({ item: i + 1, score: Number(v) || 0 }))
  await gen.run(() => assessmentApi.report({
    student: form.student_name, ...fields(), history: records,
  }))
  if (gen.result.value && !gen.result.value.error) {
    hist.value?.refresh()
    if (auth.isLoggedIn) message.info('已保存到资源库 (我的资源库可查看)')
  }
}
</script>
<template>
  <n-card title="生成学生报告" size="small">
    <n-form label-placement="left" :show-feedback="false" size="small">
      <n-space>
        <n-form-item label="学生"><n-input v-model:value="form.student_name" style="width: 140px" /></n-form-item>
        <n-button type="primary" :loading="gen.loading.value" @click="generate">生成</n-button>
      </n-space>
      <n-form-item label="成绩记录" style="margin-top: 12px">
        <n-input v-model:value="form.grade_records" type="textarea" :rows="3" placeholder="JSON 或逗号分隔, 如 90,85,92" />
      </n-form-item>
    </n-form>
    <ResultViewer :loading="gen.loading.value" :result="gen.result.value" :error="gen.errorMsg.value" @retry="generate" />
    <history-panel ref="hist" type="report" @load="onHistory" />
  </n-card>
</template>

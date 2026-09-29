<script setup lang="ts">
import { reactive, ref } from 'vue'
import { NCard, NSpace, NForm, NFormItem, NInput, NSelect, NButton, useMessage } from 'naive-ui'
import { personalizationApi } from '@/api/endpoints'
import { useGenerator } from '@/composables/useGenerator'
import { useAuthStore } from '@/stores/auth'
import { useTextbookCtx } from '@/composables/useTextbookCtx'
import ResultViewer from '@/components/ResultViewer.vue'
import HistoryPanel from '@/components/HistoryPanel.vue'

const form = reactive({ student_name: '', current_level: 'medium' })
const gen = useGenerator()
const auth = useAuthStore()
const message = useMessage()
const { ctx, fields } = useTextbookCtx()
const hist = ref<any>(null)

function onHistory(p: any) { gen.result.value = p; gen.errorMsg.value = '' }

async function generate() {
  const goal = form.current_level === 'advanced' ? '拓展提升' : form.current_level === 'basic' ? '基础巩固' : '综合提升'
  await gen.run(() => personalizationApi.path({
    student_id: form.student_name,
    progress: { student: form.student_name, grade: String(ctx.grade), subject: ctx.subject, goal },
    ...fields(),
  }))
  if (gen.result.value && !gen.result.value.error) {
    hist.value?.refresh()
    if (auth.isLoggedIn) message.info('已保存到资源库 (我的资源库可查看)')
  }
}
</script>
<template>
  <n-card title="个性化学习路径" size="small">
    <n-form label-placement="left" :show-feedback="false" size="small">
      <n-space>
        <n-form-item label="学生"><n-input v-model:value="form.student_name" style="width: 140px" /></n-form-item>
        <n-form-item label="水平"><n-select v-model:value="form.current_level" :options="[{label:'基础',value:'basic'},{label:'中等',value:'medium'},{label:'拔高',value:'advanced'}]" style="width: 100px" /></n-form-item>
        <n-button type="primary" :loading="gen.loading.value" @click="generate">生成</n-button>
      </n-space>
    </n-form>
    <ResultViewer :loading="gen.loading.value" :result="gen.result.value" :error="gen.errorMsg.value" @retry="generate" />
    <history-panel ref="hist" type="path" @load="onHistory" />
  </n-card>
</template>

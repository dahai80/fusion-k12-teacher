<script setup lang="ts">
import { reactive, ref } from 'vue'
import { NCard, NSpace, NForm, NFormItem, NInput, NButton, useMessage } from 'naive-ui'
import { personalizationApi } from '@/api/endpoints'
import { useGenerator } from '@/composables/useGenerator'
import { useAuthStore } from '@/stores/auth'
import { useTextbookCtx } from '@/composables/useTextbookCtx'
import ResultViewer from '@/components/ResultViewer.vue'
import HistoryPanel from '@/components/HistoryPanel.vue'

const form = reactive({ student_name: '', weak_points: '', interest: '' })
const gen = useGenerator()
const auth = useAuthStore()
const message = useMessage()
const { fields } = useTextbookCtx()
const hist = ref<any>(null)

function onHistory(p: any) { gen.result.value = p; gen.errorMsg.value = '' }

async function generate() {
  await gen.run(() => personalizationApi.recommend({
    student: form.student_name, ...fields(), weakness: form.weak_points,
  }))
  if (gen.result.value && !gen.result.value.error) {
    hist.value?.refresh()
    if (auth.isLoggedIn) message.info('已保存到资源库 (我的资源库可查看)')
  }
}
</script>
<template>
  <n-card title="资源推荐" size="small">
    <n-form label-placement="left" :show-feedback="false" size="small">
      <n-space>
        <n-form-item label="学生"><n-input v-model:value="form.student_name" style="width: 140px" /></n-form-item>
        <n-button type="primary" :loading="gen.loading.value" @click="generate">推荐</n-button>
      </n-space>
      <n-form-item label="薄弱点" style="margin-top: 12px"><n-input v-model:value="form.weak_points" type="textarea" :rows="2" placeholder="逗号分隔" /></n-form-item>
      <n-form-item label="兴趣" style="margin-top: 8px"><n-input v-model:value="form.interest" /></n-form-item>
    </n-form>
    <ResultViewer :loading="gen.loading.value" :result="gen.result.value" :error="gen.errorMsg.value" @retry="generate" />
    <history-panel ref="hist" type="recommend" @load="onHistory" />
  </n-card>
</template>

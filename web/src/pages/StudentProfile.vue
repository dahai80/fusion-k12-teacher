<script setup lang="ts">
import { reactive, ref } from 'vue'
import { NCard, NSpace, NForm, NFormItem, NInput, NButton, NAlert, useMessage } from 'naive-ui'
import { analyticsApi } from '@/api/endpoints'
import { useAnalyticsStore } from '@/stores/analytics'
import { useGenerator } from '@/composables/useGenerator'
import { useAuthStore } from '@/stores/auth'
import { useTextbookCtx } from '@/composables/useTextbookCtx'
import ResultViewer from '@/components/ResultViewer.vue'
import HistoryPanel from '@/components/HistoryPanel.vue'

const analytics = useAnalyticsStore()
const auth = useAuthStore()
const message = useMessage()
const { fields } = useTextbookCtx()
const form = reactive({ student_id: '' })
const gen = useGenerator()
const hist = ref<any>(null)

function onHistory(p: any) { gen.result.value = p; gen.errorMsg.value = '' }

async function generate() {
    await gen.run(() => analyticsApi.studentProfile({
        student_id: form.student_id, ...fields(), data_path: analytics.dataPath,
    }))
    if (gen.result.value && !gen.result.value.error) {
        hist.value?.refresh()
        if (auth.isLoggedIn) message.info('已保存到资源库 (我的资源库可查看)')
    }
}
</script>
<template>
  <n-card title="学生个体画像" size="small">
    <n-alert v-if="!analytics.dataPath" type="info" style="margin-bottom: 12px">请先上传数据集</n-alert>
    <n-form label-placement="left" :show-feedback="false" size="small">
      <n-space>
        <n-form-item label="学生 ID"><n-input v-model:value="form.student_id" style="width: 180px" /></n-form-item>
        <n-button type="primary" :disabled="!analytics.dataPath" :loading="gen.loading.value" @click="generate">生成</n-button>
      </n-space>
    </n-form>
    <ResultViewer :loading="gen.loading.value" :result="gen.result.value" :error="gen.errorMsg.value" @retry="generate" />
    <history-panel ref="hist" type="student_profile" @load="onHistory" />
  </n-card>
</template>

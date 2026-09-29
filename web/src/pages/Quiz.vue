<script setup lang="ts">
import { reactive, ref } from 'vue'
import { NCard, NSpace, NForm, NFormItem, NSelect, NInputNumber, NButton, useMessage } from 'naive-ui'
import { curriculumApi } from '@/api/endpoints'
import { useGenerator } from '@/composables/useGenerator'
import { useAuthStore } from '@/stores/auth'
import { useTextbookCtx } from '@/composables/useTextbookCtx'
import UnitLessonSelect from '@/components/UnitLessonSelect.vue'
import ResultViewer from '@/components/ResultViewer.vue'
import HistoryPanel from '@/components/HistoryPanel.vue'

const form = reactive({ num_questions: 10, difficulty: 'medium' })
const gen = useGenerator()
const auth = useAuthStore()
const message = useMessage()
const { ctx, fields } = useTextbookCtx()
const hist = ref<any>(null)
const diffs = [{ label: '基础', value: 'easy' }, { label: '中等', value: 'medium' }, { label: '拔高', value: 'hard' }]

function onHistory(p: any) { gen.result.value = p; gen.errorMsg.value = '' }

async function generate() {
    await gen.run(() => curriculumApi.quiz({ ...form, ...fields(), topic: ctx.topic }))
    if (gen.result.value && !gen.result.value.error) {
        hist.value?.refresh()
        if (auth.isLoggedIn) message.info('已保存到资源库 (我的资源库可查看)')
    }
}
</script>
<template>
  <n-card title="生成测验" size="small">
    <n-form label-placement="left" :show-feedback="false" size="small">
      <n-form-item label="课题" style="margin-bottom: 12px">
        <unit-lesson-select />
      </n-form-item>
      <n-space>
        <n-form-item label="题数"><n-input-number v-model:value="form.num_questions" :min="1" :max="30" style="width: 90px" /></n-form-item>
        <n-form-item label="难度"><n-select v-model:value="form.difficulty" :options="diffs" style="width: 100px" /></n-form-item>
        <n-button type="primary" :loading="gen.loading.value" :disabled="!ctx.lesson_id" @click="generate">生成</n-button>
      </n-space>
    </n-form>
    <ResultViewer :loading="gen.loading.value" :result="gen.result.value" :error="gen.errorMsg.value" @retry="generate" />
    <history-panel ref="hist" type="quiz" @load="onHistory" />
  </n-card>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { NCard, NSpace, NForm, NFormItem, NSelect, NInputNumber, NButton, NTabs, NTabPane, useMessage } from 'naive-ui'
import { curriculumApi, contentApi } from '@/api/endpoints'
import { useGenerator } from '@/composables/useGenerator'
import { useAuthStore } from '@/stores/auth'
import { useTextbookCtx } from '@/composables/useTextbookCtx'
import UnitLessonSelect from '@/components/UnitLessonSelect.vue'
import ResultViewer from '@/components/ResultViewer.vue'
import HistoryPanel from '@/components/HistoryPanel.vue'

const form = reactive({
    layers: 'ABC', assignment_type: '', worksheet_type: '', num_questions: 10,
})
const gen = useGenerator()
const auth = useAuthStore()
const message = useMessage()
const { ctx, fields } = useTextbookCtx()
const hist = ref<any>(null)

function onHistory(p: any) { gen.result.value = p; gen.errorMsg.value = '' }

function notifySave() {
    if (gen.result.value && !gen.result.value.error) {
        hist.value?.refresh()
        if (auth.isLoggedIn) message.info('已保存到资源库 (我的资源库可查看)')
    }
}

async function planDiff() {
    await gen.run(() => curriculumApi.planDiff({ ...form, ...fields(), topic: ctx.topic }))
    notifySave()
}
async function quizDiff() {
    await gen.run(() => curriculumApi.quizDiff({ ...form, ...fields(), topic: ctx.topic, num_questions: form.num_questions }))
    notifySave()
}
async function wsDiff() {
    await gen.run(() => contentApi.worksheetDiff({ ...form, ...fields(), topic: ctx.topic, num_questions: form.num_questions }))
    notifySave()
}
</script>
<template>
  <n-card title="一键分层 (差异化教学)" size="small">
    <n-form label-placement="left" :show-feedback="false" size="small">
      <n-form-item label="课题" style="margin-bottom: 12px">
        <unit-lesson-select />
      </n-form-item>
      <n-space>
        <n-form-item label="分层"><n-select v-model:value="form.layers" :options="[{label:'A 基础',value:'A'},{label:'B 进阶',value:'B'},{label:'C 拔高',value:'C'},{label:'ABC 全层',value:'ABC'}]" style="width: 120px" /></n-form-item>
        <n-form-item label="题数"><n-input-number v-model:value="form.num_questions" :min="1" :max="30" style="width: 90px" /></n-form-item>
      </n-space>
    </n-form>
    <n-tabs type="line" animated style="margin-top: 12px">
      <n-tab-pane name="plan" tab="分层教案"><n-button type="primary" size="small" :loading="gen.loading.value" :disabled="!ctx.lesson_id" @click="planDiff">生成分层教案</n-button></n-tab-pane>
      <n-tab-pane name="quiz" tab="分层测验"><n-button type="primary" size="small" :loading="gen.loading.value" :disabled="!ctx.lesson_id" @click="quizDiff">生成分层测验</n-button></n-tab-pane>
      <n-tab-pane name="ws" tab="分层工作纸"><n-button type="primary" size="small" :loading="gen.loading.value" :disabled="!ctx.lesson_id" @click="wsDiff">生成分层工作纸</n-button></n-tab-pane>
    </n-tabs>
    <ResultViewer :loading="gen.loading.value" :result="gen.result.value" :error="gen.errorMsg.value" @retry="planDiff" />
    <history-panel ref="hist" :type="['diff_lesson','diff_quiz','diff_worksheet']" @load="onHistory" />
  </n-card>
</template>

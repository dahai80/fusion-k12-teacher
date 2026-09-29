<script setup lang="ts">
import { reactive, ref } from 'vue'
import { NCard, NSpace, NForm, NFormItem, NInputNumber, NButton, useMessage } from 'naive-ui'
import { curriculumApi } from '@/api/endpoints'
import { useGenerator } from '@/composables/useGenerator'
import { useAuthStore } from '@/stores/auth'
import { useTextbookCtx } from '@/composables/useTextbookCtx'
import UnitLessonSelect from '@/components/UnitLessonSelect.vue'
import ResultViewer from '@/components/ResultViewer.vue'
import HistoryPanel from '@/components/HistoryPanel.vue'

const form = reactive({ weeks: 2 })
const gen = useGenerator()
const auth = useAuthStore()
const message = useMessage()
const { ctx, fields } = useTextbookCtx()
const hist = ref<any>(null)

function onHistory(p: any) { gen.result.value = p; gen.errorMsg.value = '' }

async function generate() {
    await gen.run(() => curriculumApi.unitPlan({ ...form, ...fields(), unit_title: ctx.unit_title, weeks: form.weeks }))
    if (gen.result.value && !gen.result.value.error) {
        hist.value?.refresh()
        if (auth.isLoggedIn) message.info('已保存到资源库 (我的资源库可查看)')
    }
}
</script>
<template>
  <n-card title="单元计划" size="small">
    <n-form label-placement="left" :show-feedback="false" size="small">
      <n-form-item label="单元" style="margin-bottom: 12px">
        <unit-lesson-select />
      </n-form-item>
      <n-space>
        <n-form-item label="周数"><n-input-number v-model:value="form.weeks" :min="1" :max="8" style="width: 100px" /></n-form-item>
        <n-button type="primary" :loading="gen.loading.value" :disabled="!ctx.unit" @click="generate">生成</n-button>
      </n-space>
    </n-form>
    <ResultViewer :loading="gen.loading.value" :result="gen.result.value" :error="gen.errorMsg.value" @retry="generate" />
    <history-panel ref="hist" type="unit_plan" @load="onHistory" />
  </n-card>
</template>

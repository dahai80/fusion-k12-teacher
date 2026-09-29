<script setup lang="ts">
import { reactive } from 'vue'
import { NCard, NSpace, NForm, NFormItem, NInput, NInputNumber, NButton } from 'naive-ui'
import { assessmentApi } from '@/api/endpoints'
import { useGenerator } from '@/composables/useGenerator'
import ResultViewer from '@/components/ResultViewer.vue'

const form = reactive({ question: '', student_answer: '', grade: '5', expected_answer: '' })
const gen = useGenerator()
async function grade() { await gen.run(() => assessmentApi.grade({ question: form.question, answer: form.student_answer, standard: form.expected_answer, grade: String(form.grade) })) }
</script>
<template>
  <n-card title="数学批改" size="small">
    <n-form label-placement="left" :show-feedback="false" size="small">
      <n-form-item label="题目"><n-input v-model:value="form.question" type="textarea" :rows="2" /></n-form-item>
      <n-space style="margin-top: 12px">
        <n-form-item label="学生答案"><n-input v-model:value="form.student_answer" style="width: 240px" /></n-form-item>
        <n-form-item label="参考答案"><n-input v-model:value="form.expected_answer" style="width: 240px" placeholder="可选" /></n-form-item>
        <n-form-item label="年级"><n-input-number v-model:value="form.grade" :min="1" :max="12" style="width: 90px" /></n-form-item>
        <n-button type="primary" :loading="gen.loading.value" @click="grade">批改</n-button>
      </n-space>
    </n-form>
    <ResultViewer :loading="gen.loading.value" :result="gen.result.value" :error="gen.errorMsg.value" @retry="grade" />
  </n-card>
</template>

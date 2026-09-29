<script setup lang="ts">
import { reactive } from 'vue'
import { NCard, NSpace, NForm, NFormItem, NInput, NInputNumber, NButton } from 'naive-ui'
import { assessmentApi } from '@/api/endpoints'
import { useGenerator } from '@/composables/useGenerator'
import ResultViewer from '@/components/ResultViewer.vue'

const form = reactive({ essay: '', grade: '5', prompt: '', rubric: '' })
const gen = useGenerator()
async function grade() { await gen.run(() => assessmentApi.essay({ ...form })) }
</script>
<template>
  <n-card title="作文批改" size="small">
    <n-form label-placement="left" :show-feedback="false" size="small">
      <n-form-item label="题目要求"><n-input v-model:value="form.prompt" /></n-form-item>
      <n-form-item label="学生作文" style="margin-top: 8px"><n-input v-model:value="form.essay" type="textarea" :rows="6" /></n-form-item>
      <n-space style="margin-top: 12px">
        <n-form-item label="年级"><n-input-number v-model:value="form.grade" :min="1" :max="12" style="width: 90px" /></n-form-item>
        <n-form-item label="量表"><n-input v-model:value="form.rubric" placeholder="可选" style="width: 200px" /></n-form-item>
        <n-button type="primary" :loading="gen.loading.value" @click="grade">批改</n-button>
      </n-space>
    </n-form>
    <ResultViewer :loading="gen.loading.value" :result="gen.result.value" :error="gen.errorMsg.value" @retry="grade" />
  </n-card>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { NCard, NSpace, NForm, NFormItem, NInput, NButton, NDataTable, NTag, NPopconfirm, useMessage } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { safetyApi } from '@/api/endpoints'
import { useGenerator } from '@/composables/useGenerator'
import ResultViewer from '@/components/ResultViewer.vue'
import { h } from 'vue'

const message = useMessage()
const form = reactive({ text: '', filter_level: 'standard' })
const gen = useGenerator()
const words = ref<string[]>([])
const newWord = ref('')

const wordCols: DataTableColumns<string> = [
  { title: '敏感词', key: 'word', render: (w) => w },
  { title: '操作', key: 'op', width: 100, render: (w) => h(NPopconfirm, { onPositiveClick: () => removeWord(w) }, { default: () => '删除?', trigger: () => h(NButton, { size: 'tiny', type: 'error', quaternary: true }, { default: () => '删' }) }) },
]

async function loadWords() { try { const r = await safetyApi.sensitiveWords(); words.value = r?.words || [] } catch {} }
async function check() { await gen.run(() => safetyApi.checkText({ ...form })) }
async function addWord() {
  if (!newWord.value) return
  try { await safetyApi.addWord({ word: newWord.value }); message.success('已添加'); newWord.value = ''; await loadWords() }
  catch (e: any) { message.error('失败: ' + (e?.message || e)) }
}
async function removeWord(w: string) {
  try { await safetyApi.removeWord(w); message.success('已删除'); await loadWords() }
  catch (e: any) { message.error('失败: ' + (e?.message || e)) }
}
onMounted(loadWords)
</script>
<template>
  <n-space vertical>
    <n-card title="内容安检" size="small">
      <n-form label-placement="left" :show-feedback="false" size="small">
        <n-form-item label="待检文本"><n-input v-model:value="form.text" type="textarea" :rows="3" /></n-form-item>
        <n-space style="margin-top: 12px">
          <n-button type="primary" :loading="gen.loading.value" @click="check">检测</n-button>
        </n-space>
      </n-form>
      <ResultViewer :loading="gen.loading.value" :result="gen.result.value" :error="gen.errorMsg.value" @retry="check" />
    </n-card>
    <n-card title="敏感词库管理" size="small">
      <n-space style="margin-bottom: 12px">
        <n-input v-model:value="newWord" placeholder="新敏感词" size="small" style="width: 180px" />
        <n-button size="small" type="primary" @click="addWord">添加</n-button>
        <n-button size="small" @click="loadWords">刷新</n-button>
      </n-space>
      <n-data-table :columns="wordCols" :data="words" size="small" />
    </n-card>
  </n-space>
</template>

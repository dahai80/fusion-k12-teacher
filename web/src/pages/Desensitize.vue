<script setup lang="ts">
import { reactive } from 'vue'
import { NCard, NSpace, NForm, NFormItem, NInput, NSelect, NButton, NTabs, NTabPane } from 'naive-ui'
import { desensitizeApi } from '@/api/endpoints'
import { useGenerator } from '@/composables/useGenerator'
import ResultViewer from '@/components/ResultViewer.vue'

const form = reactive({ records: '', name_mode: 'id', fields_to_mask: 'phone,id_card' })
const gen = useGenerator()
async function anonymize() { await gen.run(() => desensitizeApi.anonymize({ records: form.records, config: { name_mode: form.name_mode, fields_to_mask: form.fields_to_mask.split(',') } })) }
async function deanonymize() { await gen.run(() => desensitizeApi.deanonymize({ records: form.records })) }
async function exportData() { await gen.run(() => desensitizeApi.export({ records: form.records, config: { name_mode: form.name_mode } })) }
</script>
<template>
  <n-card title="数据隐私 (匿名化/还原/脱敏导出)" size="small">
    <n-form label-placement="left" :show-feedback="false" size="small">
      <n-form-item label="记录 (JSON)"><n-input v-model:value="form.records" type="textarea" :rows="4" placeholder='[{"name":"张三","phone":"13800138000"}]' /></n-form-item>
      <n-space style="margin-top: 12px">
        <n-form-item label="姓名模式"><n-select v-model:value="form.name_mode" :options="[{label:'ID 替换',value:'id'},{label:'掩码',value:'mask'}]" style="width: 120px" /></n-form-item>
        <n-form-item label="脱敏字段"><n-input v-model:value="form.fields_to_mask" style="width: 200px" /></n-form-item>
      </n-space>
    </n-form>
    <n-tabs type="line" animated style="margin-top: 12px">
      <n-tab-pane name="anon" tab="匿名化"><n-button type="primary" size="small" :loading="gen.loading.value" @click="anonymize">匿名化</n-button></n-tab-pane>
      <n-tab-pane name="de" tab="还原"><n-button type="primary" size="small" :loading="gen.loading.value" @click="deanonymize">还原</n-button></n-tab-pane>
      <n-tab-pane name="exp" tab="脱敏导出"><n-button type="primary" size="small" :loading="gen.loading.value" @click="exportData">导出</n-button></n-tab-pane>
    </n-tabs>
    <ResultViewer :loading="gen.loading.value" :result="gen.result.value" :error="gen.errorMsg.value" @retry="anonymize" />
  </n-card>
</template>

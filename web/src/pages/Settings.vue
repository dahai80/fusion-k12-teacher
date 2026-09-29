<script setup lang="ts">
import { reactive, ref } from 'vue'
import { NCard, NSpace, NForm, NFormItem, NInput, NButton, NDivider, NCode, NDescriptions, NDescriptionsItem } from 'naive-ui'
import { useSettingsStore } from '@/stores/settings'
import { useHealthStore } from '@/stores/health'
import { metricsApi } from '@/api/endpoints'

const settings = useSettingsStore()
const health = useHealthStore()
const form = reactive({ backendUrl: settings.backendUrl, apiKey: settings.apiKey })
const metrics = ref<any>(null)
const audit = ref<any>(null)

function save() {
  settings.backendUrl = form.backendUrl
  settings.apiKey = form.apiKey
}
async function loadMetrics() { try { metrics.value = await metricsApi.metrics() } catch (e: any) { metrics.value = { error: e?.message } } }
async function loadAudit() { try { audit.value = await metricsApi.audit() } catch (e: any) { audit.value = { error: e?.message } } }
</script>
<template>
  <n-space vertical>
    <n-card title="连接设置" size="small">
      <n-form label-placement="left" :show-feedback="false" size="small">
        <n-form-item label="后端地址"><n-input v-model:value="form.backendUrl" placeholder="http://127.0.0.1:11448" /></n-form-item>
        <n-form-item label="API Key" style="margin-top: 8px"><n-input v-model:value="form.apiKey" type="password" show-password-on="click" /></n-form-item>
        <n-space style="margin-top: 12px">
          <n-button type="primary" @click="save">保存</n-button>
          <n-button @click="health.poll()">测试连接</n-button>
        </n-space>
      </n-form>
    </n-card>
    <n-card title="系统" size="small">
      <n-descriptions label-placement="left" :column="2" size="small" bordered>
        <n-descriptions-item label="状态">{{ health.status }}</n-descriptions-item>
        <n-descriptions-item label="模型">{{ health.model || '-' }}</n-descriptions-item>
        <n-descriptions-item label="就绪">{{ health.ready ? '是' : '否' }}</n-descriptions-item>
        <n-descriptions-item label="错误">{{ health.lastError || '-' }}</n-descriptions-item>
      </n-descriptions>
      <n-divider />
      <n-space>
        <n-button size="small" @click="loadMetrics">加载指标</n-button>
        <n-button size="small" @click="loadAudit">加载审计</n-button>
      </n-space>
      <n-code v-if="metrics" :code="JSON.stringify(metrics, null, 2)" language="json" style="margin-top: 12px" />
      <n-code v-if="audit" :code="JSON.stringify(audit, null, 2)" language="json" style="margin-top: 12px" />
    </n-card>
  </n-space>
</template>

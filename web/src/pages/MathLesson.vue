<script setup lang="ts">
import { reactive, ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NCard, NSpace, NForm, NFormItem, NInput, NSelect, NInputNumber, NButton, NTag, NSteps, NStep, NCollapse, NCollapseItem, NCode, NEmpty, NAlert } from 'naive-ui'
import { useSettingsStore } from '@/stores/settings'

const settings = useSettingsStore()
const route = useRoute()
const router = useRouter()
const form = reactive({ subject: 'math', topic: '火车过桥', grade: '5', misconceptions: '', prerequisites: '', layer: 'B' })
const loading = ref(false)
const stage = ref('')
const thinking = ref('')
const dsl = ref<any>(null)
const errorMsg = ref('')
let ws: WebSocket | null = null

function wsUrl(): string {
  const base = settings.backendUrl.replace(/^http/, 'ws').replace(/\/$/, '')
  return `${base}/ws/socratic-dsl`
}

function generate() {
  loading.value = true
  thinking.value = ''
  stage.value = ''
  dsl.value = null
  errorMsg.value = ''
  try {
    ws = new WebSocket(wsUrl())
  } catch (e: any) {
    errorMsg.value = 'WS 连接失败: ' + e.message
    loading.value = false
    return
  }
  ws.onopen = () => {
    ws!.send(JSON.stringify({
      subject: form.subject, topic: form.topic, grade: String(form.grade),
      misconceptions: form.misconceptions ? form.misconceptions.split(/[,，]/).map((s: string) => s.trim()).filter(Boolean) : null,
      prerequisites: form.prerequisites ? form.prerequisites.split(/[,，]/).map((s: string) => s.trim()).filter(Boolean) : null,
      layer: form.layer,
    }))
  }
  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data)
      if (msg.event === 'start') { stage.value = msg.data.stage }
      else if (msg.event === 'stream_chunk') { thinking.value += msg.data.text || ''; stage.value = msg.data.stage }
      else if (msg.event === 'stage_change') { stage.value = msg.data.new_stage }
      else if (msg.event === 'dsl_complete') { dsl.value = msg.data.dsl; thinking.value = msg.data.thinking || thinking.value }
      else if (msg.event === 'finish') { loading.value = false; ws?.close() }
      else if (msg.event === 'error') { errorMsg.value = msg.data.message; loading.value = false; ws?.close() }
    } catch {}
  }
  ws.onerror = () => { errorMsg.value = 'WS 错误'; loading.value = false }
  ws.onclose = () => { loading.value = false }
}

const phases: Record<string, 'process' | 'finish' | 'error' | 'wait'> = {
  Engage: 'process', Explore: 'process', Explain: 'process',
  Elaborate: 'process', Evaluate: 'finish', Transfer: 'finish',
}

onMounted(() => {
  if (route.query.topic) form.topic = String(route.query.topic)
  if (route.query.grade) form.grade = String(route.query.grade)
  if (route.query.misconceptions) form.misconceptions = String(route.query.misconceptions)
  if (route.query.prerequisites) form.prerequisites = String(route.query.prerequisites)
  if (route.query.layer) form.layer = String(route.query.layer)
})
</script>
<template>
  <n-space vertical>
    <n-card title="苏格拉底课稿 (流式生成)" size="small">
      <n-form label-placement="left" :show-feedback="false" size="small">
        <n-space>
          <n-form-item label="学科"><n-select v-model:value="form.subject" :options="[{label:'数学',value:'math'}]" style="width: 110px" disabled /></n-form-item>
          <n-form-item label="年级"><n-input-number v-model:value="form.grade" :min="1" :max="12" style="width: 90px" /></n-form-item>
          <n-form-item label="主题"><n-input v-model:value="form.topic" style="width: 180px" /></n-form-item>
          <n-form-item label="分层"><n-select v-model:value="form.layer" :options="[{label:'A 基础',value:'A'},{label:'B 进阶',value:'B'},{label:'C 拔高',value:'C'}]" style="width: 110px" /></n-form-item>
          <n-button type="primary" :loading="loading" @click="generate">生成课稿</n-button>
        </n-space>
        <n-space style="margin-top: 8px">
          <n-form-item label="错因" style="flex: 1"><n-input v-model:value="form.misconceptions" placeholder="逗号分隔, 如: 忘记加车长, 混淆过桥与在桥上" /></n-form-item>
          <n-form-item label="前置" style="flex: 1"><n-input v-model:value="form.prerequisites" placeholder="逗号分隔前置知识点" /></n-form-item>
        </n-space>
      </n-form>
    </n-card>
    <n-alert v-if="errorMsg" type="error">{{ errorMsg }}</n-alert>
    <n-card v-if="stage || loading" :title="'阶段: ' + stage" size="small">
      <n-code v-if="thinking" :code="thinking" language="text" />
      <n-empty v-else-if="loading" description="等待推送..." />
    </n-card>
    <n-card v-if="dsl" title="课稿 DSL (5E 步骤)" size="small">
      <n-space style="margin-bottom: 12px">
        <n-tag type="info">{{ dsl.subject }}</n-tag>
        <n-tag>{{ dsl.steps?.length || 0 }} 步</n-tag>
        <n-tag v-if="dsl.version">v{{ dsl.version }}</n-tag>
      </n-space>
      <n-steps size="small">
        <n-step v-for="(s, i) in dsl.steps" :key="i" :status="phases[s.phase] || 'wait'" :title="s.step_title || s.phase">
          <div style="font-size: 12px">
            <p>{{ s.speech_narration }}</p>
            <p v-if="s.animation">动画区间: {{ s.animation.start_ratio }} → {{ s.animation.end_ratio }}</p>
            <n-tag v-if="s.checkpoint" size="tiny">{{ s.checkpoint.type }}</n-tag>
          </div>
        </n-step>
      </n-steps>
      <n-collapse style="margin-top: 12px">
        <n-collapse-item title="原始 DSL" name="raw">
          <n-code :code="JSON.stringify(dsl, null, 2)" language="json" />
        </n-collapse-item>
      </n-collapse>
    </n-card>
  </n-space>
</template>

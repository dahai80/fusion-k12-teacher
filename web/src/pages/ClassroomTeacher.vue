<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { NCard, NSpace, NForm, NFormItem, NInput, NButton, NTag, NCode, NDataTable, NModal, NSwitch, useMessage } from 'naive-ui'
import { classroomApi } from '@/api/endpoints'
import { useGenerator } from '@/composables/useGenerator'
import ResultViewer from '@/components/ResultViewer.vue'

const message = useMessage()
const form = reactive({ subject: '数学', grade: '5', topic: '', lesson_plan_json: '', quiz_json: '' })
const gen = useGenerator()
const script = ref<any>(null)
const packResult = ref<any>(null)
const packs = ref<any[]>([])
const showModal = ref(false)
const detailPack = ref<any>(null)
const hasScript = ref(false)

async function genScript() {
  script.value = null
  await gen.run(async () => {
    const body: any = { subject: form.subject, grade: form.grade, topic: form.topic }
    if (form.lesson_plan_json) {
      try { body.lesson_plan = JSON.parse(form.lesson_plan_json) } catch { message.error('lesson_plan JSON 格式错误') }
    }
    const r = await classroomApi.script(body)
    script.value = r
    hasScript.value = true
    return r
  })
}

async function doPack() {
  packResult.value = null
  const body: any = { subject: form.subject, grade: form.grade, topic: form.topic }
  if (form.lesson_plan_json) {
    try { body.lesson_plan = JSON.parse(form.lesson_plan_json) } catch { /* ignore */ }
  }
  if (form.quiz_json) {
    try { body.quiz = JSON.parse(form.quiz_json) } catch { message.error('quiz JSON 格式错误') }
  }
  if (hasScript.value && script.value) body.script = script.value
  await gen.run(async () => {
    const r = await classroomApi.pack(body)
    packResult.value = r
    message.success(`课堂包已生成: ${r.code}`)
    await loadPacks()
    return r
  })
}

async function loadPacks() {
  try {
    const r = await classroomApi.listPacks()
    packs.value = r.packs || []
  } catch (e: any) {
    message.error(e.message)
  }
}

async function viewPack(code: string) {
  try {
    detailPack.value = await classroomApi.getPack(code)
    showModal.value = true
  } catch (e: any) {
    message.error(e.message)
  }
}

const columns = [
  { title: '课堂码', key: 'code', width: 100 },
  { title: '学科', key: 'subject', width: 80 },
  { title: '年级', key: 'grade', width: 70 },
  { title: '主题', key: 'topic' },
  { title: '测验', key: 'has_quiz', width: 80, render: (row: any) => row.has_quiz ? '✓' : '—' },
  { title: '操作', key: 'op', width: 90, render: (row: any) => '' },
]

onMounted(loadPacks)
</script>

<template>
  <n-space vertical>
    <n-card title="课堂备课 (E1-E2: 生成讲稿 + 打包课程)" size="small">
      <n-form label-placement="left" :show-feedback="false" size="small">
        <n-form-item label="学科"><n-input v-model:value="form.subject" /></n-form-item>
        <n-form-item label="年级"><n-input v-model:value="form.grade" /></n-form-item>
        <n-form-item label="主题"><n-input v-model:value="form.topic" placeholder="如: 分数加减" /></n-form-item>
        <n-form-item label="教案(JSON,可选)"><n-input v-model:value="form.lesson_plan_json" type="textarea" :rows="2" placeholder='{"sections":[...]}' /></n-form-item>
        <n-form-item label="测验(JSON,可选)"><n-input v-model:value="form.quiz_json" type="textarea" :rows="2" placeholder='{"q1":{"answer":"0.75"}}' /></n-form-item>
      </n-form>
      <n-space style="margin-top: 12px">
        <n-button type="info" :loading="gen.loading.value" @click="genScript">① 生成讲稿</n-button>
        <n-button type="primary" :loading="gen.loading.value" @click="doPack">② 打包课堂</n-button>
      </n-space>
    </n-card>

    <ResultViewer v-if="!script && !packResult" :loading="gen.loading.value" :result="gen.result.value" :error="gen.errorMsg.value" @retry="genScript" />

    <n-card v-if="script" title="讲稿预览 (E1)" size="small">
      <n-space>
        <n-tag :type="script.error ? 'warning' : 'success'">{{ script.error ? '降级讲稿' : 'LLM 讲稿' }}</n-tag>
        <n-tag>页数: {{ script.pages?.length || 0 }}</n-tag>
      </n-space>
      <n-code :code="JSON.stringify(script, null, 2)" language="json" style="margin-top: 8px" />
    </n-card>

    <n-card v-if="packResult" title="打包结果 (E2)" size="small">
      <n-space>
        <n-tag type="success" size="large">{{ packResult.code }}</n-tag>
        <n-tag>class_id: {{ packResult.class_id }}</n-tag>
        <n-tag>主题: {{ packResult.topic }}</n-tag>
      </n-space>
      <p style="margin-top: 8px; color: #888">把 6 位课堂码发给学生, 学生在「课堂入口」页输入即可加入。</p>
    </n-card>

    <n-card title="课堂包列表 (E3)" size="small">
      <n-space style="margin-bottom: 8px"><n-button size="small" @click="loadPacks">刷新</n-button></n-space>
      <n-data-table :columns="columns" :data="packs" size="small" :pagination="{ pageSize: 8 }">
        <template #empty>暂无课堂包</template>
      </n-data-table>
      <n-space style="margin-top: 8px">
        <n-button v-for="p in packs.slice(0, 6)" :key="p.code" size="tiny" @click="viewPack(p.code)">{{ p.code }}</n-button>
      </n-space>
    </n-card>

    <n-modal v-model:show="showModal" preset="card" title="课堂包详情" style="width: 600px">
      <n-code v-if="detailPack" :code="JSON.stringify(detailPack, null, 2)" language="json" />
    </n-modal>
  </n-space>
</template>

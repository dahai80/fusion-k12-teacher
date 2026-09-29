<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NCard, NSpace, NForm, NFormItem, NInput, NSelect, NButton, NTag, NSpin, useMessage } from 'naive-ui'
import { courseApi } from '@/api/endpoints'

const router = useRouter()
const message = useMessage()
const loading = ref(true)
const subjects = ref<any[]>([])

const form = reactive({
  subject: 'math',
  grade: '3',
  topic: '',
  layer: 'B',
})

const layerOptions = [
  { label: '基础 (A)', value: 'A' },
  { label: '进阶 (B)', value: 'B' },
  { label: '拔高 (C)', value: 'C' },
]

onMounted(async () => {
  try {
    const res = await courseApi.subjects() as any
    subjects.value = (res.subjects || []).map((s: any) => ({
      label: s.display_name || s.subject_id,
      value: s.subject_id,
    }))
    if (subjects.value.length === 0) {
      subjects.value = [{ label: '数学', value: 'math' }]
    }
    form.subject = subjects.value[0].value
  } catch {
    subjects.value = [{ label: '数学', value: 'math' }]
  }
  loading.value = false
})

function startStudy() {
  if (!form.topic.trim()) {
    message.error('请输入学习主题')
    return
  }
  router.push({
    path: '/digital-human/player',
    query: {
      subject: form.subject,
      topic: form.topic,
      grade: form.grade,
      layer: form.layer,
    },
  })
}

const topicSuggestions = ['分数', '小数', '方程', '几何图形', '比例']
</script>

<template>
  <n-spin v-if="loading" />
  <n-space v-else vertical>
    <n-card title="🤖 AI 数字人老师 — 自主学习 (UC-C7)" size="small">
      <p style="color: #666; margin: 0 0 12px">
        选择学科与主题, AI 数字人老师即时开讲: 语音讲解 + 互动提问 + 举手答疑。
        无需课堂码, 即开即用。
      </p>
      <n-form label-placement="left" :show-feedback="false" size="small">
        <n-form-item label="学科">
          <n-select v-model:value="form.subject" :options="subjects" style="width: 160px" />
        </n-form-item>
        <n-form-item label="年级">
          <n-select
            v-model:value="form.grade"
            :options="Array.from({length: 12}, (_, i) => ({label: `${i+1}年级`, value: String(i+1)}))"
            style="width: 120px"
          />
        </n-form-item>
        <n-form-item label="分层">
          <n-select v-model:value="form.layer" :options="layerOptions" style="width: 120px" />
        </n-form-item>
        <n-form-item label="主题">
          <n-input v-model:value="form.topic" placeholder="如: 分数" style="width: 200px" />
        </n-form-item>
      </n-form>
      <n-space style="margin-top: 12px" size="small">
        <n-tag
          v-for="t in topicSuggestions"
          :key="t"
          size="small"
          style="cursor: pointer"
          @click="form.topic = t"
        >{{ t }}</n-tag>
      </n-space>
      <n-button type="primary" size="large" style="margin-top: 16px" @click="startStudy">
        🚀 开始学习
      </n-button>
    </n-card>

    <n-card title="功能说明" size="small">
      <n-space vertical size="small">
        <div>• <strong>语音讲解</strong>: AI 老师用 Kokoro TTS 逐页朗读讲稿 (5E 苏格拉底式)</div>
        <div>• <strong>数字人</strong>: MuseTalk 唇形同步数字人 (不可用时静态头像降级)</div>
        <div>• <strong>举手提问</strong>: 随时输入问题, LLM 流式答疑</div>
        <div>• <strong>按住说话</strong>: 语音输入 (Whisper ASR, Phase D)</div>
        <div>• <strong>打断</strong>: 讲课中说话可打断, AI 停下重听 (barge-in 总线)</div>
        <div>• <strong>平台解耦</strong>: 学科内容经 SubjectModule 注入, 数学/物理/化学零平台改动</div>
      </n-space>
    </n-card>
  </n-space>
</template>

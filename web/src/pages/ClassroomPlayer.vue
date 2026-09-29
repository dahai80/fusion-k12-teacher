<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NCard, NSpace, NButton, NTag, NSteps, NStep, NRadioGroup, NRadio, NInputNumber, NInput, NAlert, NResult, NSpin, useMessage } from 'naive-ui'
import { classroomApi } from '@/api/endpoints'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const sid = computed(() => (route.query.sid as string) || '')
const session = ref<any>(null)
const pkg = ref<any>(null)
const loading = ref(true)
const currentPage = ref(0)
const answerInput = ref<string>('')
const lastJudge = ref<any>(null)
const finished = ref(false)
const report = ref<any>(null)

const pages = computed(() => pkg.value?.script?.pages || [])
const page = computed(() => pages.value[currentPage.value] || null)

onMounted(async () => {
  if (!sid.value) { message.error('缺少 session_id'); router.push('/classroom/entry'); return }
  try {
    const rep = await classroomApi.report(sid.value)
    if (rep && rep.error === undefined && rep.quiz_stat && rep.quiz_stat.total !== undefined) {
      report.value = rep
      finished.value = true
      loading.value = false
      return
    }
  } catch { /* not finished, continue */ }
  try {
    const r = await classroomApi.getPack(route.query.code as string || '')
    pkg.value = r
    if (r?.script?.pages?.length) {
      try { await classroomApi.viewPage(sid.value, 0) } catch { /* ignore */ }
    }
  } catch {
    message.error('无法加载课程包, 请返回入口重新加入')
  }
  loading.value = false
})

async function viewPage(idx: number) {
  currentPage.value = idx
  answerInput.value = ''
  lastJudge.value = null
  try {
    await classroomApi.viewPage(sid.value, idx)
  } catch (e: any) {
    message.warning('页面访问记录失败: ' + e.message)
  }
}

async function submitAnswer() {
  if (!page.value?.question_point) return
  const qp = page.value.question_point
  lastJudge.value = null
  try {
    const r = await classroomApi.answer({
      session_id: sid.value,
      question_id: qp.id || `p${currentPage.value}`,
      student_answer: String(answerInput.value ?? ''),
      expected_answer: String(qp.answer ?? ''),
      question_type: qp.type || 'multiple_choice',
    })
    lastJudge.value = r
    if (r.correct) message.success('回答正确!')
    else message.warning('回答错误, 再想想')
  } catch (e: any) {
    const detail = e?.body?.detail
    const msg = typeof detail === 'string' ? detail
      : Array.isArray(detail) ? detail.map((x: any) => x?.msg || JSON.stringify(x)).join('; ')
      : (e?.message || String(e))
    message.error('提交失败: ' + msg)
  }
}

async function finish() {
  try {
    await classroomApi.finishSession(sid.value, false)
    finished.value = true
    report.value = await classroomApi.report(sid.value)
    message.success('课堂已结束')
  } catch (e: any) {
    message.error(e.message)
  }
}

function viewReport() {
  router.push({ path: '/classroom/report', query: { sid: sid.value } })
}

function launchDigitalHuman() {
  if (!pkg.value) return
  router.push({
    path: '/digital-human/player',
    query: {
      subject: pkg.value.subject || 'math',
      topic: pkg.value.topic || '',
      grade: pkg.value.grade || '3',
    },
  })
}

const emotionColor: Record<string, string> = { curious: 'info', encouraging: 'success', focused: 'warning', reflective: 'default' }
</script>

<template>
  <n-spin v-if="loading" />
  <n-space v-else-if="finished && report" vertical>
    <n-result status="success" title="课堂已完成" :description="`正确率: ${report.quiz_stat?.correct || 0}/${report.quiz_stat?.total || 0}`">
      <template #footer>
        <n-button type="primary" @click="viewReport">查看报告</n-button>
      </template>
    </n-result>
  </n-space>
  <n-space v-else-if="!pkg" vertical>
    <n-alert type="warning">课程包未加载, 请返回入口</n-alert>
    <n-button @click="router.push('/classroom/entry')">返回入口</n-button>
  </n-space>
  <n-space v-else vertical>
    <n-card size="small">
      <n-space align="center">
        <n-tag type="success">{{ pkg.topic }}</n-tag>
        <n-tag>{{ pkg.subject }} · {{ pkg.grade }}年级</n-tag>
        <n-tag v-if="page" :type="emotionColor[page.emotion_tag] || 'default'">{{ page.emotion_tag }}</n-tag>
        <span style="flex: 1" />
        <n-button size="small" type="primary" ghost @click="launchDigitalHuman">🤖 数字人模式</n-button>
        <n-button size="small" @click="finish">结束课堂</n-button>
      </n-space>
    </n-card>

    <n-card v-if="pages.length" size="small">
      <n-steps :current="currentPage + 1" size="small" horizontal>
        <n-step v-for="(p, i) in pages" :key="i" :title="p.title || `第${i+1}页`" @click="viewPage(i)" style="cursor: pointer" />
      </n-steps>
    </n-card>

    <n-card v-if="page" :title="`${currentPage + 1}. ${page.title || ''}`" size="small">
      <div style="font-size: 15px; line-height: 1.8; margin-bottom: 12px">{{ page.narration }}</div>
      <n-alert v-if="page.slide_content" type="info" :bordered="false" style="margin-bottom: 12px">{{ page.slide_content }}</n-alert>

      <n-card v-if="page.question_point" title="课堂提问" size="small" :bordered="true" style="margin-top: 8px">
        <div style="margin-bottom: 8px">{{ page.question_point.prompt }}</div>
        <n-radio-group v-if="page.question_point.type === 'multiple_choice'" v-model:value="answerInput">
          <n-space vertical>
            <n-radio v-for="opt in (page.question_point.options || [])" :key="opt" :value="opt">{{ opt }}</n-radio>
          </n-space>
        </n-radio-group>
        <n-input-number v-else-if="page.question_point.type === 'numeric'" v-model:value="answerInput" :controls="false" style="width: 100%" />
        <n-input v-else v-model:value="answerInput" type="textarea" :rows="2" />
        <n-space style="margin-top: 8px">
          <n-button type="primary" @click="submitAnswer">提交</n-button>
          <n-tag v-if="lastJudge" :type="lastJudge.correct ? 'success' : 'error'">{{ lastJudge.correct ? '正确' : '错误' }}</n-tag>
        </n-space>
        <n-alert v-if="lastJudge && lastJudge.feedback" type="info" :bordered="false" style="margin-top: 8px">{{ lastJudge.feedback }}</n-alert>
      </n-card>

      <n-space style="margin-top: 12px" justify="space-between">
        <n-button :disabled="currentPage === 0" @click="viewPage(currentPage - 1)">上一页</n-button>
        <n-button :disabled="currentPage >= pages.length - 1" type="primary" @click="viewPage(currentPage + 1)">下一页</n-button>
      </n-space>
    </n-card>
  </n-space>
</template>

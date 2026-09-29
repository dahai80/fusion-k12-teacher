<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NCard, NSpace, NTag, NStatistic, NDescriptions, NDescriptionsItem, NAlert, NSpin, NButton, NCode, useMessage } from 'naive-ui'
import { classroomApi } from '@/api/endpoints'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const sid = computed(() => (route.query.sid as string) || '')
const report = ref<any>(null)
const loading = ref(true)

onMounted(async () => {
  if (!sid.value) { message.error('缺少 session_id'); loading.value = false; return }
  try {
    report.value = await classroomApi.report(sid.value)
  } catch (e: any) {
    message.error(e.message)
  }
  loading.value = false
})

const accuracy = computed(() => {
  const q = report.value?.quiz_stat
  if (!q || !q.total) return '—'
  return Math.round((q.correct / q.total) * 100) + '%'
})

const attLabel = computed(() => {
  const a = report.value?.attendance
  if (!a) return '到课'
  if (typeof a === 'string') return a
  const dur = a.duration_sec ? ` · ${Math.round(a.duration_sec)}s` : ''
  return `${a.status || '到课'}${dur}`
})
</script>

<template>
  <n-spin v-if="loading" />
  <n-space v-else-if="!report" vertical>
    <n-alert type="warning">报告加载失败</n-alert>
    <n-button @click="router.push('/classroom/entry')">返回</n-button>
  </n-space>
  <n-space v-else vertical>
    <n-card title="课堂报告 (E6)" size="small">
      <n-space>
        <n-tag v-if="report.error" type="warning">已放弃 (无快照)</n-tag>
        <n-tag v-else type="success">已完成</n-tag>
        <n-tag>session: {{ report.session_id }}</n-tag>
        <n-tag>学生: {{ report.student_id }}</n-tag>
      </n-space>
    </n-card>

    <n-card v-if="!report.error" title="学习统计" size="small">
      <n-space>
        <n-statistic label="出勤" :value="attLabel" />
        <n-statistic label="浏览页数" :value="(report.pages_viewed || []).length" />
        <n-statistic label="正确率" :value="accuracy" />
        <n-statistic label="答对" :value="report.quiz_stat?.correct || 0" />
        <n-statistic label="总题" :value="report.quiz_stat?.total || 0" />
      </n-space>
    </n-card>

    <n-card v-if="!report.error && report.weak_points?.length" title="薄弱点" size="small">
      <n-space>
        <n-tag v-for="(w, i) in report.weak_points" :key="i" type="warning">{{ w }}</n-tag>
      </n-space>
    </n-card>

    <n-card title="原始报告" size="small">
      <n-code :code="JSON.stringify(report, null, 2)" language="json" />
    </n-card>

    <n-button @click="router.push('/classroom/entry')">返回入口</n-button>
  </n-space>
</template>

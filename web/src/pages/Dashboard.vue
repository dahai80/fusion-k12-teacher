<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { NCard, NGrid, NGridItem, NSpace, NStatistic, NTag, NButton, NDivider } from 'naive-ui'
import { useHealthStore } from '@/stores/health'

const router = useRouter()
const health = useHealthStore()

const shortcuts = [
  { label: '生成教案', path: '/lesson/plan' },
  { label: '一键分层', path: '/assess/diff' },
  { label: '数学批改', path: '/grade/math' },
  { label: '班级画像', path: '/analytics/class' },
  { label: '学习路径', path: '/personalize/path' },
  { label: '数学知识图谱', path: '/course/math/graph' },
  { label: '场景动画', path: '/course/math/scene' },
  { label: '题库', path: '/course/math/bank' },
]
</script>

<template>
  <n-space vertical size="large">
    <n-card title="服务状态" size="small">
      <n-space>
        <n-tag :type="health.status === 'ok' ? 'success' : health.status === 'down' ? 'error' : 'warning'">
          {{ health.status === 'ok' ? '可达' : health.status === 'down' ? '不可达' : '检测中' }}
        </n-tag>
        <n-statistic label="模型" :value="health.model || '-'" />
        <n-statistic label="就绪" :value="health.ready ? '是' : '否'" />
      </n-space>
      <n-divider />
      <n-grid :cols="4" :x-gap="12" :y-gap="12">
        <n-grid-item v-for="s in shortcuts" :key="s.path">
          <n-button block secondary @click="router.push(s.path)">{{ s.label }}</n-button>
        </n-grid-item>
      </n-grid>
    </n-card>

    <n-card title="关于" size="small">
      <p>Fusion K12 教师助手 — 本地优先 K-12 教学辅助平台。100% 离线, LLM 经 fusion-gateway 本地推理。</p>
      <p>平台-内容解耦架构: 数学课程为首发学科, 后续物理/化学/英语/语文零平台改动接入。</p>
    </n-card>
  </n-space>
</template>

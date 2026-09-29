<script setup lang="ts">
import { computed, h, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NLayout, NLayoutSider, NLayoutHeader, NLayoutContent, NMenu, NSpace, NTag, NText, NButton, NConfigProvider, NMessageProvider, NDialogProvider, zhCN, dateZhCN } from 'naive-ui'
import type { MenuOption } from 'naive-ui'
import { useHealthStore } from '@/stores/health'
import { useAuthStore } from '@/stores/auth'
import TextbookSelect from '@/components/TextbookSelect.vue'

const route = useRoute()
const router = useRouter()
const health = useHealthStore()
const auth = useAuthStore()
let timer: any = null

onMounted(() => {
  health.poll()
  timer = setInterval(() => health.poll(), 15000)
  auth.fetchMe()
})
onUnmounted(() => { if (timer) clearInterval(timer) })

const healthTag = computed(() => {
  if (health.status === 'ok') return { type: 'success' as const, label: `已连接 · ${health.model || '就绪'}` }
  if (health.status === 'down') return { type: 'error' as const, label: '后端不可达' }
  return { type: 'warning' as const, label: '检测中' }
})

const menuOptions: MenuOption[] = [
  { label: '🏠 工作台', key: '/dashboard' },
  { label: '📂 我的资源库', key: '/materials' },
  { label: '📚 备课', key: 'g-lesson', children: [
    { label: '教案', key: '/lesson/plan' },
    { label: '单元计划', key: '/lesson/unit' },
    { label: '课标对齐', key: '/lesson/align' },
  ]},
  { label: '✏️ 命题', key: 'g-assess', children: [
    { label: '测验', key: '/assess/quiz' },
    { label: '练习题', key: '/assess/exercise' },
    { label: '一键分层', key: '/assess/diff' },
    { label: '评分量表', key: '/assess/rubric' },
  ]},
  { label: '🧑‍🏫 批改', key: 'g-grade', children: [
    { label: '数学批改', key: '/grade/math' },
    { label: '作文批改', key: '/grade/essay' },
    { label: '学生报告', key: '/grade/report' },
  ]},
  { label: '📊 学情', key: 'g-analytics', children: [
    { label: '数据上传', key: '/analytics/upload' },
    { label: '班级画像', key: '/analytics/class' },
    { label: '学生画像', key: '/analytics/student' },
    { label: '错因分析', key: '/analytics/error' },
    { label: '补救计划', key: '/analytics/remedial' },
    { label: '班级报告', key: '/analytics/report' },
  ]},
  { label: '🎯 个性化', key: 'g-personalize', children: [
    { label: '学习路径', key: '/personalize/path' },
    { label: '技能诊断', key: '/personalize/diagnose' },
    { label: '资源推荐', key: '/personalize/recommend' },
  ]},
  { label: '🧰 内容工具', key: 'g-content', children: [
    { label: '工作纸', key: '/content/worksheet' },
    { label: '闪卡', key: '/content/flashcards' },
    { label: '课件', key: '/content/slides' },
    { label: '教育游戏', key: '/content/game' },
    { label: '家长沟通稿', key: '/content/parent' },
  ]},
  { label: '📐 数学课程', key: 'g-course', children: [
    { label: '知识图谱', key: '/course/math/graph' },
    { label: '场景动画', key: '/course/math/scene' },
    { label: '苏格拉底课稿', key: '/course/math/lesson' },
    { label: '题库', key: '/course/math/bank' },
  ]},
  { label: '🤖 自动化', key: '/agent' },
  { label: '🏫 课堂', key: 'g-classroom', children: [
    { label: '课堂备课(师)', key: '/classroom/teacher' },
    { label: '课堂入口(生)', key: '/classroom/entry' },
  ]},
  { label: '🤖 数字人老师', key: 'g-digital-human', children: [
    { label: '自主学习', key: '/digital-human/self-study' },
  ]},
  { label: '🛡️ 安全中心', key: '/safety' },
  { label: '🔒 数据隐私', key: '/desensitize' },
  { label: '⚙️ 设置', key: '/settings' },
]

const activeKey = computed(() => route.path)

function handleSelect(key: string) {
  if (key.startsWith('/')) router.push(key)
}
</script>

<template>
  <n-config-provider :locale="zhCN" :date-locale="dateZhCN">
    <n-message-provider>
      <n-dialog-provider>
        <n-layout has-sider style="height: 100vh">
          <n-layout-sider v-if="auth.isLoggedIn" bordered :native-scrollbar="true" content-style="padding: 8px 0;" :width="220" collapse-mode="width">
            <div style="padding: 12px 16px; font-weight: 700; font-size: 15px; border-bottom: 1px solid var(--n-border-color)">
              Fusion K12 教师助手
            </div>
            <n-menu :options="menuOptions" :value="activeKey" @update:value="handleSelect" />
          </n-layout-sider>
          <n-layout>
            <n-layout-header bordered style="height: 48px; display: flex; align-items: center; gap: 12px; padding: 0 16px">
              <span style="font-weight: 600; white-space: nowrap">{{ route.meta?.title || '教师工作台' }}</span>
              <textbook-select v-if="auth.isLoggedIn" style="flex: 1; min-width: 0" />
              <n-space align="center" :wrap="false">
                <n-tag :type="healthTag.type" size="small" round>{{ healthTag.label }}</n-tag>
                <n-button size="tiny" quaternary @click="health.poll()">刷新</n-button>
                <n-text v-if="auth.teacher" depth="2" style="font-size: 12px">{{ auth.teacher.name || auth.teacher.username }}</n-text>
                <n-button v-if="auth.isLoggedIn" size="tiny" quaternary @click="auth.logout().then(() => router.push('/login'))">退出</n-button>
              </n-space>
            </n-layout-header>
            <n-layout-content content-style="padding: 20px;" style="height: calc(100vh - 48px); overflow: auto">
              <router-view />
            </n-layout-content>
          </n-layout>
        </n-layout>
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>

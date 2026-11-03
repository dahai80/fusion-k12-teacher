<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NLayout, NLayoutSider, NLayoutHeader, NLayoutContent, NMenu, NSpace, NTag, NText, NButton, NConfigProvider, NMessageProvider, NDialogProvider, zhCN, enUS, dateZhCN, dateEnUS, darkTheme } from 'naive-ui'
import type { MenuOption } from 'naive-ui'
import { useHealthStore } from '@/stores/health'
import { useAuthStore } from '@/stores/auth'
import { inShell } from '@/shell'
import { useShellTheme } from '@/shellTheme'
import { useLang, t } from '@/i18n'
import TextbookSelect from '@/components/TextbookSelect.vue'

const route = useRoute()
const router = useRouter()
const health = useHealthStore()
const auth = useAuthStore()
// issue #38: 主题/语言跟随 union shell (SDK 通道), 独立态走本地链
const shellTheme = useShellTheme()
const lang = useLang()
const naiveTheme = computed(() => (shellTheme.value === 'dark' ? darkTheme : null))
const naiveLocale = computed(() => (lang.value === 'en' ? enUS : zhCN))
const naiveDateLocale = computed(() => (lang.value === 'en' ? dateEnUS : dateZhCN))
// issue #30: shell 嵌入态登录由宿主持有 — 未登录教师也显示菜单,
// 教师绑定功能 (资源库/教材自动保存) 可经 /login 自愿登录
const shell = inShell()
const showSider = computed(() => shell || auth.isLoggedIn)
let timer: any = null

onMounted(() => {
  health.poll()
  timer = setInterval(() => health.poll(), 15000)
  auth.fetchMe()
})
onUnmounted(() => { if (timer) clearInterval(timer) })

const healthTag = computed(() => {
  if (health.status === 'ok') return { type: 'success' as const, label: t('已连接', 'Connected') + ` · ${health.model || t('就绪', 'Ready')}` }
  if (health.status === 'down') return { type: 'error' as const, label: t('后端不可达', 'Backend unreachable') }
  return { type: 'warning' as const, label: t('检测中', 'Checking') }
})

const menuOptions = computed<MenuOption[]>(() => [
  { label: t('🏠 工作台', '🏠 Dashboard'), key: '/dashboard' },
  { label: t('📂 我的资源库', '📂 My Materials'), key: '/materials' },
  { label: t('📚 备课', '📚 Lesson Prep'), key: 'g-lesson', children: [
    { label: t('教案', 'Lesson Plan'), key: '/lesson/plan' },
    { label: t('单元计划', 'Unit Plan'), key: '/lesson/unit' },
    { label: t('课标对齐', 'Standards Align'), key: '/lesson/align' },
  ]},
  { label: t('✏️ 命题', '✏️ Assessment'), key: 'g-assess', children: [
    { label: t('测验', 'Quiz'), key: '/assess/quiz' },
    { label: t('练习题', 'Exercise'), key: '/assess/exercise' },
    { label: t('一键分层', 'Differentiation'), key: '/assess/diff' },
    { label: t('评分量表', 'Rubric'), key: '/assess/rubric' },
  ]},
  { label: t('🧑‍🏫 批改', '🧑‍🏫 Grading'), key: 'g-grade', children: [
    { label: t('数学批改', 'Math Grading'), key: '/grade/math' },
    { label: t('作文批改', 'Essay Grading'), key: '/grade/essay' },
    { label: t('学生报告', 'Student Report'), key: '/grade/report' },
  ]},
  { label: t('📊 学情', '📊 Analytics'), key: 'g-analytics', children: [
    { label: t('数据上传', 'Upload'), key: '/analytics/upload' },
    { label: t('班级画像', 'Class Profile'), key: '/analytics/class' },
    { label: t('学生画像', 'Student Profile'), key: '/analytics/student' },
    { label: t('错因分析', 'Error Analysis'), key: '/analytics/error' },
    { label: t('补救计划', 'Remediation'), key: '/analytics/remedial' },
    { label: t('班级报告', 'Class Report'), key: '/analytics/report' },
  ]},
  { label: t('🎯 个性化', '🎯 Personalization'), key: 'g-personalize', children: [
    { label: t('学习路径', 'Learning Path'), key: '/personalize/path' },
    { label: t('技能诊断', 'Skill Diagnosis'), key: '/personalize/diagnose' },
    { label: t('资源推荐', 'Recommendations'), key: '/personalize/recommend' },
  ]},
  { label: t('🧰 内容工具', '🧰 Content Tools'), key: 'g-content', children: [
    { label: t('工作纸', 'Worksheet'), key: '/content/worksheet' },
    { label: t('闪卡', 'Flashcards'), key: '/content/flashcards' },
    { label: t('课件', 'Slides'), key: '/content/slides' },
    { label: t('教育游戏', 'Edu Games'), key: '/content/game' },
    { label: t('家长沟通稿', 'Parent Letter'), key: '/content/parent' },
  ]},
  { label: t('📐 数学课程', '📐 Math Course'), key: 'g-course', children: [
    { label: t('知识图谱', 'Knowledge Graph'), key: '/course/math/graph' },
    { label: t('场景动画', 'Scene Animation'), key: '/course/math/scene' },
    { label: t('苏格拉底课稿', 'Socratic Lesson'), key: '/course/math/lesson' },
    { label: t('题库', 'Problem Bank'), key: '/course/math/bank' },
  ]},
  { label: t('🤖 自动化', '🤖 Automation'), key: '/agent' },
  { label: t('🏫 课堂', '🏫 Classroom'), key: 'g-classroom', children: [
    { label: t('课堂备课(师)', 'Classroom Prep'), key: '/classroom/teacher' },
    { label: t('课堂入口(生)', 'Classroom Entry'), key: '/classroom/entry' },
  ]},
  { label: t('🤖 数字人老师', '🤖 Digital Human'), key: 'g-digital-human', children: [
    { label: t('自主学习', 'Self-Study'), key: '/digital-human/self-study' },
  ]},
  { label: t('🛡️ 安全中心', '🛡️ Safety'), key: '/safety' },
  { label: t('🔒 数据隐私', '🔒 Privacy'), key: '/desensitize' },
  { label: t('⚙️ 设置', '⚙️ Settings'), key: '/settings' },
])

const activeKey = computed(() => route.path)
const pageTitle = computed(() => {
  const meta = route.meta as { title?: string, titleEn?: string } | undefined
  if (meta?.titleEn) return t(meta.title || '', meta.titleEn)
  return t('教师工作台', 'Teacher Workspace')
})

function handleSelect(key: string) {
  if (key.startsWith('/')) router.push(key)
}
</script>

<template>
  <n-config-provider :theme="naiveTheme" :locale="naiveLocale" :date-locale="naiveDateLocale" style="height: 100%">
    <n-message-provider>
      <n-dialog-provider>
        <n-layout has-sider style="height: 100vh">
          <n-layout-sider v-if="showSider" bordered :native-scrollbar="true" content-style="padding: 8px 0;" :width="220" collapse-mode="width">
            <div style="padding: 12px 16px; font-weight: 700; font-size: 15px; border-bottom: 1px solid var(--n-border-color)">
              {{ t('Fusion K12 教师助手', 'Fusion K12 Teacher') }}
            </div>
            <n-menu :options="menuOptions" :value="activeKey" @update:value="handleSelect" />
          </n-layout-sider>
          <n-layout>
            <n-layout-header bordered style="height: 48px; display: flex; align-items: center; gap: 12px; padding: 0 16px">
              <span style="font-weight: 600; white-space: nowrap">{{ pageTitle }}</span>
              <textbook-select v-if="auth.isLoggedIn" style="flex: 1; min-width: 0" />
              <n-space align="center" :wrap="false">
                <n-tag :type="healthTag.type" size="small" round>{{ healthTag.label }}</n-tag>
                <n-button size="tiny" quaternary @click="health.poll()">{{ t('刷新', 'Refresh') }}</n-button>
                <n-text v-if="auth.teacher" depth="2" style="font-size: 12px">{{ auth.teacher.name || auth.teacher.username }}</n-text>
                <n-button v-if="!auth.isLoggedIn" size="tiny" quaternary @click="router.push('/login')">{{ t('教师登录', 'Teacher Login') }}</n-button>
                <n-button v-if="auth.isLoggedIn" size="tiny" quaternary @click="auth.logout().then(() => router.push('/login'))">{{ t('退出', 'Sign Out') }}</n-button>
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

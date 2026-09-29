<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { NCard, NSpace, NSelect, NButton, NGrid, NGridItem, NTag, NText, NEmpty, NSpin, NModal, useMessage } from 'naive-ui'
import { materialsApi } from '@/api/endpoints'
import ResultViewer from '@/components/ResultViewer.vue'

const message = useMessage()
const loading = ref(false)
const items = ref<any[]>([])
const filters = ref({ type: '', subject: '', grade: '' })
const detailVisible = ref(false)
const detail = ref<any>(null)
const detailLoading = ref(false)

const typeOptions = [
  { label: '全部', value: '' },
  { label: '教案', value: 'lesson_plan' },
  { label: '测验', value: 'quiz' },
  { label: '单元计划', value: 'unit_plan' },
  { label: '分层教案', value: 'diff_lesson' },
  { label: '分层测验', value: 'diff_quiz' },
  { label: '分层工作纸', value: 'diff_worksheet' },
  { label: '工作纸', value: 'worksheet' },
  { label: '闪卡', value: 'flashcards' },
  { label: '课件', value: 'slides' },
  { label: '游戏', value: 'game' },
  { label: '家长沟通', value: 'parent_comm' },
  { label: '数学批改', value: 'grade_math' },
  { label: '作文批改', value: 'grade_essay' },
  { label: '评分量规', value: 'rubric' },
  { label: '学生报告', value: 'report' },
  { label: '班级画像', value: 'class_profile' },
  { label: '学生画像', value: 'student_profile' },
  { label: '错因分析', value: 'error_analysis' },
  { label: '补救计划', value: 'remedial' },
  { label: '班级报告', value: 'class_report' },
  { label: '技能诊断', value: 'diagnose' },
  { label: '学习路径', value: 'path' },
  { label: '资源推荐', value: 'recommend' },
  { label: '概念讲解', value: 'explain' },
  { label: '练习', value: 'exercise' },
  { label: 'STEM项目', value: 'stem' },
  { label: '语言活动', value: 'lang_activity' },
  { label: '课标对齐', value: 'align' },
  { label: '覆盖报告', value: 'coverage' },
  { label: '安全检查', value: 'safety' },
  { label: '脱敏', value: 'desensitize' },
]

const TYPE_LABELS: Record<string, string> = Object.fromEntries(
  typeOptions.filter(o => o.value).map(o => [o.value, o.label])
)

async function load() {
  loading.value = true
  try {
    const q: any = {}
    if (filters.value.type) q.type = filters.value.type
    if (filters.value.subject) q.subject = filters.value.subject
    if (filters.value.grade) q.grade = filters.value.grade
    const r = await materialsApi.list(q)
    items.value = r.items || []
  } catch (e: any) {
    message.error('加载资源库失败: ' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

async function openDetail(item: any) {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  try {
    const r = await materialsApi.get(item.id)
    detail.value = r
  } catch (e: any) {
    message.error('加载详情失败: ' + (e?.message || e))
  } finally {
    detailLoading.value = false
  }
}

async function removeItem(item: any) {
  try {
    await materialsApi.delete(item.id)
    message.success('已删除')
    await load()
  } catch (e: any) {
    message.error('删除失败: ' + (e?.message || e))
  }
}

onMounted(load)
</script>

<template>
  <n-card title="我的资源库" size="small">
    <template #header-extra>
      <n-button size="small" quaternary @click="load">刷新</n-button>
    </template>
    <n-space align="center" style="margin-bottom: 12px">
      <n-select v-model:value="filters.type" :options="typeOptions" size="small" style="width: 160px" placeholder="类型" @update:value="load" />
      <n-button size="small" @click="load">筛选</n-button>
    </n-space>
    <n-spin :show="loading">
      <n-empty v-if="!items.length && !loading" description="资源库为空, 生成内容后将自动保存到这里" />
      <n-grid v-else :cols="3" :x-gap="12" :y-gap="12" responsive="screen">
        <n-grid-item v-for="item in items" :key="item.id">
          <n-card size="small" hoverable @click="openDetail(item)">
            <template #header>
              <n-text style="font-size: 13px">{{ item.title || '(无标题)' }}</n-text>
            </template>
            <n-space size="small">
              <n-tag size="small" type="info">{{ TYPE_LABELS[item.type] || item.type }}</n-tag>
              <n-tag v-if="item.subject" size="small">{{ item.subject }}</n-tag>
              <n-tag v-if="item.grade" size="small">{{ item.grade }}年级</n-tag>
            </n-space>
            <n-text v-if="item.lesson_title" depth="3" style="font-size: 12px; display: block; margin-top: 6px">
              {{ item.unit_title }} · {{ item.lesson_title }}
            </n-text>
            <n-text depth="3" style="font-size: 11px; display: block; margin-top: 4px">{{ item.created_at }}</n-text>
            <template #action>
              <n-button size="tiny" quaternary type="error" @click.stop="removeItem(item)">删除</n-button>
            </template>
          </n-card>
        </n-grid-item>
      </n-grid>
    </n-spin>

    <n-modal v-model:show="detailVisible" preset="card" style="width: 800px; max-width: 95vw" :title="detail?.title || '资源详情'">
      <n-spin :show="detailLoading">
        <ResultViewer v-if="detail" :loading="false" :result="detail.payload" :error="''" />
      </n-spin>
    </n-modal>
  </n-card>
</template>

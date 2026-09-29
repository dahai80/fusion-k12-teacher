<script setup lang="ts">
import { onMounted, reactive, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { NCard, NSpace, NSelect, NDataTable, NTag, NDrawer, NDrawerContent, NCode, NDescriptions, NDescriptionsItem, NButton } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { courseApi } from '@/api/endpoints'
import { useMessage } from 'naive-ui'

const message = useMessage()
const router = useRouter()
const problems = ref<any[]>([])
const manifest = ref<any>({})
const loading = ref(false)
const filter = reactive({ template_id: '', difficulty_layer: '', misconception_tag: '' })
const detail = ref<any>(null)
const showDetail = ref(false)

const templateOpts = computed(() => {
  const set = new Set(problems.value.map(p => p.template_id))
  return [...set].map(v => ({ label: v, value: v }))
})
const diffOpts = [{ label: 'A 基础', value: 'A' }, { label: 'B 进阶', value: 'B' }, { label: 'C 拔高', value: 'C' }]
const miscOpts = computed(() => (manifest.value.misconceptions || []).map((m: any) => ({ label: m.label, value: m.id })))

const columns: DataTableColumns<any> = [
  { title: 'ID', key: 'id', width: 110 },
  { title: '类型', key: 'kind', width: 70, render: r => r.kind === 'example' ? '例题' : '练习' },
  { title: '模板', key: 'template_id', width: 160 },
  { title: '层', key: 'difficulty_layer', width: 60, render: r => { const t = r.difficulty_layer === 'A' ? 'success' : r.difficulty_layer === 'B' ? 'warning' : 'error'; return h(NTag, { type: t, size: 'tiny' }, { default: () => r.difficulty_layer }) } },
  { title: '知识点', key: 'knowledge_node_id', width: 140 },
  { title: '认知', key: 'cognitive_level', width: 80 },
  { title: '题干', key: 'problem_text', ellipsis: { tooltip: true } },
  { title: '操作', key: 'op', width: 80, render: r => h(NButton, { size: 'tiny', onClick: () => { detail.value = r; showDetail.value = true } }, { default: () => '详情' }) },
]

import { h } from 'vue'
async function load() {
  loading.value = true
  try {
    const q: any = {}
    if (filter.template_id) q.template_id = filter.template_id
    if (filter.difficulty_layer) q.difficulty_layer = filter.difficulty_layer
    if (filter.misconception_tag) q.misconception_tag = filter.misconception_tag
    const r = await courseApi.problemBank('math', q)
    problems.value = r.problems || []
    manifest.value = r.manifest || {}
  } catch (e: any) { message.error('加载失败: ' + (e?.message || e)) }
  finally { loading.value = false }
}
onMounted(load)

function toLesson() {
  if (!detail.value) return
  const d = detail.value
  const grade = (d.knowledge_node_id || '').match(/g(\d)/)?.[1] || '5'
  router.push({
    path: '/course/math/lesson',
    query: {
      topic: (d.problem_text || '').slice(0, 40),
      grade,
      misconceptions: (d.misconception_tags || []).join(','),
      layer: d.difficulty_layer || 'B',
    },
  })
}
</script>
<template>
  <n-space vertical>
    <n-card title="数学题库 — 1-6年级易错题 (场景+概念)" size="small">
      <n-space style="margin-bottom: 12px">
        <n-select v-model:value="filter.template_id" :options="templateOpts" placeholder="模板" size="small" clearable style="width: 180px" />
        <n-select v-model:value="filter.difficulty_layer" :options="diffOpts" placeholder="分层" size="small" clearable style="width: 120px" />
        <n-select v-model:value="filter.misconception_tag" :options="miscOpts" placeholder="错因" size="small" clearable style="width: 200px" />
        <n-button size="small" type="primary" @click="load">查询</n-button>
      </n-space>
      <n-data-table :columns="columns" :data="problems" :loading="loading" size="small" :max-height="500" />
    </n-card>
    <n-drawer v-model:show="showDetail" :width="480">
      <n-drawer-content :title="detail?.id" closable>
        <template v-if="detail">
          <n-descriptions label-placement="left" bordered :column="1" size="small">
            <n-descriptions-item label="模板">{{ detail.template_id }}</n-descriptions-item>
            <n-descriptions-item label="分层">{{ detail.difficulty_layer }}</n-descriptions-item>
            <n-descriptions-item label="认知层级">{{ detail.cognitive_level }}</n-descriptions-item>
            <n-descriptions-item label="知识点">{{ detail.knowledge_node_id }}</n-descriptions-item>
            <n-descriptions-item label="前置">{{ detail.prerequisite_node_ids?.join(', ') }}</n-descriptions-item>
            <n-descriptions-item label="错因">{{ detail.misconception_tags?.join(', ') }}</n-descriptions-item>
            <n-descriptions-item label="题干">{{ detail.problem_text }}</n-descriptions-item>
            <n-descriptions-item label="关键认知">{{ detail.key_cognition }}</n-descriptions-item>
          </n-descriptions>
          <n-code :code="JSON.stringify({ variables: detail.variables, expected: detail.expected }, null, 2)" language="json" style="margin-top: 12px" />
          <n-button type="primary" size="small" style="margin-top: 12px" @click="toLesson">生成苏格拉底课稿 →</n-button>
        </template>
      </n-drawer-content>
    </n-drawer>
  </n-space>
</template>

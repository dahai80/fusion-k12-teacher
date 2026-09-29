<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { NCard, NSpace, NSelect, NDataTable, NTag, NDrawer, NDrawerContent, NCode, NDescriptions, NDescriptionsItem, NButton } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { courseApi } from '@/api/endpoints'
import { useMessage } from 'naive-ui'
import { h } from 'vue'

const message = useMessage()
const nodes = ref<any[]>([])
const loading = ref(false)
const grade = ref<string>('')
const detail = ref<any>(null)
const showDetail = ref(false)
const gradeOpts = Array.from({ length: 12 }, (_, i) => ({ label: `${i + 1} 年级`, value: String(i + 1) }))

const columns: DataTableColumns<any> = [
  { title: 'ID', key: 'id', width: 140 },
  { title: '标题', key: 'title' },
  { title: '年级', key: 'grade', width: 60 },
  { title: '模块', key: 'strand', width: 120 },
  { title: '认知', key: 'cognitive_level', width: 80, render: r => r.cognitive_level ? h(NTag, { size: 'tiny' }, { default: () => r.cognitive_level }) : '' },
  { title: '操作', key: 'op', width: 80, render: r => h(NButton, { size: 'tiny', onClick: () => openNode(r.id) }, { default: () => '详情' }) },
]

async function load() {
  loading.value = true
  try {
    const q: any = grade.value ? { grade: grade.value } : {}
    const r = await courseApi.graphNodes('math', q)
    nodes.value = r.nodes || []
  } catch (e: any) { message.error('加载失败: ' + (e?.message || e)) }
  finally { loading.value = false }
}
async function openNode(id: string) {
  try {
    const r = await courseApi.graphNode('math', id)
    detail.value = r.node
    detail.value._chain = r.prerequisites_chain
    showDetail.value = true
  } catch (e: any) { message.error('加载失败: ' + (e?.message || e)) }
}
async function attribution(id: string) {
  try {
    const r = await courseApi.errorAttribution('math', { node_id: id, max_depth: 2 })
    detail.value._attribution = r.attribution_path
  } catch (e: any) { message.error('归因失败: ' + (e?.message || e)) }
}
onMounted(load)
</script>
<template>
  <n-space vertical>
    <n-card title="数学知识图谱" size="small">
      <n-space style="margin-bottom: 12px">
        <n-select v-model:value="grade" :options="gradeOpts" placeholder="全部年级" size="small" clearable style="width: 160px" />
        <n-button size="small" type="primary" @click="load">查询</n-button>
      </n-space>
      <n-data-table :columns="columns" :data="nodes" :loading="loading" size="small" :max-height="500" />
    </n-card>
    <n-drawer v-model:show="showDetail" :width="500">
      <n-drawer-content :title="detail?.title" closable>
        <template v-if="detail">
          <n-descriptions label-placement="left" bordered :column="1" size="small">
            <n-descriptions-item label="ID">{{ detail.id }}</n-descriptions-item>
            <n-descriptions-item label="年级">{{ detail.grade }}</n-descriptions-item>
            <n-descriptions-item label="模块">{{ detail.strand }}</n-descriptions-item>
            <n-descriptions-item label="认知层级">{{ detail.cognitive_level }}</n-descriptions-item>
            <n-descriptions-item label="公式">{{ detail.formula || '-' }}</n-descriptions-item>
            <n-descriptions-item label="可视化引擎">{{ detail.visual_engine || '-' }}</n-descriptions-item>
            <n-descriptions-item label="错因沉淀">{{ detail.misconceptions?.join('; ') || '-' }}</n-descriptions-item>
            <n-descriptions-item label="描述">{{ detail.description || '-' }}</n-descriptions-item>
          </n-descriptions>
          <n-space style="margin-top: 12px"><n-button size="small" @click="attribution(detail.id)">错因归因</n-button></n-space>
          <n-code v-if="detail._chain" :code="'前置链: ' + JSON.stringify(detail._chain)" language="json" style="margin-top: 12px" />
          <n-code v-if="detail._attribution" :code="'归因路径: ' + JSON.stringify(detail._attribution)" language="json" style="margin-top: 12px" />
        </template>
      </n-drawer-content>
    </n-drawer>
  </n-space>
</template>

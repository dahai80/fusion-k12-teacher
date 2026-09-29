<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { NCard, NSpace, NButton, NDataTable, NTag, NPopconfirm, useMessage } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { agentApi } from '@/api/endpoints'
import { ApiError } from '@/api/client'

const message = useMessage()
const tasks = ref<any[]>([])
const history = ref<any[]>([])
const running = ref(false)

const columns: DataTableColumns<any> = [
  { title: '任务', key: 'name', width: 160 },
  { title: '描述', key: 'description' },
  { title: '状态', key: 'status', width: 100, render: (r) => r.status ? h(NTag, { type: 'success', size: 'small' }, { default: () => '已配置' }) : h(NTag, { size: 'small' }, { default: () => '未配置' }) },
  { title: '操作', key: 'op', width: 120, render: (r) => h(NPopconfirm, { onPositiveClick: () => runTask(r.name) }, { default: () => '立即执行?', trigger: () => h(NButton, { size: 'tiny', type: 'primary' }, { default: () => '执行' }) }) },
]

import { h } from 'vue'
async function load() {
  try {
    const [t, hist] = await Promise.all([agentApi.tasks(), agentApi.history().catch(() => [])])
    tasks.value = t?.tasks || []
    history.value = hist?.history || []
  } catch (e: any) {
    message.error('加载失败: ' + (e?.message || e))
  }
}
async function runTask(name: string) {
  running.value = true
  try {
    const r = await agentApi.run({ task_name: name })
    message.success('执行完成')
    history.value = [{ task: name, time: new Date().toISOString(), result: r }, ...history.value].slice(0, 20)
  } catch (e: any) {
    message.error('执行失败: ' + (e instanceof ApiError ? e.body?.detail : e?.message))
  } finally { running.value = false }
}
onMounted(load)
</script>
<template>
  <n-space vertical>
    <n-card title="预置任务" size="small">
      <n-space style="margin-bottom: 12px"><n-button size="small" @click="load">刷新</n-button></n-space>
      <n-data-table :columns="columns" :data="tasks" :loading="running" size="small" />
    </n-card>
    <n-card title="执行历史" size="small">
      <n-data-table :data="history" size="small" :columns="[{ title: '任务', key: 'task' }, { title: '时间', key: 'time' }]" />
    </n-card>
  </n-space>
</template>

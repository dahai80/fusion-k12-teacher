<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { NCard, NSpace, NButton, NDataTable, NTag, NPopconfirm, NSwitch, useMessage } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { agentApi } from '@/api/endpoints'
import { ApiError } from '@/api/client'

const message = useMessage()
const tasks = ref<any[]>([])
const history = ref<any[]>([])
const running = ref(false)
// 已注册到调度器(有 cron 排程)的任务 id 集合 — "状态"列与开关的依据
const scheduledIds = ref<Set<string>>(new Set())

const columns: DataTableColumns<any> = [
  { title: '任务', key: 'name', width: 160 },
  { title: '描述', key: 'description' },
  { title: '排程', key: 'schedule', width: 100, render: (r) => h(NTag, {
      type: scheduledIds.value.has(r.id) ? 'success' : 'default', size: 'small',
    }, { default: () => (scheduledIds.value.has(r.id) ? '定时已启用' : '未配置') }) },
  { title: '调度开关', key: 'switch', width: 90, render: (r) => h(NSwitch, {
      size: 'small',
      value: scheduledIds.value.has(r.id),
      loading: switching.value === r.id,
      onUpdateValue: (v: boolean) => toggleSchedule(r.id, v),
    }) },
  { title: '操作', key: 'op', width: 120, render: (r) => h(NPopconfirm, { onPositiveClick: () => runTask(r.id) }, { default: () => '立即执行?', trigger: () => h(NButton, { size: 'tiny', type: 'primary' }, { default: () => '执行' }) }) },
]

import { h } from 'vue'
const switching = ref('')
async function load() {
  try {
    const [t, hist] = await Promise.all([agentApi.tasks(), agentApi.history().catch(() => [])])
    // 后端返回 {predefined: {task_id: 描述}, registered: [{id,name,...}]} —
    // 原代码读 t.tasks（不存在）→ 表格永远为空只剩刷新按钮
    tasks.value = Object.entries(t?.predefined || {}).map(([id, description]) => ({
      id, name: id, description,
    }))
    scheduledIds.value = new Set((t?.registered || []).map((x: any) => x.id))
    history.value = hist?.history || []
  } catch (e: any) {
    message.error('加载失败: ' + (e?.message || e))
  }
}
async function toggleSchedule(id: string, enable: boolean) {
  switching.value = id
  try {
    const r = await agentApi.schedule({ task_id: id, enable })
    if (r?.success) {
      if (enable) scheduledIds.value = new Set([...scheduledIds.value, id])
      else scheduledIds.value = new Set([...scheduledIds.value].filter((x) => x !== id))
      message.success(enable ? '已启用定时调度' : '已停用定时调度')
    } else {
      message.error('调度配置失败（任务无 cron 排程或不存在）')
    }
  } catch (e: any) {
    message.error('调度配置失败: ' + (e instanceof ApiError ? e.body?.detail : e?.message))
  } finally { switching.value = '' }
}
async function runTask(name: string) {
  running.value = true
  try {
    // 后端 AgentRunRequest 字段是 task_id（非 task_name）
    const r = await agentApi.run({ task_id: name })
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

<script setup lang="ts">
import { ref } from 'vue'
import { NCard, NSpace, NUpload, NButton, NTag, NText, NCollapse, NCollapseItem, NCode, useMessage } from 'naive-ui'
import type { UploadFileInfo } from 'naive-ui'
import { analyticsApi } from '@/api/endpoints'
import { useAnalyticsStore } from '@/stores/analytics'

const message = useMessage()
const analytics = useAnalyticsStore()
const fileList = ref<UploadFileInfo[]>([])
const loading = ref(false)
const resp = ref<any>(null)

async function customRequest({ file }: { file: UploadFileInfo }) {
  if (!file.file) return
  loading.value = true
  try {
    const r = await analyticsApi.upload(file.file)
    resp.value = r
    if (r?.data_path) {
      analytics.dataPath = r.data_path
      message.success('上传成功, 数据集已绑定: ' + r.data_path)
    }
  } catch (e: any) {
    message.error('上传失败: ' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

async function downloadTemplate(fmt: 'json' | 'csv') {
  try {
    const blob = await analyticsApi.template(fmt)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = fmt === 'json' ? 'analytics_template.json' : 'analytics_template.csv'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    message.success('模板已下载')
  } catch (e: any) {
    message.error('下载失败: ' + (e?.message || e))
  }
}
</script>
<template>
  <n-card title="学情数据上传" size="small">
    <n-space vertical>
      <n-text>支持 JSON / CSV, 上传后自动脱敏落盘, 返回 data_path 供后续学情页使用。</n-text>
      <n-space>
        <n-button size="small" secondary @click="downloadTemplate('json')">下载 JSON 模板</n-button>
        <n-button size="small" secondary @click="downloadTemplate('csv')">下载 CSV 模板</n-button>
      </n-space>
      <n-upload :custom-request="customRequest" v-model:file-list="fileList" accept=".json,.csv">
        <n-button :loading="loading">选择文件上传</n-button>
      </n-upload>
      <n-space>
        <n-tag v-if="analytics.dataPath" type="success">当前数据集: {{ analytics.dataPath }}</n-tag>
        <n-button v-if="analytics.dataPath" size="small" quaternary @click="analytics.clear()">清除绑定</n-button>
      </n-space>
      <n-collapse style="margin-top: 4px">
        <n-collapse-item title="字段说明" name="fields">
          <n-space vertical size="small">
            <n-text depth="2">student_id: 学生编号 (必填)</n-text>
            <n-text depth="2">student_name: 学生姓名 (上传时自动脱敏)</n-text>
            <n-text depth="2">assessment_id: 测评编号</n-text>
            <n-text depth="2">date: 测评日期 (YYYY-MM-DD)</n-text>
            <n-text depth="2">subject: 学科 / grade: 年级</n-text>
            <n-text depth="2">total_score: 总分 / max_score: 满分 (默认100)</n-text>
            <n-text depth="2">scores: 各知识点得分 (JSON 对象, CSV 无此列)</n-text>
            <n-text depth="2">responses: 答题明细 (question_id/question/answer/correct)</n-text>
            <n-text depth="2">CSV 每行一条答题记录, 按 student_id+assessment_id 聚合</n-text>
          </n-space>
        </n-collapse-item>
      </n-collapse>
      <pre v-if="resp" style="background: #f5f5f5; padding: 12px; font-size: 12px; overflow: auto">{{ JSON.stringify(resp, null, 2) }}</pre>
    </n-space>
  </n-card>
</template>

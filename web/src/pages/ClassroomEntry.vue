<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NCard, NSpace, NForm, NFormItem, NInput, NButton, NTag, NCode, useMessage } from 'naive-ui'
import { classroomApi } from '@/api/endpoints'
import { useGenerator } from '@/composables/useGenerator'

const router = useRouter()
const message = useMessage()
const form = reactive({ code: '', student_id: '' })
const gen = useGenerator()
const session = ref<any>(null)
const pkg = ref<any>(null)

async function join() {
  if (!/^\d{6}$/.test(form.code)) { message.error('请输入 6 位课堂码'); return }
  if (!form.student_id.trim()) { message.error('请输入学号'); return }
  session.value = null
  await gen.run(async () => {
    const r = await classroomApi.createSession({ code: form.code, student_id: form.student_id })
    session.value = r.session
    pkg.value = r.package
    message.success(`已加入课堂: ${r.package.topic}`)
    return r
  })
}

function enterClass() {
  if (session.value) {
    router.push({ path: '/classroom/player', query: { sid: session.value.session_id, code: form.code } })
  }
}
</script>

<template>
  <n-space vertical>
    <n-card title="学生课堂入口 (E5: 加入课堂)" size="small">
      <n-form label-placement="left" :show-feedback="false" size="small">
        <n-form-item label="课堂码"><n-input v-model:value="form.code" placeholder="6 位数字" maxlength="6" style="max-width: 200px" /></n-form-item>
        <n-form-item label="学号"><n-input v-model:value="form.student_id" placeholder="如 s001" style="max-width: 200px" /></n-form-item>
      </n-form>
      <n-button type="primary" style="margin-top: 12px" :loading="gen.loading.value" @click="join">加入课堂</n-button>
    </n-card>

    <n-card v-if="pkg" title="课程信息" size="small">
      <n-space>
        <n-tag type="info">{{ pkg.subject }}</n-tag>
        <n-tag>年级 {{ pkg.grade }}</n-tag>
        <n-tag type="success">{{ pkg.topic }}</n-tag>
        <n-tag v-if="pkg.has_quiz">含测验</n-tag>
      </n-space>
      <p style="margin-top: 8px">讲稿页数: {{ pkg.script?.pages?.length || 0 }}</p>
      <n-button type="primary" style="margin-top: 8px" @click="enterClass">进入课堂 →</n-button>
    </n-card>
  </n-space>
</template>

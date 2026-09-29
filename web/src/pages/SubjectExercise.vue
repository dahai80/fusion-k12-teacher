<script setup lang="ts">
import { reactive, ref } from 'vue'
import { NCard, NSpace, NInput, NSelect, NInputNumber, NButton, NTabs, NTabPane, useMessage } from 'naive-ui'
import { subjectApi } from '@/api/endpoints'
import { useGenerator } from '@/composables/useGenerator'
import { useAuthStore } from '@/stores/auth'
import { useTextbookCtx } from '@/composables/useTextbookCtx'
import UnitLessonSelect from '@/components/UnitLessonSelect.vue'
import ResultViewer from '@/components/ResultViewer.vue'
import HistoryPanel from '@/components/HistoryPanel.vue'

const form = reactive({ concept: '', duration: 40, language: '英语', skill: '', theme: '' })
const gen = useGenerator()
const auth = useAuthStore()
const message = useMessage()
const { ctx, fields } = useTextbookCtx()
const hist = ref<any>(null)

function onHistory(p: any) { gen.result.value = p; gen.errorMsg.value = '' }

function toastIfSaved() {
    if (gen.result.value && !gen.result.value.error) {
        hist.value?.refresh()
        if (auth.isLoggedIn) message.info('已保存到资源库 (我的资源库可查看)')
    }
}

async function explain() { await gen.run(() => subjectApi.explain({ ...fields(), concept: form.concept || ctx.topic })); toastIfSaved() }
async function exercise() { await gen.run(() => subjectApi.exercise({ ...fields(), topic: ctx.topic })); toastIfSaved() }
async function stem() { await gen.run(() => subjectApi.stemProject({ ...fields(), topic: ctx.topic, duration: form.duration + '分钟' })); toastIfSaved() }
async function lang() { await gen.run(() => subjectApi.languageActivity({ ...fields(), language: form.language, skill: form.skill, theme: form.theme })); toastIfSaved() }
</script>
<template>
  <n-card title="学科专家 (讲解/练习/STEM/语言活动)" size="small">
    <n-form label-placement="left" :show-feedback="false" size="small">
      <n-form-item label="课题" style="margin-bottom: 12px">
        <unit-lesson-select />
      </n-form-item>
    </n-form>
    <n-tabs type="line" animated>
      <n-tab-pane name="explain" tab="概念讲解">
        <n-space>
          <n-input v-model:value="form.concept" :placeholder="ctx.topic || '概念'" size="small" style="width: 160px" />
          <n-button type="primary" size="small" :loading="gen.loading.value" :disabled="!ctx.lesson_id" @click="explain">讲解</n-button>
        </n-space>
      </n-tab-pane>
      <n-tab-pane name="exercise" tab="练习题">
        <n-space>
          <n-button type="primary" size="small" :loading="gen.loading.value" :disabled="!ctx.lesson_id" @click="exercise">生成</n-button>
        </n-space>
      </n-tab-pane>
      <n-tab-pane name="stem" tab="STEM 项目">
        <n-space>
          <n-input-number v-model:value="form.duration" :min="10" size="small" style="width: 100px" />
          <n-button type="primary" size="small" :loading="gen.loading.value" :disabled="!ctx.lesson_id" @click="stem">生成</n-button>
        </n-space>
      </n-tab-pane>
      <n-tab-pane name="lang" tab="语言活动">
        <n-space>
          <n-select v-model:value="form.language" :options="[{label:'英语',value:'英语'},{label:'语文',value:'语文'}]" size="small" style="width: 100px" />
          <n-input v-model:value="form.skill" placeholder="技能" size="small" style="width: 120px" />
          <n-input v-model:value="form.theme" placeholder="主题" size="small" style="width: 160px" />
          <n-button type="primary" size="small" :loading="gen.loading.value" @click="lang">生成</n-button>
        </n-space>
      </n-tab-pane>
    </n-tabs>
    <ResultViewer :loading="gen.loading.value" :result="gen.result.value" :error="gen.errorMsg.value" @retry="exercise" />
    <history-panel ref="hist" :type="['explain','exercise','stem','lang_activity']" @load="onHistory" />
  </n-card>
</template>

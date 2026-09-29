<script setup lang="ts">
import { reactive, ref } from 'vue'
import { NCard, NSpace, NForm, NFormItem, NInput, NButton, NTag, NDescriptions, NDescriptionsItem, NAlert, useMessage } from 'naive-ui'
import { standardsApi } from '@/api/endpoints'
import { useGenerator } from '@/composables/useGenerator'
import { useAuthStore } from '@/stores/auth'
import { useTextbookCtx } from '@/composables/useTextbookCtx'
import UnitLessonSelect from '@/components/UnitLessonSelect.vue'
import ResultViewer from '@/components/ResultViewer.vue'
import HistoryPanel from '@/components/HistoryPanel.vue'

const form = reactive({ objectives: '' })
const gen = useGenerator()
const auth = useAuthStore()
const message = useMessage()
const { ctx, fields } = useTextbookCtx()
const hist = ref<any>(null)

const coverageResult = ref<any>(null)
const remediateResult = ref<any>(null)
const remediateLoading = ref(false)

function onHistory(p: any) { gen.result.value = p; gen.errorMsg.value = '' }

function objectivesList(): string[] {
    if (form.objectives) {
        const parts = form.objectives.split(/[;\n]/).map(s => s.trim()).filter(Boolean)
        if (parts.length) return parts
    }
    return [ctx.topic || '默认目标']
}

function notifySave() {
    if (gen.result.value && !gen.result.value.error) {
        hist.value?.refresh()
        if (auth.isLoggedIn) message.info('已保存到资源库 (我的资源库可查看)')
    }
}

async function align() {
    remediateResult.value = null
    coverageResult.value = null
    await gen.run(() => standardsApi.align({ ...fields(), objectives: objectivesList(), topic: ctx.topic }))
    notifySave()
}
async function coverage() {
    remediateResult.value = null
    await gen.run(async () => {
        const r = await standardsApi.coverage({ ...fields(), objectives: objectivesList(), topic: ctx.topic })
        coverageResult.value = r
        return r
    })
    notifySave()
}

async function remediate() {
    if (!coverageResult.value?.missing_points?.length) return
    remediateLoading.value = true
    try {
        const r = await standardsApi.remediate({
            ...fields(),
            topic: ctx.topic,
            missing_points: coverageResult.value.missing_points,
        })
        remediateResult.value = r
        if (!r.error) {
            hist.value?.refresh()
            if (auth.isLoggedIn) message.info('补齐方案已生成 (已保存到资源库)')
        }
    } catch (e: any) {
        remediateResult.value = { error: e?.message || '生成失败' }
    } finally {
        remediateLoading.value = false
    }
}

const coveragePct = () => {
    if (!coverageResult.value) return 0
    return Math.round((coverageResult.value.coverage_ratio || 0) * 100)
}
</script>

<template>
  <n-card title="课标对齐与覆盖校验" size="small">
    <n-form label-placement="left" :show-feedback="false" size="small">
      <n-form-item label="课题" style="margin-bottom: 12px">
        <unit-lesson-select />
      </n-form-item>
      <n-space>
        <n-button type="primary" :loading="gen.loading.value" :disabled="!ctx.lesson_id" @click="align">对齐</n-button>
        <n-button :loading="gen.loading.value" :disabled="!ctx.lesson_id" @click="coverage">覆盖校验</n-button>
      </n-space>
      <n-form-item label="目标" style="margin-top: 12px">
        <n-input v-model:value="form.objectives" type="textarea" :rows="2" placeholder="分号或换行分隔, 留空由课题推断" />
      </n-form-item>
    </n-form>
    <ResultViewer :loading="gen.loading.value" :result="gen.result.value" :error="gen.errorMsg.value" @retry="align" />

    <div v-if="coverageResult" style="margin-top: 16px">
      <n-descriptions title="覆盖报告" label-placement="left" :column="2" size="small" bordered>
        <n-descriptions-item label="覆盖率">
          <n-tag :type="coveragePct() >= 80 ? 'success' : coveragePct() >= 50 ? 'warning' : 'error'" size="small">
            {{ coveragePct() }}%
          </n-tag>
        </n-descriptions-item>
        <n-descriptions-item label="必修知识点">{{ coverageResult.total_points }}</n-descriptions-item>
        <n-descriptions-item label="已覆盖">{{ coverageResult.covered_points }}</n-descriptions-item>
        <n-descriptions-item label="缺失">{{ coverageResult.missing_points?.length || 0 }}</n-descriptions-item>
      </n-descriptions>

      <n-alert v-if="coverageResult.missing_points?.length" type="warning" title="缺失知识点" style="margin-top: 12px" :show-icon="true">
        <div v-for="m in coverageResult.details?.filter((d: any) => !d.covered)" :key="m.point_id" style="margin: 4px 0">
          • {{ m.topic || m.point_id }}<span v-if="m.description"> — {{ m.description }}</span>
        </div>
        <n-button type="primary" size="small" :loading="remediateLoading" style="margin-top: 12px" @click="remediate">
          生成补齐方案
        </n-button>
      </n-alert>

      <n-alert v-else type="success" title="知识点全覆盖" style="margin-top: 12px">
        当前教学目标已覆盖全部必修知识点。
      </n-alert>
    </div>

    <div v-if="remediateResult" style="margin-top: 16px">
      <n-alert v-if="remediateResult.error" type="error" title="生成失败" style="margin-bottom: 12px">
        {{ remediateResult.error }}
      </n-alert>
      <template v-else>
        <n-descriptions title="补齐教学方案" label-placement="left" :column="1" size="small" bordered>
          <n-descriptions-item label="预计时长">{{ remediateResult.estimated_duration || '-' }}</n-descriptions-item>
          <n-descriptions-item label="时间线">{{ remediateResult.timeline || '-' }}</n-descriptions-item>
        </n-descriptions>
        <div v-if="remediateResult.strategies?.length" style="margin-top: 12px">
          <strong>教学策略:</strong>
          <ol style="margin: 8px 0 0 20px">
            <li v-for="(s, i) in remediateResult.strategies" :key="i" style="margin: 4px 0">{{ s }}</li>
          </ol>
        </div>
        <div v-if="remediateResult.exercises?.length" style="margin-top: 12px">
          <strong>针对性练习:</strong>
          <div v-for="(ex, i) in remediateResult.exercises" :key="i" style="margin: 6px 0; padding-left: 12px">
            • {{ ex.topic }} — {{ ex.type }} ({{ ex.difficulty }}) × {{ ex.count }}
          </div>
        </div>
      </template>
    </div>

    <history-panel ref="hist" :type="['align','coverage','remediate']" @load="onHistory" />
  </n-card>
</template>

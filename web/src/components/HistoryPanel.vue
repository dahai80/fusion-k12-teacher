<script setup lang="ts">
import { ref, watch } from 'vue'
import { NCard, NSpin, NEmpty, NList, NListItem, NThing, NTag, NButton, NText, useMessage } from 'naive-ui'
import { materialsApi } from '@/api/endpoints'
import { useTextbookCtx } from '@/composables/useTextbookCtx'

const props = defineProps<{ type: string | string[] }>()
const emit = defineEmits<{ (e: 'load', payload: any): void }>()
const message = useMessage()
const { ctx } = useTextbookCtx()

const items = ref<any[]>([])
const loading = ref(false)

const TYPE_LABELS: Record<string, string> = {
    lesson_plan: '教案', quiz: '测验', unit_plan: '单元计划',
    diff_lesson: '分层教案', diff_quiz: '分层测验', diff_worksheet: '分层工作纸',
    worksheet: '工作纸', flashcards: '闪卡', slides: '课件', game: '游戏',
    parent_comm: '家长沟通', grade_math: '数学批改', grade_essay: '作文批改',
    rubric: '评分量规', report: '学生报告', class_profile: '班级画像',
    student_profile: '学生画像', error_analysis: '错因分析', remedial: '补救计划',
    class_report: '班级报告', diagnose: '技能诊断', path: '学习路径',
    recommend: '资源推荐', explain: '概念讲解', exercise: '练习',
    stem: 'STEM项目', lang_activity: '语言活动', align: '课标对齐',
    coverage: '覆盖报告', remediate: '补齐方案', safety: '安全检查',
    desensitize: '脱敏',
}

async function load() {
    if (!ctx.subject || !ctx.grade) { items.value = []; return }
    loading.value = true
    try {
        const types = Array.isArray(props.type) ? props.type : [props.type]
        const all: any[] = []
        for (const t of types) {
            const r = await materialsApi.list({
                type: t, edition: ctx.edition, subject: ctx.subject,
                grade: String(ctx.grade), lesson_id: ctx.lesson_id,
            })
            all.push(...(r.items || []))
        }
        items.value = all.sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''))
    } catch (e: any) {
        items.value = []
        message.error('加载历史失败: ' + (e?.message || e))
    } finally {
        loading.value = false
    }
}

async function open(item: any) {
    try {
        const r = await materialsApi.get(item.id)
        emit('load', r.payload)
    } catch (e: any) {
        message.error('加载详情失败: ' + (e?.message || e))
    }
}

watch(() => [ctx.edition, ctx.subject, ctx.grade, ctx.lesson_id], load, { immediate: true })

defineExpose({ refresh: load })
</script>

<template>
  <n-card title="已生成 (当前课题)" size="small" style="margin-top: 12px">
    <template #header-extra>
      <n-button quaternary size="tiny" @click="load">刷新</n-button>
    </template>
    <n-spin :show="loading">
      <n-empty v-if="!items.length && !loading" size="small" description="当前课题暂无历史, 生成后将显示在这里" />
      <n-list v-else hoverable clickable>
        <n-list-item v-for="item in items" :key="item.id" @click="open(item)">
          <n-thing>
            <template #header>
              <n-text style="font-size: 13px">{{ item.title || '(无标题)' }}</n-text>
            </template>
            <template #header-extra>
              <n-tag size="small" type="info">{{ TYPE_LABELS[item.type] || item.type }}</n-tag>
            </template>
            <template #description>
              <n-text depth="3" style="font-size: 11px">{{ item.created_at }}</n-text>
            </template>
          </n-thing>
        </n-list-item>
      </n-list>
    </n-spin>
  </n-card>
</template>

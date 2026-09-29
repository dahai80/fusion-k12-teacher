<script setup lang="ts">
import { ref, watch, computed, onMounted } from 'vue'
import { NSpace, NSelect, NSpin } from 'naive-ui'
import { textbookApi } from '@/api/endpoints'
import { useTextbookStore, type TextbookContext } from '@/stores/textbook'

const emit = defineEmits<{ (e: 'select', sel: TextbookContext): void }>()

const ctx = useTextbookStore()
const loading = ref(false)
const editions = ref<any[]>([])
const grades = ref<string[]>([])

const editionOptions = computed(() =>
    editions.value.map(e => ({ label: e.name, value: e.edition }))
)
const gradeOptions = computed(() => grades.value.map(g => ({ label: `${g}年级`, value: g })))

onMounted(async () => {
    await loadEditions()
})

async function loadEditions() {
    loading.value = true
    try {
        const r = await textbookApi.editions()
        editions.value = r.editions || []
        if (!editions.value.find(e => e.edition === ctx.edition)) {
            ctx.set({ edition: editions.value[0]?.edition || '' })
        }
        if (ctx.edition) {
            await loadGrades()
        }
    } catch (e) {
        console.warn('加载教材版本失败', e)
    } finally {
        loading.value = false
    }
}

async function loadGrades() {
    grades.value = []
    if (!ctx.edition) return
    try {
        const r = await textbookApi.grades(ctx.edition, ctx.subject)
        grades.value = r.grades || []
        if (ctx.grade && !grades.value.includes(ctx.grade)) {
            ctx.set({ grade: '' })
        }
    } catch (e) {}
}

function onEditionChange() {
    ctx.set({ grade: '', unit: null, unit_title: '', lesson_id: '', lesson_title: '', topic: '' })
    loadGrades()
    emitCurrent()
}

function onGradeChange() {
    ctx.set({ unit: null, unit_title: '', lesson_id: '', lesson_title: '', topic: '' })
    emitCurrent()
}

function emitCurrent() {
    emit('select', {
        edition: ctx.edition, subject: ctx.subject, grade: ctx.grade,
        unit: ctx.unit, unit_title: ctx.unit_title, lesson_id: ctx.lesson_id,
        lesson_title: ctx.lesson_title, topic: ctx.topic,
    })
}
</script>

<template>
    <n-spin :show="loading" size="small">
        <n-space align="center" size="small" :wrap="false">
            <n-select
                v-model:value="ctx.edition"
                :options="editionOptions"
                size="small"
                style="width: 140px"
                placeholder="版本"
                @update:value="onEditionChange"
            />
            <n-select
                v-model:value="ctx.subject"
                :options="[{ label: '数学', value: '数学' }, { label: '语文', value: '语文' }, { label: '英语', value: '英语' }, { label: '科学', value: '科学' }]"
                size="small"
                style="width: 90px"
                @update:value="onEditionChange"
            />
            <n-select
                v-model:value="ctx.grade"
                :options="gradeOptions"
                size="small"
                placeholder="年级"
                style="width: 90px"
                @update:value="onGradeChange"
            />
        </n-space>
    </n-spin>
</template>

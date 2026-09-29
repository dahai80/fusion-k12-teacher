<script setup lang="ts">
import { ref, watch, computed, onMounted } from 'vue'
import { NSpace, NSelect, NSpin } from 'naive-ui'
import { textbookApi } from '@/api/endpoints'
import { useTextbookStore, type TextbookContext } from '@/stores/textbook'

const emit = defineEmits<{ (e: 'select', sel: TextbookContext): void }>()

const ctx = useTextbookStore()
const loading = ref(false)
const units = ref<any[]>([])
const lessons = ref<any[]>([])

const unitOptions = computed(() => units.value.map(u => ({ label: `第${u.unit}单元 ${u.title}`, value: u.unit })))
const lessonOptions = computed(() => lessons.value.map(l => ({ label: `第${l.lesson}课 ${l.title}`, value: `${ctx.unit}-${l.lesson}` })))

onMounted(async () => {
    await loadUnits()
})

watch(() => [ctx.edition, ctx.subject, ctx.grade], () => {
    ctx.set({ unit: null, unit_title: '', lesson_id: '', lesson_title: '', topic: '' })
    units.value = []
    lessons.value = []
    loadUnits()
})

async function loadUnits() {
    loading.value = true
    try {
        if (!ctx.edition || !ctx.grade) { units.value = []; return }
        const r = await textbookApi.units(ctx.edition, ctx.subject, ctx.grade)
        units.value = r.units || []
        if (ctx.unit != null && units.value.find(u => u.unit === ctx.unit)) {
            loadLessons()
        } else {
            ctx.set({ unit: null, unit_title: '', lesson_id: '', lesson_title: '', topic: '' })
        }
    } catch (e) {
        console.warn('加载单元失败', e)
    } finally {
        loading.value = false
    }
}

function loadLessons() {
    lessons.value = []
    if (ctx.unit == null) return
    const u = units.value.find(x => x.unit === ctx.unit)
    if (u) lessons.value = u.lessons || []
}

function onUnitChange() {
    const u = units.value.find(x => x.unit === ctx.unit)
    ctx.set({ unit_title: u?.title || '', lesson_id: '', lesson_title: '', topic: '' })
    lessons.value = []
    loadLessons()
    emitCurrent()
}

function onLessonChange() {
    const l = lessons.value.find(x => `${ctx.unit}-${x.lesson}` === ctx.lesson_id)
    ctx.set({
        lesson_title: l?.title || '',
        topic: l?.topic || l?.title || '',
    })
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
                v-model:value="ctx.unit"
                :options="unitOptions"
                size="small"
                placeholder="选择单元"
                style="width: 200px"
                @update:value="onUnitChange"
            />
            <n-select
                v-model:value="ctx.lesson_id"
                :options="lessonOptions"
                size="small"
                placeholder="选择课"
                style="width: 200px"
                :disabled="!ctx.unit"
                @update:value="onLessonChange"
            />
        </n-space>
    </n-spin>
</template>

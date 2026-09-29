import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { useAuthStore } from './auth'

const LS_KEY = 'fusion-k12-textbook'

export interface TextbookContext {
    edition: string
    subject: string
    grade: string
    unit: number | null
    unit_title: string
    lesson_id: string
    lesson_title: string
    topic: string
}

function load(): Partial<TextbookContext> {
    try {
        const raw = localStorage.getItem(LS_KEY)
        if (raw) return JSON.parse(raw)
    } catch (e) {
        console.warn('textbook store load 失败', e)
    }
    return {}
}

export const useTextbookStore = defineStore('textbook', () => {
    const auth = useAuthStore()
    const init = load()
    const edition = ref(init.edition || auth.teacher?.default_edition || 'renjiao')
    const subject = ref(init.subject || '数学')
    const grade = ref(init.grade || '')
    const unit = ref<number | null>(init.unit ?? null)
    const unit_title = ref(init.unit_title || '')
    const lesson_id = ref(init.lesson_id || '')
    const lesson_title = ref(init.lesson_title || '')
    const topic = ref(init.topic || '')

    function set(sel: Partial<TextbookContext>) {
        if (sel.edition !== undefined) edition.value = sel.edition
        if (sel.subject !== undefined) subject.value = sel.subject
        if (sel.grade !== undefined) grade.value = sel.grade
        if (sel.unit !== undefined) unit.value = sel.unit
        if (sel.unit_title !== undefined) unit_title.value = sel.unit_title
        if (sel.lesson_id !== undefined) lesson_id.value = sel.lesson_id
        if (sel.lesson_title !== undefined) lesson_title.value = sel.lesson_title
        if (sel.topic !== undefined) topic.value = sel.topic
    }

    watch([edition, subject, grade, unit, unit_title, lesson_id, lesson_title, topic], () => {
        localStorage.setItem(LS_KEY, JSON.stringify({
            edition: edition.value, subject: subject.value, grade: grade.value,
            unit: unit.value, unit_title: unit_title.value, lesson_id: lesson_id.value,
            lesson_title: lesson_title.value, topic: topic.value,
        }))
    })

    return { edition, subject, grade, unit, unit_title, lesson_id, lesson_title, topic, set }
})

import { useTextbookStore } from '@/stores/textbook'

export function useTextbookCtx() {
    const ctx = useTextbookStore()
    const fields = () => ({
        edition: ctx.edition,
        subject: ctx.subject,
        grade: String(ctx.grade),
        lesson_id: ctx.lesson_id,
        unit_title: ctx.unit_title,
        lesson_title: ctx.lesson_title,
    })
    return { ctx, fields }
}

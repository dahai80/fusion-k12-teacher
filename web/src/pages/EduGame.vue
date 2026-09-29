<script setup lang="ts">
import { reactive, ref } from 'vue'
import { NCard, NSpace, NForm, NFormItem, NSelect, NButton, useMessage } from 'naive-ui'
import { contentApi } from '@/api/endpoints'
import { useGenerator } from '@/composables/useGenerator'
import { useAuthStore } from '@/stores/auth'
import { useTextbookCtx } from '@/composables/useTextbookCtx'
import UnitLessonSelect from '@/components/UnitLessonSelect.vue'
import ResultViewer from '@/components/ResultViewer.vue'
import HistoryPanel from '@/components/HistoryPanel.vue'

const form = reactive({ game_type: 'quiz' })
const gen = useGenerator()
const auth = useAuthStore()
const message = useMessage()
const { ctx, fields } = useTextbookCtx()
const hist = ref<any>(null)

function onHistory(p: any) { gen.result.value = p; gen.errorMsg.value = '' }

async function generate() {
    await gen.run(() => contentApi.generate({ style: 'game', ...form, ...fields(), topic: ctx.topic }))
    if (gen.result.value && !gen.result.value.error) {
        hist.value?.refresh()
        if (auth.isLoggedIn) message.info('已保存到资源库 (我的资源库可查看)')
    }
}
</script>
<template>
    <n-card title="教育游戏" size="small">
        <n-form label-placement="left" :show-feedback="false" size="small">
            <n-form-item label="课题" style="margin-bottom: 12px">
                <unit-lesson-select />
            </n-form-item>
            <n-space>
                <n-form-item label="类型"><n-select v-model:value="form.game_type" :options="[{label:'答题',value:'quiz'},{label:'闯关',value:'adventure'},{label:'匹配',value:'match'}]" style="width: 110px" /></n-form-item>
                <n-button type="primary" :loading="gen.loading.value" :disabled="!ctx.lesson_id" @click="generate">生成</n-button>
            </n-space>
        </n-form>
        <ResultViewer :loading="gen.loading.value" :result="gen.result.value" :error="gen.errorMsg.value" @retry="generate" />
        <history-panel ref="hist" type="game" @load="onHistory" />
    </n-card>
</template>

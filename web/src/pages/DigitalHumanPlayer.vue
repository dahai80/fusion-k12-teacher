<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NCard, NSpace, NButton, NTag, NSteps, NStep, NInput, NAlert,
  NDrawer, NDrawerContent, NResult, NSpin, useMessage,
} from 'naive-ui'
import { useDigitalHuman } from '@/composables/useDigitalHuman'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const dh = useDigitalHuman()

const loading = ref(true)
const finished = ref(false)
const raiseHandText = ref('')
const showRaiseHand = ref(false)
const videoEl = ref<HTMLVideoElement | null>(null)

const sessionId = computed(() => (route.query.sid as string) || '')
const subject = computed(() => (route.query.subject as string) || 'math')
const topic = computed(() => (route.query.topic as string) || '')
const grade = computed(() => (route.query.grade as string) || '3')

const stateLabel = computed(() => {
  const m: Record<string, string> = {
    idle: '待命', ai_thinking: '思考中', ai_speaking: '讲课中',
    user_speaking: '听你说', error: '异常',
  }
  return m[dh.agentState] || dh.agentState
})
const stateType = computed(() => {
  const m: Record<string, string> = {
    idle: 'default', ai_thinking: 'warning', ai_speaking: 'success',
    user_speaking: 'info', error: 'error',
  }
  return m[dh.agentState] || 'default'
})

const hasCheckpoint = computed(() => {
  const cp = dh.lastNarrate?.checkpoint || dh.currentPage?.checkpoint
  return !!cp && typeof cp === 'object' && Object.keys(cp).length > 0
})
const hasQuestion = computed(() => {
  const q = dh.lastNarrate?.question || dh.currentPage?.question
  return !!q && typeof q === 'object' && (q.id || q.prompt)
})

onMounted(async () => {
  if (sessionId.value) {
    loading.value = false
    return
  }
  if (!topic.value) {
    message.error('缺少主题参数')
    router.push('/digital-human/self-study')
    return
  }
  const res = await dh.createSession({
    subject: subject.value, topic: topic.value, grade: grade.value, layer: 'B',
  }, videoEl.value)
  loading.value = false
  if (res && res.page_count > 0) {
    message.success(`数字人老师已就绪: ${res.page_count} 页`)
    await dh.narrate(0)
  } else if (res) {
    message.warning('讲稿为空 (LLM 生成失败或模型未就绪)')
  }
})

onUnmounted(() => {
  dh.close()
})

async function onNarrate(idx: number) {
  await dh.narrate(idx)
}

function submitRaiseHand() {
  if (!raiseHandText.value.trim()) return
  dh.raiseHand(raiseHandText.value)
  raiseHandText.value = ''
  showRaiseHand.value = false
}

function onPressSpeak() {
  dh.startRecording()
}
function onReleaseSpeak() {
  dh.stopRecording()
}

async function finishSession() {
  await dh.finish()
  finished.value = true
}
</script>

<template>
  <n-spin v-if="loading" />
  <n-space v-else-if="finished" vertical>
    <n-result status="success" title="学习已结束" description="数字人老师会话已关闭">
      <template #footer>
        <n-button type="primary" @click="router.push('/digital-human/self-study')">返回</n-button>
      </template>
    </n-result>
  </n-space>
  <n-space v-else vertical>
    <n-card size="small">
      <n-space align="center">
        <n-tag type="success">{{ topic }}</n-tag>
        <n-tag>{{ subject }} · {{ grade }}年级</n-tag>
        <n-tag :type="stateType as any">{{ stateLabel }}</n-tag>
        <n-tag v-if="dh.connected" type="info" size="small">WS 已连</n-tag>
        <n-tag v-if="dh.livekitConnected" type="success" size="small">LiveKit 视频</n-tag>
        <span style="flex: 1" />
        <n-button size="small" @click="finishSession">结束</n-button>
      </n-space>
    </n-card>

    <div style="display: flex; gap: 12px; align-items: flex-start">
      <n-card style="flex: 1; min-width: 0" size="small">
        <n-card v-if="dh.session && dh.session.page_count > 0" size="small" :bordered="false" style="margin-bottom: 8px">
          <n-steps :current="dh.currentPageIdx + 1" size="small" horizontal>
            <n-step
              v-for="(p, i) in dh.session.pages"
              :key="i"
              :title="p.title || `第${i + 1}页`"
              style="cursor: pointer"
              @click="onNarrate(i)"
            />
          </n-steps>
        </n-card>

        <n-card v-if="dh.currentPage" :title="`${dh.currentPageIdx + 1}. ${dh.currentPage.title || ''}`" size="small">
          <div style="font-size: 16px; line-height: 1.9; margin-bottom: 12px; min-height: 80px">
            {{ dh.currentPage.text }}
          </div>

          <n-alert v-if="hasCheckpoint" type="success" :bordered="false" style="margin-bottom: 8px" title="知识点检查点">
            <div style="font-size: 13px">
              {{ dh.lastNarrate?.checkpoint?.prompt || dh.currentPage?.checkpoint?.prompt || '本页关键知识点已掌握' }}
            </div>
          </n-alert>

          <n-alert v-if="hasQuestion" type="warning" :bordered="false" style="margin-bottom: 8px" title="随堂提问">
            <div style="font-size: 13px">
              {{ dh.lastNarrate?.question?.prompt || dh.currentPage?.question?.prompt || '思考一下本页内容' }}
            </div>
          </n-alert>

          <n-alert v-if="dh.lastQa" type="info" :bordered="false" style="margin-bottom: 8px">
            <div style="font-size: 13px"><strong>问:</strong> {{ dh.lastQa.question }}</div>
            <div style="font-size: 13px; margin-top: 4px"><strong>答:</strong> {{ dh.lastQa.answer }}</div>
          </n-alert>
          <n-alert v-if="dh.errorMsg" type="error" :bordered="false" style="margin-bottom: 8px">{{ dh.errorMsg }}</n-alert>

          <n-space style="margin-top: 12px" justify="space-between">
            <n-button :disabled="dh.currentPageIdx === 0" @click="onNarrate(dh.currentPageIdx - 1)">上一页</n-button>
            <n-space>
              <n-button type="primary" @click="showRaiseHand = true">✋ 举手提问</n-button>
              <n-button
                :type="dh.recording ? 'error' : 'default'"
                :disabled="!dh.session?.asr_available"
                @mousedown="onPressSpeak"
                @mouseup="onReleaseSpeak"
                @mouseleave="onReleaseSpeak"
              >{{ dh.recording ? '🔴 录音中' : '🎤 按住说话' }}</n-button>
            </n-space>
            <n-button
              :disabled="dh.currentPageIdx >= (dh.session?.page_count || 0) - 1"
              type="primary"
              @click="onNarrate(dh.currentPageIdx + 1)"
            >下一页</n-button>
          </n-space>
        </n-card>
      </n-card>

      <n-card title="数字人老师" size="small" style="width: 320px; flex-shrink: 0">
        <div style="background: #1a1a1a; border-radius: 8px; aspect-ratio: 1; display: flex; align-items: center; justify-content: center; overflow: hidden; position: relative">
          <video
            ref="videoEl"
            autoplay
            playsinline
            muted
            :style="{ width: '100%', height: '100%', objectFit: 'cover', display: dh.livekitConnected ? 'block' : 'none' }"
          />
          <div v-if="!dh.livekitConnected" style="text-align: center; color: #888">
            <div style="font-size: 48px">🤖</div>
            <div style="font-size: 12px; margin-top: 8px">
              {{ dh.session?.avatar_available ? '数字人就绪' : '静态头像 (MuseTalk 未启用)' }}
            </div>
          </div>
        </div>
        <n-space vertical style="margin-top: 8px" size="small">
          <n-tag :type="stateType as any" size="small">状态: {{ stateLabel }}</n-tag>
          <n-tag v-if="dh.session?.tts_available" type="success" size="small">语音合成 ✓</n-tag>
          <n-tag v-if="dh.session?.asr_available" type="success" size="small">语音识别 ✓</n-tag>
          <n-tag v-if="dh.session?.avatar_available" type="success" size="small">数字人视频 ✓</n-tag>
        </n-space>
      </n-card>
    </div>

    <n-drawer v-model:show="showRaiseHand" :width="400" placement="right">
      <n-drawer-content title="举手提问" closable>
        <n-input
          v-model:value="raiseHandText"
          type="textarea"
          :rows="4"
          placeholder="输入你的问题..."
        />
        <n-button
          type="primary"
          style="margin-top: 12px"
          :loading="dh.busy"
          :disabled="!raiseHandText.trim()"
          @click="submitRaiseHand"
        >提交问题</n-button>
      </n-drawer-content>
    </n-drawer>
  </n-space>
</template>

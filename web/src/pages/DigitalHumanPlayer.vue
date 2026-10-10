<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NCard, NSpace, NButton, NTag, NSteps, NStep, NInput, NAlert,
  NDrawer, NDrawerContent, NResult, NSpin, NUpload, useMessage } from 'naive-ui'
import type { UploadFileInfo } from 'naive-ui'
import SceneCanvas from '@/components/SceneCanvas.vue'
import { api } from '@/api/client'
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
// 会话模式: topic(默认自由主题) | course(按教案讲) | expand(举一反三) | qa(纯问答)
const mode = computed(() => (route.query.mode as string) || 'topic')
const classId = computed(() => (route.query.classId as string) || '')
// 知识图谱节点 id (入口页点选知识点标签时带上) — 讲解/举一反三锚定图谱
const nodeId = computed(() => (route.query.nodeId as string) || '')
// 模式3: 纯问答 — 无讲稿页签, 进来即问 (文字/语音/图片)
const isQaMode = computed(() => mode.value === 'qa')

// 图片提问: 选图 → base64 → raiseHand 带图
const pendingImageB64 = ref('')
const pendingImageName = ref('')

function onImageChosen(options: { file: UploadFileInfo }) {
  const f = options.file?.file
  if (!f) { pendingImageB64.value = ''; return }
  if (f.size > 8 * 1024 * 1024) { message.error('图片不能超过 8MB'); pendingImageB64.value = ''; return }
  const reader = new FileReader()
  reader.onload = () => {
    const dataUrl = String(reader.result || '')
    pendingImageB64.value = dataUrl.split(',')[1] || ''
    pendingImageName.value = f.name
  }
  reader.readAsDataURL(f)
}

// 问答历史: 每次提问立即入列(问题可见, 答案占位"思考中"), 回答到达后回填 —
// 修复 bug1 (原实现只显示 lastQa, 发送后问题文本从界面消失) 与 bug2 (等待期无反馈)
interface QaEntry { q: string; a: string; done: boolean; t: number }
const qaHistory = ref<QaEntry[]>([])
const qaElapsed = ref(0)
let qaTimer: number | null = null

function startQaTimer() {
  qaElapsed.value = 0
  if (qaTimer) window.clearInterval(qaTimer)
  qaTimer = window.setInterval(() => { qaElapsed.value += 1 }, 1000)
}
function stopQaTimer() {
  if (qaTimer) { window.clearInterval(qaTimer); qaTimer = null }
}
const qaWaitHint = computed(() => {
  if (qaElapsed.value < 5) return '老师正在思考…'
  if (qaElapsed.value < 20) return `老师正在思考… (${qaElapsed.value}s)`
  return `正在组织详细的解答，可能需要 1-2 分钟… (${Math.floor(qaElapsed.value / 60)}分${qaElapsed.value % 60}秒)`
})

async function submitQa() {
  const text = raiseHandText.value.trim()
  if (!text && !pendingImageB64.value) { message.warning('输入问题，或附上图片'); return }
  const qLabel = text || '📷 图片提问'
  qaHistory.value.push({ q: qLabel, a: '', done: false, t: Date.now() })
  startQaTimer()
  await dh.raiseHand(text, pendingImageB64.value)
  stopQaTimer()
  // 回填答案 (raiseHand 返回后 lastQa 已更新; 失败时标注)
  const last = qaHistory.value[qaHistory.value.length - 1]
  if (dh.lastQa?.answer) {
    last.a = dh.lastQa.answer
  } else if (dh.errorMsg) {
    last.a = `（出错了: ${dh.errorMsg}，请重试）`
  } else {
    last.a = '（老师没有返回回答，请重试）'
  }
  last.done = true
  raiseHandText.value = ''
  pendingImageB64.value = ''
  pendingImageName.value = ''
  // 答疑完成 → 异步尝试把题目编译成场景动画 (可动画题如火车过桥/植树),
  // 成功则在问答卡下方嵌入展示; 失败静默 (动画只是增强, 不影响答疑)
  if (text) loadScene(text)
}

// 场景动画联动: scene-compile 是 LLM 提取+SymPy 验证 (分钟级), 异步不阻塞答疑
const sceneData = ref<any>(null)
const sceneLoading = ref(false)

async function loadScene(question: string) {
  sceneData.value = null
  sceneLoading.value = true
  try {
    const dsl = await api.post(`/api/course/${subject.value}/scene-compile`, {
      problem_text: question,
      knowledge_node_id: nodeId.value,
    })
    sceneData.value = dsl
  } catch { /* 不可动画题或编译失败 — 无动画, 仅问答 */ }
  sceneLoading.value = false
}

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
  // 仅自由主题模式需要 topic; course/expand 由后端从课堂包取 topic, qa 纯问答无需 topic
  if (mode.value === 'topic' && !topic.value) {
    message.error('缺少主题参数')
    router.push('/digital-human/self-study')
    return
  }
  const body: any = {
    subject: subject.value, grade: grade.value, layer: 'B', mode: mode.value,
  }
  if (nodeId.value) body.knowledge_node_id = nodeId.value
  if (mode.value === 'course' || mode.value === 'expand') {
    body.class_id = classId.value
    if (topic.value) body.topic = topic.value
  } else {
    body.topic = topic.value
  }
  const res = await dh.createSession(body, videoEl.value)
  loading.value = false
  if (res && res.page_count > 0) {
    message.success(`数字人老师已就绪: ${res.page_count} 页`)
    await dh.narrate(0)
  } else if (isQaMode.value) {
    message.success('老师已就绪，直接提问吧')
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

        <!-- 模式3: 纯问答 — 无讲稿, 直接提问 (文字/语音/图片) -->
        <n-card v-if="isQaMode" title="🙋 向老师提问" size="small">
          <!-- 问答历史: 问题发出即显示, 答案到达前显示思考提示 (计时) — 不冷场 -->
          <div v-if="qaHistory.length" style="margin-bottom: 12px">
            <div v-for="(e, i) in qaHistory" :key="e.t" style="margin-bottom: 10px">
              <div style="font-size: 13px"><strong>问 {{ i + 1 }}:</strong> {{ e.q }}</div>
              <n-alert v-if="e.done" type="info" :bordered="false" style="margin-top: 4px">
                <div style="font-size: 13px; white-space: pre-wrap"><strong>答:</strong> {{ e.a }}</div>
              </n-alert>
              <n-alert v-else type="warning" :bordered="false" style="margin-top: 4px">
                <div style="font-size: 13px">
                  ⏳ {{ qaWaitHint }}
                  <span v-if="sceneLoading" style="margin-left: 8px; color: #888">· 场景动画同步构建中…</span>
                </div>
              </n-alert>
            </div>
          </div>
          <n-input
            v-model:value="raiseHandText"
            type="textarea" :rows="3"
            :placeholder="'输入你的问题，老师会用语音回答…\n可同时附上题目图片（拍照/截图上传）'"
          />
          <n-space style="margin-top: 10px" align="center">
            <n-upload
              :show-file-list="false"
              accept="image/*"
              :default-upload="false"
              @change="onImageChosen"
            >
              <n-button size="small">📷 {{ pendingImageName ? `已选: ${pendingImageName}` : '上传图片提问' }}</n-button>
            </n-upload>
            <n-button
              :type="dh.recording ? 'error' : 'default'"
              :disabled="!dh.session?.asr_available"
              @mousedown="onPressSpeak"
              @mouseup="onReleaseSpeak"
              @mouseleave="onReleaseSpeak"
            >{{ dh.recording ? '🔴 录音中…' : '🎤 按住说话' }}</n-button>
            <n-button type="primary" :loading="dh.busy" @click="submitQa">发送提问</n-button>
          </n-space>
          <n-alert v-if="pendingImageB64" type="success" :bordered="false" style="margin-top: 8px">
            图片已就绪，点击"发送提问"老师就会看图解答
          </n-alert>

          <!-- 场景动画联动: 可动画题 (火车过桥/植树/移多补少等) 编译成功后嵌入展示 —
               动画是异步加载 (LLM 提取分钟级), 加载中不打扰答疑 -->
          <n-card v-if="sceneLoading" size="small" :bordered="true" style="margin-top: 12px">
            <n-spin size="small" /><span style="margin-left: 8px; color: #888; font-size: 13px">正在为这道题生成场景动画…</span>
          </n-card>
          <n-card v-if="sceneData" title="🎬 场景动画演示" size="small" :bordered="true" style="margin-top: 12px">
            <SceneCanvas :scene="sceneData" />
          </n-card>
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

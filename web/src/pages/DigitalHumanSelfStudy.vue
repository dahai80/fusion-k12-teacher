<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NCard, NSpace, NForm, NFormItem, NInput, NSelect, NButton, NTag, NSpin, useMessage } from 'naive-ui'
import { courseApi } from '@/api/endpoints'
import { api } from '@/api/client'

const router = useRouter()
const message = useMessage()
const loading = ref(true)
const subjects = ref<any[]>([])
// 模式1/2 的课程(课堂包)选择数据
const packs = ref<any[]>([])
const packsLoading = ref(false)

// study = 按课程讲 | expand = 举一反三 | qa = 我有问题 (原自由主题表单并入 study 的"直接输入主题")
const mode = ref<'study' | 'expand' | 'qa'>('study')

const form = reactive({
  subject: 'math',
  grade: '3',
  topic: '',
  layer: 'B',
  classId: '',      // 模式1/2: 选中的课堂包
})

const modeCards = [
  { key: 'study', icon: '📖', title: '讲课程', desc: '选择课程，老师按备课教案讲一遍' },
  { key: 'expand', icon: '💡', title: '举一反三', desc: '选课程，老师不照教案，围绕知识点扩展讲' },
  { key: 'qa', icon: '🙋', title: '我有问题', desc: '直接提问：语音 / 文字 / 拍照上传' },
] as const

const layerOptions = [
  { label: '基础 (A)', value: 'A' },
  { label: '进阶 (B)', value: 'B' },
  { label: '拔高 (C)', value: 'C' },
]

onMounted(async () => {
  try {
    const res = await courseApi.subjects() as any
    subjects.value = (res.subjects || []).map((s: any) => ({
      label: s.display_name || s.subject_id,
      value: s.subject_id,
    }))
    if (subjects.value.length === 0) {
      subjects.value = [{ label: '数学', value: 'math' }]
    }
    form.subject = subjects.value[0].value
  } catch {
    subjects.value = [{ label: '数学', value: 'math' }]
  }
  loading.value = false
  loadSuggestions()
  if (mode.value !== 'qa') loadPacks()
})

// 年级/学科切换 → 图谱标签 + 课程双数据源(课堂包/教材单元)都按新年级刷新；
// 已选课程若不属于新年级则清空（级联：年级变 → 课程列表重筛）
function onGradeChange() {
  loadSuggestions()
  loadPacks()
  const gradeN = String(parseInt(form.grade, 10) || '')
  const picked = packs.value.find((p: any) => p.class_id === form.classId)
  if (picked && gradeN && String(picked.grade) !== gradeN) form.classId = ''
  else form.classId = ''  // 教材单元 value 里编码了年级, 年级变了一律重选
}

// 点选知识点标签: 填充主题 + 记住 node_id (随请求传给后端, 讲解/举一反三锚定图谱节点)
const selectedNodeId = ref('')
function pickSuggestion(t: { label: string; value: string }) {
  selectedNodeId.value = t.value
  form.topic = t.label
}

async function loadPacks() {
  packsLoading.value = true
  // 双数据源: ①已备课课堂包(讲稿现成, 秒开) ②北师大版教材单元(按需生成讲稿)。
  // 只有课堂包时 6 年级下拉为空 (包全是低年级备课产物) — 教材目录补全所有年级。
  try {
    const r = await api.get('/api/classroom/packs') as any
    packs.value = (r.packs || []).filter((p: any) => p.page_count > 0)
  } catch { packs.value = [] }
  try {
    const t = await api.get(`/api/textbook/beishi/${form.subject}/${parseInt(form.grade, 10)}/units`) as any
    textbookUnits.value = (t.units || []).map((u: any) => ({
      unit: u.unit, title: u.title, edition: 'beishi',
      subject: form.subject, grade: form.grade,
    }))
  } catch { textbookUnits.value = [] }
  packsLoading.value = false
}

// 北师大版教材单元 (mode=course/expand 未备课时兜底)
const textbookUnits = ref<{ unit: number; title: string; edition: string; subject: string; grade: string }[]>([])

function pickMode(m: 'study' | 'expand' | 'qa') {
  mode.value = m
  if (m !== 'qa' && packs.value.length === 0 && textbookUnits.value.length === 0) loadPacks()
}

function packOptions() {
  // 级联筛选: 先选年级 → 该年级的课堂包 + 教材单元 (分组展示, 包优先·秒开)
  const gradeN = String(parseInt(form.grade, 10) || '')
  const packOpts = packs.value
    .filter((p: any) => !gradeN || String(p.grade) === gradeN)
    .map((p: any) => ({
      label: `${p.topic}（${p.grade}年级·已备课·秒开）`,
      value: p.class_id,
    }))
  const unitOpts = textbookUnits.value
    .filter((u) => String(u.grade) === gradeN)
    .map((u) => ({
      label: `${u.title}（${u.grade}年级·北师大版·现场生成讲稿）`,
      value: `unit:${u.edition}:${u.subject}:${u.grade}:${u.unit}:${u.title}`,
    }))
  if (packOpts.length && unitOpts.length) {
    return [
      { type: 'group', label: '已备课课程（点开即讲）', key: 'g-pack', children: packOpts },
      { type: 'group', label: '北师大版教材单元（现场生成）', key: 'g-unit', children: unitOpts },
    ]
  }
  return packOpts.length ? packOpts : unitOpts
}

function startStudy() {
  if (mode.value === 'qa') {
    // 模式3: 纯问答 — 不选课不生成讲稿, 进对话界面
    router.push({ path: '/digital-human/player', query: { mode: 'qa', subject: form.subject, grade: form.grade } })
    return
  }
  if (mode.value === 'expand') {
    // 模式2: 举一反三 — 选课程单元, 后端走图谱上下文+扩展讲解
    if (!form.classId) { message.error('请选择课程单元'); return }
    if (form.classId.startsWith('unit:')) {
      // 教材单元(未备课): 以单元标题为主题现场生成讲稿
      const [, , , unitGrade, , unitTitle] = form.classId.split(':')
      router.push({
        path: '/digital-human/player',
        query: {
          mode: 'expand', subject: form.subject, grade: unitGrade,
          topic: unitTitle, layer: form.layer,
          nodeId: selectedNodeId.value,
        },
      })
      return
    }
    router.push({
      path: '/digital-human/player',
      query: {
        mode: 'expand', classId: form.classId,
        subject: form.subject, grade: form.grade, layer: form.layer,
      },
    })
    return
  }
  // 模式1: 讲课程 — 优先选课程单元(复用教案零 LLM)；也允许直接输主题(自由讲课)
  if (form.classId) {
    if (form.classId.startsWith('unit:')) {
      // 教材单元(未备课): topic=单元标题, 播放器走 topic 生成链路
      const [, , , unitGrade, , unitTitle] = form.classId.split(':')
      router.push({
        path: '/digital-human/player',
        query: {
          mode: 'topic', subject: form.subject, grade: unitGrade,
          topic: unitTitle, layer: form.layer,
          nodeId: selectedNodeId.value,
        },
      })
      return
    }
    router.push({
      path: '/digital-human/player',
      query: { mode: 'course', classId: form.classId, layer: form.layer },
    })
    return
  }
  if (!form.topic.trim()) { message.error('请选择课程，或输入学习主题'); return }
  router.push({
    path: '/digital-human/player',
    query: {
      mode: 'topic', subject: form.subject, topic: form.topic,
      grade: form.grade, layer: form.layer,
      nodeId: selectedNodeId.value,
    },
  })
}

// 主题建议: 按年级动态查知识图谱节点 (替代原写死 5 个标签) —
// 点选节点同时带 knowledge_node_id, 举一反三/讲解直接锚定图谱知识点
const topicSuggestions = ref<{ label: string; value: string }[]>([])
const suggestionsLoading = ref(false)

async function loadSuggestions() {
  suggestionsLoading.value = true
  try {
    const r = await api.get(`/api/course/${form.subject}/graph/nodes`) as any
    const nodes: any[] = r.nodes || r || []
    const gradeN = String(parseInt(form.grade, 10) || '')
    const inGrade = nodes.filter((n: any) => String(n.grade || '') === gradeN)
    topicSuggestions.value = (inGrade.length ? inGrade : nodes.slice(0, 8)).slice(0, 10)
      .map((n: any) => ({ label: n.title || n.id, value: n.id || '' }))
  } catch {
    topicSuggestions.value = []
  }
  suggestionsLoading.value = false
}
</script>

<template>
  <n-spin v-if="loading" />
  <n-space v-else vertical>
    <n-card title="🤖 AI 数字人老师 — 自主学习 (UC-C7)" size="small">
      <p style="color: #666; margin: 0 0 12px">
        选择学习方式: 按教案讲课 / 围绕知识点举一反三 / 直接提问答疑。语音讲解 + 互动提问 + 举手答疑。
      </p>
      <!-- 三模式卡片 -->
      <n-space style="margin-bottom: 16px">
        <n-card
          v-for="m in modeCards" :key="m.key"
          size="small" hoverable
          :style="{ width: '220px', cursor: 'pointer', border: mode === m.key ? '2px solid #18a058' : '1px solid #eee' }"
          @click="pickMode(m.key)"
        >
          <div style="font-size: 22px">{{ m.icon }}</div>
          <div style="font-weight: 600; margin: 4px 0">{{ m.title }}</div>
          <div style="font-size: 12px; color: #888">{{ m.desc }}</div>
        </n-card>
      </n-space>

      <!-- 模式3: 我有问题 — 无表单, 直接进对话 -->
      <template v-if="mode === 'qa'">
        <n-alert type="info" :bordered="false" style="margin-bottom: 12px">
          进入后直接向老师提问：可打字、按住说话（语音转文字）、拍照上传题目。无需选择课程。
        </n-alert>
        <n-button type="primary" size="large" @click="startStudy">🙋 开始提问</n-button>
      </template>

      <!-- 模式1/2: 课程单元选择 -->
      <template v-else>
        <n-form label-placement="left" :show-feedback="false" size="small">
          <n-form-item label="年级">
            <n-select
              v-model:value="form.grade"
              :options="Array.from({length: 12}, (_, i) => ({label: `${i+1}年级`, value: String(i+1)}))"
              style="width: 120px"
              @update:value="onGradeChange"
            />
          </n-form-item>
          <n-form-item label="分层">
            <n-select v-model:value="form.layer" :options="layerOptions" style="width: 120px" />
          </n-form-item>
          <n-form-item :label="mode === 'expand' ? '选择课程（举一反三）' : '选择课程（按教案讲）'">
            <n-select
              v-model:value="form.classId"
              :options="packOptions()"
              :loading="packsLoading"
              placeholder="按年级筛选后选择课程单元"
              style="width: 320px"
              filterable
            />
          </n-form-item>
          <n-form-item v-if="mode === 'study'" label="或自由主题">
            <n-input v-model:value="form.topic" placeholder="不选课程时可直接输入主题, 如: 分数" style="width: 320px" />
          </n-form-item>
        </n-form>
        <n-space v-if="mode === 'study'" style="margin-top: 8px" size="small" align="center">
          <span style="font-size: 12px; color: #888">{{ form.grade }}年级知识点:</span>
          <n-tag
            v-for="t in topicSuggestions" :key="t.value || t.label"
            size="small" style="cursor: pointer"
            :type="selectedNodeId === t.value ? 'success' : 'default'"
            @click="pickSuggestion(t)"
          >{{ t.label }}</n-tag>
          <n-tag v-if="suggestionsLoading" size="small" type="info">加载中…</n-tag>
          <n-tag v-if="!suggestionsLoading && topicSuggestions.length === 0" size="small">该年级暂无图谱节点，可直接输入主题</n-tag>
        </n-space>
        <n-button type="primary" size="large" style="margin-top: 16px" @click="startStudy">
          {{ mode === 'expand' ? '💡 举一反三开讲' : '🚀 开始讲课' }}
        </n-button>
      </template>
    </n-card>

    <n-card title="功能说明" size="small">
      <n-space vertical size="small">
        <div>• <strong>📖 讲课程</strong>: 复用备课教案逐页精讲（零等待, 讲的就是你备的课），也可自由输主题即兴讲</div>
        <div>• <strong>💡 举一反三</strong>: 结合知识图谱先修点与易错点, 换角度、换例子扩展讲解</div>
        <div>• <strong>🙋 我有问题</strong>: 免课程直接问 — 文字 / 按住说话 (Whisper ASR) / 拍照上传 (VLM 看图解题)</div>
        <div>• <strong>语音讲解</strong>: Kokoro TTS 中文声线逐页朗读 (5E 苏格拉底式)</div>
        <div>• <strong>打断</strong>: 讲课中说话可打断, AI 停下重听 (barge-in 总线)</div>
      </n-space>
    </n-card>
  </n-space>
</template>

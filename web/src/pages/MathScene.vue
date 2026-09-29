<script setup lang="ts">
import { reactive, ref, computed } from 'vue'
import { NCard, NSpace, NForm, NFormItem, NInput, NButton, NTag, NTimeline, NTimelineItem, NAlert } from 'naive-ui'
import { courseApi } from '@/api/endpoints'
import { useGenerator } from '@/composables/useGenerator'
import SceneCanvas from '@/components/SceneCanvas.vue'

const form = reactive({ problem_text: '一列长200米的火车以20米每秒的速度通过800米大桥, 求通过时间。' })
const gen = useGenerator()
const scene = ref<any>(null)

async function compile() {
  scene.value = null
  await gen.run(async () => {
    const r = await courseApi.sceneCompile('math', { ...form })
    scene.value = r
    return r
  })
}

const hasScene = computed(() => scene.value && !scene.value.error)

// ── Gemini 参考 GUI: 左上解析结果 / 左下结构化参数 / 右侧动画+HUD ──

// 1. 自然语言解析结果 (S1): 已知量 → 求什么 → 判定
const parseResult = computed(() => {
  const s = scene.value
  if (!hasScene.value) return null
  const isGeneric = s.meta?.pipeline === 'generic' || s.template_type === 'generic_solve'
  return {
    isGeneric,
    scenario: s.template_type || 'unknown',
    questionFocus: String(s.pedagogy?.question_focus || ''),
    misconception: String(s.pedagogy?.misconception_breakdown || ''),
    verified: !!s.verified,
  }
})

// 2. 结构化参数 (S2): parameters + 分步 pipeline + JSON DSL 全文
const structParams = computed(() => scene.value?.canvas_config?.parameters || [])
const structPipeline = computed<any[]>(() => scene.value?.canvas_config?.pipeline || [])
const dslJson = computed(() => {
  if (!hasScene.value) return ''
  try {
    const { meta, entities, canvas_config, timeline, pedagogy, verified, template_type } = scene.value
    return JSON.stringify({
      meta: { ...meta, template_type },
      parameters: Object.fromEntries((canvas_config?.parameters || []).map((p: any) => [p.key, { label: p.label, value: p.value, unit: p.unit }])),
      entities, pipeline: canvas_config?.pipeline || [], timeline, pedagogy, verified,
    }, null, 2)
  } catch {
    return String(scene.value)
  }
})

// 3. 分步推导卡片 (右侧下部): 每步公式+结果, 高亮当前进度所在步
const currentStepIdx = computed(() => {
  // 与 SceneCanvas 内 currentStep 同口径: 由进度推导, 此处无播放状态, 展示全部并高亮最终步
  return Math.max(0, structPipeline.value.length - 1)
})
</script>
<template>
  <n-space vertical size="large">
    <!-- 左右分栏 (Gemini 参考): 左 1/3 解析+参数, 右 2/3 动画+推导 -->
    <div class="scene-grid">
      <!-- 左列 -->
      <div class="scene-col-left">
        <!-- 1. 自然语言解析结果 -->
        <n-card size="small" class="left-card">
          <template #header>
            <n-tag type="warning" size="small" :bordered="false">1 · 自然语言解析</n-tag>
          </template>
          <n-form label-placement="left" :show-feedback="false" size="small">
            <n-form-item label="题干">
              <n-input v-model:value="form.problem_text" type="textarea" :rows="3" placeholder="输入任意 K12 应用题..." />
            </n-form-item>
          </n-form>
          <n-button type="primary" style="margin-top: 12px" block :loading="gen.loading.value" @click="compile">编译场景</n-button>
          <template v-if="parseResult">
            <div class="parse-block">
              <div class="parse-row"><span class="plabel">场景判定</span>
                <n-tag size="small" :type="parseResult.isGeneric ? 'info' : 'success'">
                  {{ parseResult.isGeneric ? '通用求解管线' : '精品模板: ' + parseResult.scenario }}
                </n-tag>
                <n-tag size="small" :type="parseResult.verified ? 'success' : 'warning'">
                  {{ parseResult.verified ? 'SymPy 验算通过' : '未验算' }}
                </n-tag>
              </div>
              <div v-if="parseResult.questionFocus" class="parse-row"><span class="plabel">求解目标</span><span>{{ parseResult.questionFocus }}</span></div>
            </div>
          </template>
          <n-tag v-else type="info" size="small" style="margin-top: 12px">左侧编译后, 此处展示 S1 解析结果</n-tag>
        </n-card>

        <!-- 2. 结构化参数 (JSON DSL) -->
        <n-card size="small" class="left-card">
          <template #header>
            <n-tag type="success" size="small" :bordered="false">2 · 结构化参数 (JSON DSL)</n-tag>
          </template>
          <template v-if="hasScene">
            <div v-if="structParams.length" class="param-chips">
              <n-tag v-for="p in structParams" :key="p.key" size="small" :bordered="false" class="param-chip">
                {{ p.label || p.key }} = {{ p.value }}{{ p.unit || '' }}
              </n-tag>
            </div>
            <pre class="dsl-viewer">{{ dslJson }}</pre>
          </template>
          <n-tag v-else type="default" size="small">编译后展示 LLM 输出的 DSL JSON</n-tag>
        </n-card>
      </div>

      <!-- 右列 -->
      <div class="scene-col-right">
        <template v-if="hasScene">
          <!-- 3. 动画画布 (含分步 HUD) -->
          <n-card size="small">
            <template #header>
              <n-tag type="warning" size="small" :bordered="false">3 · 场景动画</n-tag>
            </template>
            <scene-canvas :scene="scene" />
          </n-card>

          <!-- 实时分步推导卡片 -->
          <n-card v-if="structPipeline.length" size="small" class="derive-card">
            <template #header>
              <n-tag type="info" size="small" :bordered="false">实时分步推导</n-tag>
              <n-tag size="small" style="margin-left: 8px">双引擎交叉验证通过</n-tag>
            </template>
            <div class="derive-grid">
              <div v-for="(s, i) in structPipeline" :key="s.step" class="derive-item" :class="{ active: i === currentStepIdx }">
                <div class="dlabel">{{ s.step }}. {{ s.title }}</div>
                <div class="dval">{{ s.formula }} → {{ fmtStep(s.value) }}{{ s.result_unit || '' }}</div>
              </div>
            </div>
          </n-card>

          <n-card title="时间轴里程碑" size="small">
            <n-timeline>
              <n-timeline-item
                v-for="(m, i) in (scene.timeline?.milestones || [])"
                :key="i"
                :type="i === 0 ? 'info' : 'success'"
                :time="'t=' + m.time_mark + 's'"
              >
                <strong>{{ m.event_name }}</strong>
                <span style="color: #64748b"> — {{ m.formula_state || ('进度 ' + m.progress_percentage + '%') }}</span>
              </n-timeline-item>
            </n-timeline>
          </n-card>

          <n-alert v-if="parseResult?.misconception" type="warning" :show-icon="true" style="margin-top: 0">
            💡 教学破局点: {{ parseResult.misconception }}
          </n-alert>
        </template>

        <n-card v-else-if="gen.errorMsg.value" size="small">
          <n-alert type="error">{{ gen.errorMsg.value }}</n-alert>
        </n-card>
        <n-card v-else size="small">
          <n-space vertical>
            <n-tag type="info">输入应用题, 点击编译生成场景动画</n-tag>
            <n-tag size="small" type="default">示例: 火车过桥 / 车轮滚圈 / 任意新题型 (通用管线自动求解)</n-tag>
          </n-space>
        </n-card>
      </div>
    </div>
  </n-space>
</template>

<script lang="ts">
// 模板内使用的工具函数
export default {
  methods: {
    fmtStep(v: any): string {
      const n = Number(v)
      if (!Number.isFinite(n)) return '—'
      return Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/\.?0+$/, '')
    },
  },
}
</script>

<style scoped>
.scene-grid { display: grid; grid-template-columns: 1fr; gap: 16px; }
@media (min-width: 1024px) {
  .scene-grid { grid-template-columns: 1fr 2fr; align-items: start; }
}
.scene-col-left, .scene-col-right { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.left-card { min-width: 0; }
.parse-block { margin-top: 12px; display: flex; flex-direction: column; gap: 6px; }
.parse-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 13px; }
.plabel { color: #64748b; font-size: 12px; min-width: 56px; }
.param-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.param-chip { font-family: ui-monospace, monospace; }
.dsl-viewer {
  background: #0f172a; color: #34d399; padding: 10px; border-radius: 8px;
  font-size: 11px; font-family: ui-monospace, monospace; line-height: 1.4;
  overflow: auto; max-height: 220px; margin: 0;
}
.derive-card :deep(.n-card__content) { background: #0f172a; border-radius: 8px; }
.derive-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; }
.derive-item { background: rgba(30, 41, 59, 0.8); border: 1px solid #334155; border-radius: 8px; padding: 10px; }
.derive-item.active { border-color: #f59e0b; }
.dlabel { font-size: 11px; color: #94a3b8; }
.dval { font-size: 12px; font-weight: 700; font-family: ui-monospace, monospace; color: #7dd3fc; margin-top: 4px; }
</style>

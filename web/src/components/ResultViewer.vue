<script setup lang="ts">
import { computed } from 'vue'
import {
  NCard, NSpace, NTag, NCollapse, NCollapseItem, NEmpty, NCode, NButton,
  NDescriptions, NDescriptionsItem, NTimeline, NTimelineItem, NList, NListItem, NThing,
  NProgress, NStatistic,
} from 'naive-ui'

const props = defineProps<{
  loading: boolean
  result: any | null
  error: string
  title?: string
}>()

const emit = defineEmits<{ (e: 'retry'): void }>()

const hasError = computed(() => Boolean(props.error))
const isErrorResult = computed(() => props.result && props.result.error)

type Kind = 'lesson' | 'diff' | 'quiz' | 'exercise' | 'unit' | 'grading' | 'worksheet'
  | 'flashcards' | 'slides' | 'game' | 'parent_comm' | 'report' | 'class_profile'
  | 'student_profile' | 'error_analysis' | 'remedial' | 'class_report' | 'diagnose'
  | 'path' | 'recommend' | 'explain' | 'stem' | 'lang_activity' | 'align' | 'coverage'
  | 'safety' | 'desensitize' | 'rubric' | 'generic'

const kind = computed<Kind>(() => {
  const r = props.result
  if (!r) return 'generic'
  if (r.is_safe !== undefined || r.decision) return 'safety'
  if (r.desensitized_records !== undefined) return 'desensitize'
  if (r.type === 'worksheet') return 'worksheet'
  if (r.type === 'flashcards') return 'flashcards'
  if (r.type === 'slides') return 'slides'
  if (r.type === 'game') return 'game'
  if (r.content && typeof r.content === 'string' && Object.keys(r).length <= 2) return 'parent_comm'
  if (r.report && typeof r.report === 'string' && r.class_id !== undefined) return 'class_report'
  if (r.score !== undefined && r.total !== undefined && r.percentage !== undefined) return 'grading'
  if (r.student_name !== undefined && r.overall_score !== undefined) return 'report'
  if (r.total_students !== undefined && r.avg_score !== undefined) return 'class_profile'
  if (r.overall_level !== undefined && r.knowledge_mastery !== undefined) return 'student_profile'
  if (Array.isArray(r.errors) && r.total !== undefined) return 'error_analysis'
  if (Array.isArray(r.weak_points) && Array.isArray(r.strategies)) return 'remedial'
  if (r.mastered_skills !== undefined) return 'diagnose'
  if (Array.isArray(r.goals) && Array.isArray(r.units)) return 'path'
  if (Array.isArray(r.resources)) return 'recommend'
  if (r.simple_explanation !== undefined) return 'explain'
  if (r.driving_question !== undefined) return 'stem'
  if (r.objective !== undefined && Array.isArray(r.procedure) && r.differentiation) return 'lang_activity'
  if (Array.isArray(r.knowledge_points) && r.must_cover !== undefined) return 'align'
  if (r.coverage_ratio !== undefined) return 'coverage'
  if (Array.isArray(r.dimensions) || (Object.keys(r).length > 0 && Array.isArray((r as any)[Object.keys(r)[0]]) && typeof (r as any)[Object.keys(r)[0]]?.[0] === 'object')) return 'rubric'
  const plan = r.unit_plan && typeof r.unit_plan === 'object' ? r.unit_plan : null
  if (plan && (Array.isArray(plan.weekly_schedule) || plan.duration_weeks !== undefined)) return 'unit'
  if (Array.isArray(r.procedures) || Array.isArray(r.objectives) || r.duration_minutes !== undefined) return 'lesson'
  if (r.layers && typeof r.layers === 'object') return 'diff'
  if (Array.isArray(r.questions)) return 'quiz'
  if (r.question && (r.answer || r.explanation)) return 'exercise'
  return 'generic'
})

const LABELS: Record<string, string> = {
  id: '编号', title: '标题', subject: '学科', grade: '年级', topic: '主题',
  duration_minutes: '时长(分钟)', difficulty: '难度', created_at: '生成时间',
  total_points: '总分', time_limit_minutes: '限时(分钟)', answer_key: '答案要点',
  assessment: '课堂评价', homework: '课后作业', explanation: '解析', answer: '答案',
  standards_aligned: '课标对齐', unit_title: '单元主题', unit_theme: '单元主题',
  grade_level: '年级', duration_weeks: '周数', weekly_schedule: '周计划',
  materials_needed: '所需材料', differentiation_strategies: '分层策略',
  learning_objectives: '学习目标', main_activities: '主要活动',
  assessment_methods: '评估方式', theme: '主题', week: '周次',
  score: '得分', total: '满分', percentage: '百分比', feedback: '反馈',
  improvements: '改进建议', strengths: '优点', rubric_scores: '评分维度',
  partial: '部分正确', student_name: '学生', period: '周期',
  overall_score: '总体得分', skills: '技能掌握', areas_to_improve: '待提升',
  teacher_notes: '教师评语', class_id: '班级', total_students: '学生人数',
  avg_score: '平均分', score_distribution: '分数分布',
  weak_knowledge_points: '薄弱知识点', strong_knowledge_points: '优势知识点',
  student_risk_levels: '风险等级', generated_at: '生成时间',
  name: '姓名', overall_level: '总体水平', knowledge_mastery: '知识掌握',
  learning_trend: '学习趋势', risk_indicators: '风险指标',
  recommended_actions: '建议措施', student_id: '学生编号',
  errors: '错误列表', weak_points: '薄弱点',
  strategies: '策略', timeline: '时间线',
  estimated_duration: '预计时长', mastered_skills: '已掌握',
  developing_skills: '发展中', needs_support: '需支持',
  recommendations: '建议', goals: '目标', units: '单元',
  prerequisites: '前置知识', resources: '推荐资源',
  practice_plan: '练习计划', parent_tips: '家长建议',
  simple_explanation: '通俗解释', example: '示例',
  visualization: '可视化', common_misconceptions: '常见误区',
  extension: '拓展', driving_question: '驱动问题',
  objectives: '目标', materials: '材料', procedure: '步骤',
  expected_outcomes: '预期成果', rubric: '评价标准',
  objective: '目标', differentiation: '分层',
  knowledge_points: '知识点', must_cover: '必覆盖',
  optional_advanced: '进阶可选', curriculum_codes: '课标编码',
  suggested_objectives: '建议目标', prerequisite_count: '前置数量',
  covered_points: '已覆盖', coverage_ratio: '覆盖率',
  missing_points: '缺失知识点',
  is_safe: '是否安全', decision: '决定', risk_level: '风险等级',
  flagged_words: '标记词', age_issues: '年龄适宜性问题',
  filtered_text: '过滤后文本', forced_filtered_text: '强制过滤文本',
  summary: '摘要', original_count: '原始数量',
  anonymized_count: '脱敏数量', masked_fields: '掩码字段',
  desensitized_records: '脱敏记录',
  game_type: '游戏类型', rules: '规则', duration: '时长',
  setup: '准备', variations: '变体', debrief: '总结',
  front: '正面', back: '背面', hint: '提示',
  slide_number: '页码', content: '内容',
  visual_suggestion: '视觉建议',
  question: '题目', options: '选项', points: '分值',
  sections: '章节', instructions: '说明',
  error_type: '错误类型', frequency: '频次',
  root_cause: '根因', remediation: '补救',
  sample_responses: '示例回答', group_name: '组名',
  task_description: '任务描述', expected_output: '预期产出',
  time_allocation: '时间分配', error: '错误', type: '类型',
}
function label(k: string): string { return LABELS[k] || k }

function asArray(v: any): any[] { return Array.isArray(v) ? v : [] }

const LAYER_NAMES: Record<string, string> = {
  struggling: '基础层 (A)', standard: '标准层 (B)', advanced: '进阶层 (C)', ell: '语言辅助',
}
function layerName(k: string): string { return LAYER_NAMES[k] || k }

const DIFFICULTY_TYPE: Record<string, string> = {
  easy: 'success', medium: 'warning', hard: 'error',
}

function riskType(level: string): 'success' | 'warning' | 'error' | 'info' {
  const l = (level || '').toLowerCase()
  if (l.includes('high') || l.includes('高')) return 'error'
  if (l.includes('mid') || l.includes('中')) return 'warning'
  if (l.includes('low') || l.includes('低')) return 'success'
  return 'info'
}

const simpleFields = computed(() => {
  if (!props.result) return []
  return Object.entries(props.result)
    .filter(([k, v]) => !['error', 'questions', 'procedures', 'objectives', 'materials',
      'differentiation', 'layers', 'group_tasks', 'hints', 'skills', 'examples',
      'exercises', 'layer_errors', 'standards_aligned', 'unit_plan', 'sections', 'items',
      'rules', 'variations', 'content', 'report', 'improvements', 'strengths', 'rubric_scores',
      'weak_knowledge_points', 'strong_knowledge_points', 'student_risk_levels',
      'score_distribution', 'knowledge_mastery', 'risk_indicators', 'recommended_actions',
      'errors', 'weak_points', 'strategies', 'exercises', 'goals', 'units', 'prerequisites',
      'resources', 'practice_plan', 'parent_tips', 'common_misconceptions', 'procedure',
      'expected_outcomes', 'rubric', 'knowledge_points', 'must_cover', 'optional_advanced',
      'curriculum_codes', 'suggested_objectives', 'missing_points', 'details',
      'flagged_words', 'age_issues', 'filtered_text', 'forced_filtered_text',
      'desensitized_records', 'result', 'mastered_skills', 'developing_skills',
      'needs_support', 'recommendations', 'sample_responses'].includes(k)
      && !(Array.isArray(v) || (typeof v === 'object' && v !== null)))
    .map(([k, v]) => ({ label: label(k), value: String(v) }))
})

function pretty(v: any): string {
  try { return JSON.stringify(v, null, 2) } catch { return String(v) }
}

const unitPlan = computed(() => {
  const r = props.result
  if (!r) return null
  return r.unit_plan && typeof r.unit_plan === 'object' ? r.unit_plan : null
})

const scoreColor = (pct: number) => pct >= 80 ? '#18a058' : pct >= 60 ? '#f0a020' : '#d03050'
</script>

<template>
  <n-card :title="title || '生成结果'" size="small" style="margin-top: 16px">
    <template v-if="loading">
      <n-space vertical>
        <div v-for="i in 4" :key="i" style="height: 20px; background: var(--n-color-target); border-radius: 4px; animation: pulse 1.2s infinite" />
      </n-space>
    </template>
    <template v-else-if="hasError">
      <n-space vertical align="center">
        <n-tag type="error">生成失败</n-tag>
        <n-code :code="error" language="text" />
        <n-button type="primary" @click="emit('retry')">重试</n-button>
      </n-space>
    </template>
    <template v-else-if="isErrorResult">
      <n-space vertical align="center">
        <n-tag type="warning">引擎降级</n-tag>
        <span>{{ result.error }}</span>
        <n-button @click="emit('retry')">重试</n-button>
      </n-space>
    </template>

    <!-- ── 教案 lesson ── -->
    <template v-else-if="result && kind === 'lesson'">
      <n-descriptions v-if="simpleFields.length" label-placement="left" bordered :column="2" size="small">
        <n-descriptions-item v-for="f in simpleFields" :key="f.label" :label="f.label">{{ f.value }}</n-descriptions-item>
      </n-descriptions>
      <n-card v-if="asArray(result.objectives).length" title="教学目标" size="small" :bordered="false" style="margin-top: 12px">
        <n-list><n-list-item v-for="(o, i) in asArray(result.objectives)" :key="i"><n-thing :description="`${i + 1}. ${o}`" /></n-list-item></n-list>
      </n-card>
      <n-card v-if="asArray(result.materials).length" title="教学准备" size="small" :bordered="false" style="margin-top: 12px">
        <n-space><n-tag v-for="(m, i) in asArray(result.materials)" :key="i" type="info">{{ m }}</n-tag></n-space>
      </n-card>
      <n-card v-if="asArray(result.procedures).length" title="教学过程" size="small" :bordered="false" style="margin-top: 12px">
        <n-timeline>
          <n-timeline-item v-for="(p, i) in asArray(result.procedures)" :key="i" :type="i === 0 ? 'success' : 'default'"
            :time="p.duration || ''" :title="`步骤 ${p.step || i + 1}`">
            <div v-if="p.activity" style="font-weight: 600; margin-bottom: 4px">{{ p.activity }}</div>
            <div v-if="p.teacher_does" style="font-size: 13px; color: #2080f0"><strong>教师：</strong>{{ p.teacher_does }}</div>
            <div v-if="p.student_does" style="font-size: 13px; color: #18a058"><strong>学生：</strong>{{ p.student_does }}</div>
          </n-timeline-item>
        </n-timeline>
      </n-card>
      <n-card v-if="result.assessment" title="课堂评价" size="small" :bordered="false" style="margin-top: 12px"><div style="line-height: 1.8">{{ result.assessment }}</div></n-card>
      <n-card v-if="result.homework" title="课后作业" size="small" :bordered="false" style="margin-top: 12px"><div style="line-height: 1.8">{{ result.homework }}</div></n-card>
      <n-card v-if="result.differentiation && typeof result.differentiation === 'object'" title="分层教学" size="small" :bordered="false" style="margin-top: 12px">
        <n-space vertical>
          <div v-for="(v, k) in result.differentiation" :key="k">
            <n-tag :type="k === 'struggling' ? 'warning' : k === 'advanced' ? 'success' : 'info'" size="small">{{ layerName(k) }}</n-tag>
            <span style="margin-left: 8px; font-size: 13px">{{ v }}</span>
          </div>
        </n-space>
      </n-card>
    </template>

    <!-- ── 分层 diff ── -->
    <template v-else-if="result && kind === 'diff'">
      <n-descriptions v-if="simpleFields.length" label-placement="left" bordered :column="2" size="small">
        <n-descriptions-item v-for="f in simpleFields" :key="f.label" :label="f.label">{{ f.value }}</n-descriptions-item>
      </n-descriptions>
      <n-card v-for="(layer, lk) in result.layers || {}" :key="lk" :title="layerName(lk)" size="small" style="margin-top: 12px">
        <div v-if="layer.explanation" style="line-height: 1.8; margin-bottom: 8px">{{ layer.explanation }}</div>
        <n-space v-if="asArray(layer.examples).length" style="margin-bottom: 8px"><n-tag v-for="(ex, i) in asArray(layer.examples)" :key="i" type="info">{{ ex }}</n-tag></n-space>
        <n-card v-if="asArray(layer.exercises).length" title="练习题" size="small" :bordered="false" style="margin-bottom: 8px">
          <n-list>
            <n-list-item v-for="(ex, i) in asArray(layer.exercises)" :key="i">
              <n-thing>
                <template #header>{{ `${i + 1}. ${ex.question}` }}</template>
                <template #description>
                  <span v-if="ex.answer" style="color: #18a058">答案：{{ ex.answer }}</span>
                  <span v-if="ex.hint" style="color: #888; margin-left: 12px">提示：{{ ex.hint }}</span>
                </template>
              </n-thing>
            </n-list-item>
          </n-list>
        </n-card>
        <n-space v-if="asArray(layer.hints).length" vertical><n-tag v-for="(h, i) in asArray(layer.hints)" :key="i" size="small" type="warning">{{ h }}</n-tag></n-space>
        <div v-if="layer.extension" style="margin-top: 8px; font-size: 13px; color: #888"><strong>拓展：</strong>{{ layer.extension }}</div>
      </n-card>
      <n-card v-if="asArray(result.group_tasks).length" title="小组任务" size="small" style="margin-top: 12px">
        <n-list>
          <n-list-item v-for="(t, i) in asArray(result.group_tasks)" :key="i">
            <n-thing>
              <template #header>{{ t.group_name }}</template>
              <template #description>
                <div>{{ t.task_description }}</div>
                <div v-if="t.expected_output" style="color: #18a058">预期产出：{{ t.expected_output }}</div>
                <div v-if="t.time_allocation" style="color: #2080f0">时间分配：{{ t.time_allocation }}</div>
              </template>
            </n-thing>
          </n-list-item>
        </n-list>
      </n-card>
    </template>

    <!-- ── 测验 quiz ── -->
    <template v-else-if="result && kind === 'quiz'">
      <n-descriptions v-if="simpleFields.length" label-placement="left" bordered :column="2" size="small">
        <n-descriptions-item v-for="f in simpleFields" :key="f.label" :label="f.label">{{ f.value }}</n-descriptions-item>
      </n-descriptions>
      <n-card title="题目" size="small" :bordered="false" style="margin-top: 12px">
        <n-list>
          <n-list-item v-for="(q, i) in asArray(result.questions)" :key="i">
            <n-thing>
              <template #header>{{ `${i + 1}. ${q.question}` }}</template>
              <template #header-extra>
                <n-space>
                  <n-tag v-if="q.difficulty" size="small" :type="DIFFICULTY_TYPE[q.difficulty] || 'info'">{{ q.difficulty }}</n-tag>
                  <n-tag v-if="q.points" size="small">{{ q.points }} 分</n-tag>
                </n-space>
              </template>
              <template #description>
                <div v-if="Array.isArray(q.options)">
                  <div v-for="(opt, j) in q.options" :key="j" :style="{ color: opt === q.answer ? '#18a058' : '', fontWeight: opt === q.answer ? 600 : 400 }">
                    {{ String.fromCharCode(65 + j) }}. {{ opt }}<span v-if="opt === q.answer"> ✓</span>
                  </div>
                </div>
                <div v-else-if="q.answer" style="color: #18a058"><strong>答案：</strong>{{ q.answer }}</div>
              </template>
            </n-thing>
          </n-list-item>
        </n-list>
      </n-card>
      <n-card v-if="result.answer_key" title="答案要点" size="small" :bordered="false" style="margin-top: 12px"><div style="line-height: 1.8; white-space: pre-wrap">{{ result.answer_key }}</div></n-card>
    </template>

    <!-- ── 单题 exercise ── -->
    <template v-else-if="result && kind === 'exercise'">
      <n-descriptions v-if="simpleFields.length" label-placement="left" bordered :column="2" size="small">
        <n-descriptions-item v-for="f in simpleFields" :key="f.label" :label="f.label">{{ f.value }}</n-descriptions-item>
      </n-descriptions>
      <n-card title="题目" size="small" :bordered="false" style="margin-top: 12px"><div style="font-size: 16px; line-height: 1.8">{{ result.question }}</div></n-card>
      <n-card v-if="asArray(result.hints).length" title="提示" size="small" :bordered="false" style="margin-top: 12px">
        <n-list><n-list-item v-for="(h, i) in asArray(result.hints)" :key="i"><n-thing :description="`${i + 1}. ${h}`" /></n-list-item></n-list>
      </n-card>
      <n-card v-if="result.answer" title="答案" size="small" :bordered="false" style="margin-top: 12px"><div style="color: #18a058; line-height: 1.8">{{ result.answer }}</div></n-card>
      <n-card v-if="result.explanation" title="解析" size="small" :bordered="false" style="margin-top: 12px"><div style="line-height: 1.8">{{ result.explanation }}</div></n-card>
      <n-card v-if="asArray(result.skills).length" title="考查技能" size="small" :bordered="false" style="margin-top: 12px"><n-space><n-tag v-for="(s, i) in asArray(result.skills)" :key="i" type="info">{{ s }}</n-tag></n-space></n-card>
    </template>

    <!-- ── 单元计划 unit ── -->
    <template v-else-if="result && kind === 'unit' && unitPlan">
      <n-descriptions v-if="unitPlan.unit_theme || unitPlan.grade_level || unitPlan.subject || unitPlan.duration_weeks"
        label-placement="left" bordered :column="2" size="small">
        <n-descriptions-item v-if="unitPlan.unit_theme" :label="label('unit_theme')">{{ unitPlan.unit_theme }}</n-descriptions-item>
        <n-descriptions-item v-if="unitPlan.subject" :label="label('subject')">{{ unitPlan.subject }}</n-descriptions-item>
        <n-descriptions-item v-if="unitPlan.grade_level" :label="label('grade_level')">{{ unitPlan.grade_level }}</n-descriptions-item>
        <n-descriptions-item v-if="unitPlan.duration_weeks !== undefined" :label="label('duration_weeks')">{{ unitPlan.duration_weeks }} 周</n-descriptions-item>
      </n-descriptions>
      <n-card v-for="(w, i) in asArray(unitPlan.weekly_schedule)" :key="i" :title="`第 ${w.week || i + 1} 周：${w.theme || ''}`" size="small" :bordered="false" style="margin-top: 12px">
        <n-card v-if="asArray(w.learning_objectives).length" title="学习目标" size="small" :bordered="false" style="margin-bottom: 8px"><n-list><n-list-item v-for="(o, j) in asArray(w.learning_objectives)" :key="j"><n-thing :description="`${j + 1}. ${o}`" /></n-list-item></n-list></n-card>
        <n-card v-if="asArray(w.main_activities).length" title="主要活动" size="small" :bordered="false" style="margin-bottom: 8px"><n-list><n-list-item v-for="(a, j) in asArray(w.main_activities)" :key="j"><n-thing :description="`${j + 1}. ${a}`" /></n-list-item></n-list></n-card>
        <n-card v-if="asArray(w.assessment_methods).length" title="评估方式" size="small" :bordered="false"><n-list><n-list-item v-for="(a, j) in asArray(w.assessment_methods)" :key="j"><n-thing :description="`${j + 1}. ${a}`" /></n-list-item></n-list></n-card>
      </n-card>
      <n-card v-if="asArray(unitPlan.materials_needed).length" title="所需材料" size="small" :bordered="false" style="margin-top: 12px"><n-space><n-tag v-for="(m, i) in asArray(unitPlan.materials_needed)" :key="i" type="info">{{ m }}</n-tag></n-space></n-card>
      <n-card v-if="asArray(unitPlan.differentiation_strategies).length" title="分层策略" size="small" :bordered="false" style="margin-top: 12px"><n-list><n-list-item v-for="(d, i) in asArray(unitPlan.differentiation_strategies)" :key="i"><n-thing :description="`${i + 1}. ${d}`" /></n-list-item></n-list></n-card>
    </template>

    <!-- ── 评分 grading ── -->
    <template v-else-if="result && kind === 'grading'">
      <n-space align="center" style="margin-bottom: 12px">
        <n-statistic label="得分" :value="`${result.score} / ${result.total}`" />
        <n-progress type="circle" :percentage="result.percentage" :color="scoreColor(result.percentage)" :stroke-width="8" />
      </n-space>
      <n-card v-if="result.feedback" title="反馈" size="small" :bordered="false"><div style="line-height: 1.8">{{ result.feedback }}</div></n-card>
      <n-card v-if="asArray(result.strengths).length" title="优点" size="small" :bordered="false" style="margin-top: 12px"><n-list><n-list-item v-for="(s, i) in asArray(result.strengths)" :key="i"><n-thing :description="`${i + 1}. ${s}`" /></n-list-item></n-list></n-card>
      <n-card v-if="asArray(result.improvements).length" title="改进建议" size="small" :bordered="false" style="margin-top: 12px"><n-list><n-list-item v-for="(s, i) in asArray(result.improvements)" :key="i"><n-thing :description="`${i + 1}. ${s}`" /></n-list-item></n-list></n-card>
      <n-card v-if="result.rubric_scores && typeof result.rubric_scores === 'object'" title="评分维度" size="small" :bordered="false" style="margin-top: 12px">
        <n-space vertical>
          <div v-for="(v, k) in result.rubric_scores" :key="k"><n-tag size="small">{{ label(String(k)) }}</n-tag><span style="margin-left: 8px">{{ v }} 分</span></div>
        </n-space>
      </n-card>
    </template>

    <!-- ── 工作纸 worksheet ── -->
    <template v-else-if="result && kind === 'worksheet'">
      <n-descriptions v-if="result.title || result.instructions" label-placement="left" bordered :column="1" size="small">
        <n-descriptions-item v-if="result.title" :label="label('title')">{{ result.title }}</n-descriptions-item>
        <n-descriptions-item v-if="result.instructions" :label="label('instructions')">{{ result.instructions }}</n-descriptions-item>
      </n-descriptions>
      <n-card v-for="(s, i) in asArray(result.sections)" :key="i" :title="s.title || `章节 ${i + 1}`" size="small" :bordered="false" style="margin-top: 12px">
        <n-list>
          <n-list-item v-for="(q, j) in asArray(s.questions)" :key="j">
            <n-thing>
              <template #header>{{ `${i + 1}.${j + 1} ${q.question}` }}</template>
              <template #header-extra><n-tag v-if="q.points" size="small">{{ q.points }} 分</n-tag></template>
              <template #description><span v-if="q.type" style="color: #888">{{ q.type }}</span></template>
            </n-thing>
          </n-list-item>
        </n-list>
      </n-card>
      <n-card v-if="result.answer_key" title="答案要点" size="small" :bordered="false" style="margin-top: 12px"><div style="line-height: 1.8; white-space: pre-wrap">{{ result.answer_key }}</div></n-card>
    </template>

    <!-- ── 闪卡 flashcards ── -->
    <template v-else-if="result && kind === 'flashcards'">
      <n-list>
        <n-list-item v-for="(c, i) in asArray(result.items)" :key="i">
          <n-thing>
            <template #header>{{ `${i + 1}. ${c.front}` }}</template>
            <template #description>
              <div style="color: #18a058; font-weight: 600">背面：{{ c.back }}</div>
              <div v-if="c.hint" style="color: #888">提示：{{ c.hint }}</div>
            </template>
          </n-thing>
        </n-list-item>
      </n-list>
    </template>

    <!-- ── 幻灯片 slides ── -->
    <template v-else-if="result && kind === 'slides'">
      <n-timeline>
        <n-timeline-item v-for="(s, i) in asArray(result.items)" :key="i" type="success" :time="`第 ${s.slide_number || i + 1} 页`" :title="s.title || ''">
          <div v-if="s.content" style="line-height: 1.8">{{ s.content }}</div>
          <div v-if="s.teacher_notes" style="font-size: 13px; color: #2080f0; margin-top: 4px"><strong>讲稿：</strong>{{ s.teacher_notes }}</div>
          <div v-if="s.visual_suggestion" style="font-size: 13px; color: #888; margin-top: 4px"><strong>视觉：</strong>{{ s.visual_suggestion }}</div>
        </n-timeline-item>
      </n-timeline>
    </template>

    <!-- ── 教育游戏 game ── -->
    <template v-else-if="result && kind === 'game'">
      <n-descriptions label-placement="left" bordered :column="2" size="small">
        <n-descriptions-item v-if="result.game_type" :label="label('game_type')">{{ result.game_type }}</n-descriptions-item>
        <n-descriptions-item v-if="result.title" :label="label('title')">{{ result.title }}</n-descriptions-item>
        <n-descriptions-item v-if="result.objective" :label="label('objective')" :span="2">{{ result.objective }}</n-descriptions-item>
        <n-descriptions-item v-if="result.duration" :label="label('duration')">{{ result.duration }}</n-descriptions-item>
      </n-descriptions>
      <n-card v-if="asArray(result.materials).length" title="所需材料" size="small" :bordered="false" style="margin-top: 12px"><n-space><n-tag v-for="(m, i) in asArray(result.materials)" :key="i" type="info">{{ m }}</n-tag></n-space></n-card>
      <n-card v-if="result.setup" title="准备" size="small" :bordered="false" style="margin-top: 12px"><div style="line-height: 1.8">{{ result.setup }}</div></n-card>
      <n-card v-if="asArray(result.rules).length" title="规则" size="small" :bordered="false" style="margin-top: 12px"><n-list><n-list-item v-for="(r, i) in asArray(result.rules)" :key="i"><n-thing :description="`${i + 1}. ${r}`" /></n-list-item></n-list></n-card>
      <n-card v-if="asArray(result.variations).length" title="变体" size="small" :bordered="false" style="margin-top: 12px"><n-list><n-list-item v-for="(v, i) in asArray(result.variations)" :key="i"><n-thing :description="`${i + 1}. ${v}`" /></n-list-item></n-list></n-card>
      <n-card v-if="result.debrief" title="总结" size="small" :bordered="false" style="margin-top: 12px"><div style="line-height: 1.8">{{ result.debrief }}</div></n-card>
    </template>

    <!-- ── 家校通信 parent_comm ── -->
    <template v-else-if="result && kind === 'parent_comm'">
      <div style="line-height: 1.9; white-space: pre-wrap; padding: 8px">{{ result.content }}</div>
    </template>

    <!-- ── 班级报告 class_report ── -->
    <template v-else-if="result && kind === 'class_report'">
      <n-tag v-if="result.class_id" type="info" style="margin-bottom: 12px">班级：{{ result.class_id }}</n-tag>
      <div style="line-height: 1.9; white-space: pre-wrap; padding: 8px">{{ result.report }}</div>
    </template>

    <!-- ── 学生报告 report ── -->
    <template v-else-if="result && kind === 'report'">
      <n-descriptions label-placement="left" bordered :column="2" size="small">
        <n-descriptions-item v-if="result.student_name" :label="label('student_name')">{{ result.student_name }}</n-descriptions-item>
        <n-descriptions-item v-if="result.subject" :label="label('subject')">{{ result.subject }}</n-descriptions-item>
        <n-descriptions-item v-if="result.grade" :label="label('grade')">{{ result.grade }}</n-descriptions-item>
        <n-descriptions-item v-if="result.period" :label="label('period')">{{ result.period }}</n-descriptions-item>
        <n-descriptions-item v-if="result.overall_score !== undefined" :label="label('overall_score')">{{ result.overall_score }}</n-descriptions-item>
      </n-descriptions>
      <n-card v-if="result.skills && typeof result.skills === 'object'" title="技能掌握" size="small" :bordered="false" style="margin-top: 12px">
        <n-space vertical>
          <div v-for="(v, k) in result.skills" :key="k">
            <n-tag size="small">{{ label(String(k)) }}</n-tag>
            <n-progress style="display: inline-block; width: 200px; margin-left: 8px" :percentage="Number(v)" :color="scoreColor(Number(v))" />
          </div>
        </n-space>
      </n-card>
      <n-card v-if="asArray(result.strengths).length" title="优点" size="small" :bordered="false" style="margin-top: 12px"><n-list><n-list-item v-for="(s, i) in asArray(result.strengths)" :key="i"><n-thing :description="`${i + 1}. ${s}`" /></n-list-item></n-list></n-card>
      <n-card v-if="asArray(result.areas_to_improve).length" title="待提升" size="small" :bordered="false" style="margin-top: 12px"><n-list><n-list-item v-for="(s, i) in asArray(result.areas_to_improve)" :key="i"><n-thing :description="`${i + 1}. ${s}`" /></n-list-item></n-list></n-card>
      <n-card v-if="result.teacher_notes" title="教师评语" size="small" :bordered="false" style="margin-top: 12px"><div style="line-height: 1.8">{{ result.teacher_notes }}</div></n-card>
    </template>

    <!-- ── 班级画像 class_profile ── -->
    <template v-else-if="result && kind === 'class_profile'">
      <n-space align="center" style="margin-bottom: 12px">
        <n-statistic label="学生人数" :value="result.total_students || 0" />
        <n-statistic label="平均分" :value="result.avg_score || 0" />
      </n-space>
      <n-card v-if="result.score_distribution && typeof result.score_distribution === 'object'" title="分数分布" size="small" :bordered="false" style="margin-bottom: 12px">
        <n-space vertical>
          <div v-for="(cnt, range) in result.score_distribution" :key="range">
            <n-tag size="small">{{ range }}</n-tag>
            <n-progress style="display: inline-block; width: 200px; margin-left: 8px" :percentage="result.total_students ? Math.round(Number(cnt) / result.total_students * 100) : 0" />
            <span style="margin-left: 8px">{{ cnt }} 人</span>
          </div>
        </n-space>
      </n-card>
      <n-card v-if="asArray(result.weak_knowledge_points).length" title="薄弱知识点" size="small" :bordered="false" style="margin-top: 12px">
        <n-list>
          <n-list-item v-for="(w, i) in asArray(result.weak_knowledge_points)" :key="i">
            <n-thing>
              <template #header>{{ w.knowledge_point_name || w.knowledge_point_id }}</template>
              <template #header-extra><n-tag size="small" type="error">错误率 {{ w.error_rate }}%</n-tag></template>
              <template #description>
                <div v-if="asArray(w.common_mistakes).length" style="color: #d03050">常见错误：{{ asArray(w.common_mistakes).join('；') }}</div>
                <div v-if="w.suggested_remedial" style="color: #2080f0">建议补救：{{ w.suggested_remedial }}</div>
                <div v-if="asArray(w.affected_students).length" style="color: #888">影响学生：{{ asArray(w.affected_students).length }} 人</div>
              </template>
            </n-thing>
          </n-list-item>
        </n-list>
      </n-card>
      <n-card v-if="asArray(result.strong_knowledge_points).length" title="优势知识点" size="small" :bordered="false" style="margin-top: 12px"><n-space><n-tag v-for="(s, i) in asArray(result.strong_knowledge_points)" :key="i" type="success">{{ s }}</n-tag></n-space></n-card>
      <n-card v-if="result.student_risk_levels && typeof result.student_risk_levels === 'object'" title="风险等级" size="small" :bordered="false" style="margin-top: 12px">
        <n-space vertical>
          <div v-for="(lvl, sid) in result.student_risk_levels" :key="sid"><n-tag size="small" :type="riskType(lvl)">{{ sid }}</n-tag><span style="margin-left: 8px">{{ lvl }}</span></div>
        </n-space>
      </n-card>
    </template>

    <!-- ── 学生画像 student_profile ── -->
    <template v-else-if="result && kind === 'student_profile'">
      <n-descriptions label-placement="left" bordered :column="2" size="small">
        <n-descriptions-item v-if="result.name" :label="label('name')">{{ result.name }}</n-descriptions-item>
        <n-descriptions-item v-if="result.student_id" :label="label('student_id')">{{ result.student_id }}</n-descriptions-item>
        <n-descriptions-item v-if="result.grade" :label="label('grade')">{{ result.grade }}</n-descriptions-item>
        <n-descriptions-item v-if="result.subject" :label="label('subject')">{{ result.subject }}</n-descriptions-item>
        <n-descriptions-item v-if="result.overall_level" :label="label('overall_level')" :span="2"><n-tag :type="riskType(result.overall_level)">{{ result.overall_level }}</n-tag></n-descriptions-item>
        <n-descriptions-item v-if="result.learning_trend" :label="label('learning_trend')" :span="2">{{ result.learning_trend }}</n-descriptions-item>
      </n-descriptions>
      <n-card v-if="result.knowledge_mastery && typeof result.knowledge_mastery === 'object'" title="知识掌握" size="small" :bordered="false" style="margin-top: 12px">
        <n-space vertical>
          <div v-for="(v, k) in result.knowledge_mastery" :key="k">
            <n-tag size="small">{{ label(String(k)) }}</n-tag>
            <n-progress style="display: inline-block; width: 200px; margin-left: 8px" :percentage="Number(v)" :color="scoreColor(Number(v))" />
          </div>
        </n-space>
      </n-card>
      <n-card v-if="asArray(result.risk_indicators).length" title="风险指标" size="small" :bordered="false" style="margin-top: 12px"><n-space vertical><n-tag v-for="(r, i) in asArray(result.risk_indicators)" :key="i" type="warning">{{ r }}</n-tag></n-space></n-card>
      <n-card v-if="asArray(result.recommended_actions).length" title="建议措施" size="small" :bordered="false" style="margin-top: 12px"><n-list><n-list-item v-for="(a, i) in asArray(result.recommended_actions)" :key="i"><n-thing :description="`${i + 1}. ${a}`" /></n-list-item></n-list></n-card>
    </template>

    <!-- ── 错因分析 error_analysis ── -->
    <template v-else-if="result && kind === 'error_analysis'">
      <n-statistic label="错误总数" :value="result.total || 0" style="margin-bottom: 12px" />
      <n-card v-for="(e, i) in asArray(result.errors)" :key="i" :title="`${i + 1}. ${e.error_type || e.knowledge_point_id || ''}`" size="small" :bordered="false" style="margin-top: 12px">
        <template #header-extra><n-tag v-if="e.frequency" size="small" type="error">频次 {{ e.frequency }}</n-tag></template>
        <div v-if="e.knowledge_point_name" style="font-weight: 600; margin-bottom: 4px">知识点：{{ e.knowledge_point_name }}</div>
        <div v-if="e.root_cause" style="color: #d03050; line-height: 1.8"><strong>根因：</strong>{{ e.root_cause }}</div>
        <div v-if="e.remediation" style="color: #2080f0; line-height: 1.8; margin-top: 4px"><strong>补救：</strong>{{ e.remediation }}</div>
        <div v-if="asArray(e.sample_responses).length" style="margin-top: 8px">
          <span style="color: #888">示例回答：</span>
          <n-space style="margin-top: 4px"><n-tag v-for="(s, j) in asArray(e.sample_responses)" :key="j" size="small">{{ s }}</n-tag></n-space>
        </div>
      </n-card>
    </template>

    <!-- ── 补救计划 remedial ── -->
    <template v-else-if="result && kind === 'remedial'">
      <n-descriptions label-placement="left" bordered :column="2" size="small">
        <n-descriptions-item v-if="result.student_id" :label="label('student_id')">{{ result.student_id }}</n-descriptions-item>
        <n-descriptions-item v-if="result.subject" :label="label('subject')">{{ result.subject }}</n-descriptions-item>
        <n-descriptions-item v-if="result.grade" :label="label('grade')">{{ result.grade }}</n-descriptions-item>
        <n-descriptions-item v-if="result.estimated_duration" :label="label('estimated_duration')">{{ result.estimated_duration }}</n-descriptions-item>
        <n-descriptions-item v-if="result.timeline" :label="label('timeline')" :span="2">{{ result.timeline }}</n-descriptions-item>
      </n-descriptions>
      <n-card v-if="asArray(result.weak_points).length" title="薄弱点" size="small" :bordered="false" style="margin-top: 12px">
        <n-list>
          <n-list-item v-for="(w, i) in asArray(result.weak_points)" :key="i">
            <n-thing>
              <template #header>{{ w.knowledge_point_name || w.question_id }}</template>
              <template #description><span v-if="w.knowledge_point_name" style="color: #888">{{ w.knowledge_point_name }}</span></template>
            </n-thing>
          </n-list-item>
        </n-list>
      </n-card>
      <n-card v-if="asArray(result.strategies).length" title="策略" size="small" :bordered="false" style="margin-top: 12px"><n-list><n-list-item v-for="(s, i) in asArray(result.strategies)" :key="i"><n-thing :description="`${i + 1}. ${s}`" /></n-list-item></n-list></n-card>
      <n-card v-if="asArray(result.exercises).length" title="练习" size="small" :bordered="false" style="margin-top: 12px">
        <n-list><n-list-item v-for="(e, i) in asArray(result.exercises)" :key="i"><n-thing :description="`${i + 1}. ${e.question || e}`" /></n-list-item></n-list>
      </n-card>
    </template>

    <!-- ── 技能诊断 diagnose ── -->
    <template v-else-if="result && kind === 'diagnose'">
      <n-descriptions v-if="result.overall_level" label-placement="left" bordered :column="1" size="small" style="margin-bottom: 12px">
        <n-descriptions-item :label="label('overall_level')"><n-tag :type="riskType(result.overall_level)">{{ result.overall_level }}</n-tag></n-descriptions-item>
      </n-descriptions>
      <n-card v-if="asArray(result.mastered_skills).length" title="已掌握" size="small" :bordered="false"><n-space><n-tag v-for="(s, i) in asArray(result.mastered_skills)" :key="i" type="success">{{ s }}</n-tag></n-space></n-card>
      <n-card v-if="asArray(result.developing_skills).length" title="发展中" size="small" :bordered="false" style="margin-top: 12px"><n-space><n-tag v-for="(s, i) in asArray(result.developing_skills)" :key="i" type="warning">{{ s }}</n-tag></n-space></n-card>
      <n-card v-if="asArray(result.needs_support).length" title="需支持" size="small" :bordered="false" style="margin-top: 12px"><n-space><n-tag v-for="(s, i) in asArray(result.needs_support)" :key="i" type="error">{{ s }}</n-tag></n-space></n-card>
      <n-card v-if="asArray(result.recommendations).length" title="建议" size="small" :bordered="false" style="margin-top: 12px"><n-list><n-list-item v-for="(r, i) in asArray(result.recommendations)" :key="i"><n-thing :description="`${i + 1}. ${r}`" /></n-list-item></n-list></n-card>
    </template>

    <!-- ── 学习路径 path ── -->
    <template v-else-if="result && kind === 'path'">
      <n-descriptions label-placement="left" bordered :column="2" size="small">
        <n-descriptions-item v-if="result.student_id" :label="label('student_id')">{{ result.student_id }}</n-descriptions-item>
        <n-descriptions-item v-if="result.grade" :label="label('grade')">{{ result.grade }}</n-descriptions-item>
        <n-descriptions-item v-if="result.subject" :label="label('subject')">{{ result.subject }}</n-descriptions-item>
        <n-descriptions-item v-if="result.estimated_duration" :label="label('estimated_duration')">{{ result.estimated_duration }}</n-descriptions-item>
      </n-descriptions>
      <n-card v-if="asArray(result.prerequisites).length" title="前置知识" size="small" :bordered="false" style="margin-top: 12px"><n-space><n-tag v-for="(p, i) in asArray(result.prerequisites)" :key="i" type="info">{{ p }}</n-tag></n-space></n-card>
      <n-card v-if="asArray(result.goals).length" title="目标" size="small" :bordered="false" style="margin-top: 12px"><n-list><n-list-item v-for="(g, i) in asArray(result.goals)" :key="i"><n-thing :description="`${i + 1}. ${g}`" /></n-list-item></n-list></n-card>
      <n-card v-for="(u, i) in asArray(result.units)" :key="i" :title="u.title || `单元 ${i + 1}`" size="small" :bordered="false" style="margin-top: 12px">
        <n-tag v-if="u.duration" size="small" type="info">{{ u.duration }}</n-tag>
        <n-list v-if="asArray(u.activities).length" style="margin-top: 8px"><n-list-item v-for="(a, j) in asArray(u.activities)" :key="j"><n-thing :description="`${j + 1}. ${a}`" /></n-list-item></n-list>
        <div v-if="u.mastery_criteria" style="margin-top: 8px; font-size: 13px; color: #18a058"><strong>达标标准：</strong>{{ u.mastery_criteria }}</div>
      </n-card>
    </template>

    <!-- ── 资源推荐 recommend ── -->
    <template v-else-if="result && kind === 'recommend'">
      <n-card v-for="(r, i) in asArray(result.resources)" :key="i" :title="r.title || `资源 ${i + 1}`" size="small" :bordered="false" style="margin-bottom: 8px">
        <template #header-extra>
          <n-space>
            <n-tag v-if="r.type" size="small">{{ r.type }}</n-tag>
            <n-tag v-if="r.difficulty" size="small" :type="DIFFICULTY_TYPE[r.difficulty] || 'info'">{{ r.difficulty }}</n-tag>
            <n-tag v-if="r.duration" size="small">{{ r.duration }}</n-tag>
          </n-space>
        </template>
        <div style="line-height: 1.8">{{ r.description }}</div>
      </n-card>
      <n-card v-if="result.practice_plan" title="练习计划" size="small" :bordered="false" style="margin-top: 12px"><div style="line-height: 1.8; white-space: pre-wrap">{{ result.practice_plan }}</div></n-card>
      <n-card v-if="result.parent_tips" title="家长建议" size="small" :bordered="false" style="margin-top: 12px"><div style="line-height: 1.8; white-space: pre-wrap">{{ result.parent_tips }}</div></n-card>
    </template>

    <!-- ── 概念讲解 explain ── -->
    <template v-else-if="result && kind === 'explain'">
      <n-card v-if="result.simple_explanation" title="通俗解释" size="small" :bordered="false"><div style="line-height: 1.8">{{ result.simple_explanation }}</div></n-card>
      <n-card v-if="result.example" title="示例" size="small" :bordered="false" style="margin-top: 12px"><div style="line-height: 1.8; color: #2080f0">{{ result.example }}</div></n-card>
      <n-card v-if="result.visualization" title="可视化" size="small" :bordered="false" style="margin-top: 12px"><div style="line-height: 1.8">{{ result.visualization }}</div></n-card>
      <n-card v-if="asArray(result.common_misconceptions).length" title="常见误区" size="small" :bordered="false" style="margin-top: 12px"><n-list><n-list-item v-for="(m, i) in asArray(result.common_misconceptions)" :key="i"><n-thing :description="`${i + 1}. ${m}`" /></n-list-item></n-list></n-card>
      <n-card v-if="result.extension" title="拓展" size="small" :bordered="false" style="margin-top: 12px"><div style="line-height: 1.8; color: #18a058">{{ result.extension }}</div></n-card>
    </template>

    <!-- ── STEM 项目 stem ── -->
    <template v-else-if="result && kind === 'stem'">
      <n-descriptions v-if="result.title || result.driving_question" label-placement="left" bordered :column="1" size="small">
        <n-descriptions-item v-if="result.title" :label="label('title')">{{ result.title }}</n-descriptions-item>
        <n-descriptions-item v-if="result.driving_question" :label="label('driving_question')">{{ result.driving_question }}</n-descriptions-item>
      </n-descriptions>
      <n-card v-if="asArray(result.objectives).length" title="目标" size="small" :bordered="false" style="margin-top: 12px"><n-list><n-list-item v-for="(o, i) in asArray(result.objectives)" :key="i"><n-thing :description="`${i + 1}. ${o}`" /></n-list-item></n-list></n-card>
      <n-card v-if="asArray(result.materials).length" title="材料" size="small" :bordered="false" style="margin-top: 12px"><n-space><n-tag v-for="(m, i) in asArray(result.materials)" :key="i" type="info">{{ m }}</n-tag></n-space></n-card>
      <n-card v-if="asArray(result.procedure).length" title="步骤" size="small" :bordered="false" style="margin-top: 12px"><n-list><n-list-item v-for="(p, i) in asArray(result.procedure)" :key="i"><n-thing :description="`${i + 1}. ${p}`" /></n-list-item></n-list></n-card>
      <n-card v-if="asArray(result.expected_outcomes).length" title="预期成果" size="small" :bordered="false" style="margin-top: 12px"><n-list><n-list-item v-for="(o, i) in asArray(result.expected_outcomes)" :key="i"><n-thing :description="`${i + 1}. ${o}`" /></n-list-item></n-list></n-card>
      <n-card v-if="result.rubric" title="评价标准" size="small" :bordered="false" style="margin-top: 12px"><div style="line-height: 1.8; white-space: pre-wrap">{{ typeof result.rubric === 'string' ? result.rubric : pretty(result.rubric) }}</div></n-card>
    </template>

    <!-- ── 语言活动 lang_activity ── -->
    <template v-else-if="result && kind === 'lang_activity'">
      <n-descriptions v-if="result.title || result.objective" label-placement="left" bordered :column="1" size="small">
        <n-descriptions-item v-if="result.title" :label="label('title')">{{ result.title }}</n-descriptions-item>
        <n-descriptions-item v-if="result.objective" :label="label('objective')">{{ result.objective }}</n-descriptions-item>
      </n-descriptions>
      <n-card v-if="asArray(result.materials).length" title="材料" size="small" :bordered="false" style="margin-top: 12px"><n-space><n-tag v-for="(m, i) in asArray(result.materials)" :key="i" type="info">{{ m }}</n-tag></n-space></n-card>
      <n-card v-if="asArray(result.procedure).length" title="步骤" size="small" :bordered="false" style="margin-top: 12px"><n-list><n-list-item v-for="(p, i) in asArray(result.procedure)" :key="i"><n-thing :description="`${i + 1}. ${p}`" /></n-list-item></n-list></n-card>
      <n-card v-if="result.differentiation && typeof result.differentiation === 'object'" title="分层" size="small" :bordered="false" style="margin-top: 12px">
        <n-space vertical>
          <div v-for="(v, k) in result.differentiation" :key="k"><n-tag size="small" :type="k === 'beginner' ? 'warning' : k === 'advanced' ? 'success' : 'info'">{{ layerName(k) }}</n-tag><span style="margin-left: 8px; font-size: 13px">{{ v }}</span></div>
        </n-space>
      </n-card>
    </template>

    <!-- ── 课标对齐 align ── -->
    <template v-else-if="result && kind === 'align'">
      <n-descriptions label-placement="left" bordered :column="2" size="small">
        <n-descriptions-item v-if="result.subject" :label="label('subject')">{{ result.subject }}</n-descriptions-item>
        <n-descriptions-item v-if="result.grade" :label="label('grade')">{{ result.grade }}</n-descriptions-item>
        <n-descriptions-item v-if="result.topic" :label="label('topic')">{{ result.topic }}</n-descriptions-item>
        <n-descriptions-item v-if="result.prerequisite_count !== undefined" :label="label('prerequisite_count')">{{ result.prerequisite_count }}</n-descriptions-item>
      </n-descriptions>
      <n-card v-if="asArray(result.must_cover).length" title="必覆盖" size="small" :bordered="false" style="margin-top: 12px"><n-list><n-list-item v-for="(m, i) in asArray(result.must_cover)" :key="i"><n-thing :description="`${i + 1}. ${m}`" /></n-list-item></n-list></n-card>
      <n-card v-if="asArray(result.optional_advanced).length" title="进阶可选" size="small" :bordered="false" style="margin-top: 12px"><n-space><n-tag v-for="(o, i) in asArray(result.optional_advanced)" :key="i" type="success">{{ o }}</n-tag></n-space></n-card>
      <n-card v-if="asArray(result.suggested_objectives).length" title="建议目标" size="small" :bordered="false" style="margin-top: 12px"><n-list><n-list-item v-for="(o, i) in asArray(result.suggested_objectives)" :key="i"><n-thing :description="`${i + 1}. ${o}`" /></n-list-item></n-list></n-card>
      <n-card v-if="asArray(result.knowledge_points).length" title="知识点" size="small" :bordered="false" style="margin-top: 12px">
        <n-list>
          <n-list-item v-for="(k, i) in asArray(result.knowledge_points)" :key="i">
            <n-thing>
              <template #header>{{ k.name || k.id }}</template>
              <template #description><span v-if="k.description" style="color: #888">{{ k.description }}</span></template>
            </n-thing>
          </n-list-item>
        </n-list>
      </n-card>
    </template>

    <!-- ── 覆盖率 coverage ── -->
    <template v-else-if="result && kind === 'coverage'">
      <n-space align="center" style="margin-bottom: 12px">
        <n-statistic label="已覆盖" :value="`${result.covered_points || 0} / ${result.total_points || 0}`" />
        <n-progress type="circle" :percentage="Math.round((result.coverage_ratio || 0) * 100)" :color="scoreColor((result.coverage_ratio || 0) * 100)" />
      </n-space>
      <n-card v-if="asArray(result.missing_points).length" title="缺失知识点" size="small" :bordered="false"><n-space vertical><n-tag v-for="(m, i) in asArray(result.missing_points)" :key="i" type="error">{{ m }}</n-tag></n-space></n-card>
    </template>

    <!-- ── 安全检查 safety ── -->
    <template v-else-if="result && kind === 'safety'">
      <n-space align="center" style="margin-bottom: 12px">
        <n-tag :type="result.is_safe ? 'success' : 'error'" size="large">{{ result.is_safe ? '安全' : '不安全' }}</n-tag>
        <n-tag v-if="result.decision" :type="result.decision === 'allow' ? 'success' : 'error'">{{ result.decision }}</n-tag>
        <n-tag v-if="result.risk_level" :type="riskType(result.risk_level)">{{ result.risk_level }}</n-tag>
      </n-space>
      <n-card v-if="result.summary" title="摘要" size="small" :bordered="false"><div style="line-height: 1.8">{{ result.summary }}</div></n-card>
      <n-card v-if="asArray(result.flagged_words).length" title="标记词" size="small" :bordered="false" style="margin-top: 12px"><n-space><n-tag v-for="(w, i) in asArray(result.flagged_words)" :key="i" type="error">{{ w }}</n-tag></n-space></n-card>
      <n-card v-if="asArray(result.age_issues).length" title="年龄适宜性问题" size="small" :bordered="false" style="margin-top: 12px"><n-list><n-list-item v-for="(a, i) in asArray(result.age_issues)" :key="i"><n-thing :description="`${i + 1}. ${a}`" /></n-list-item></n-list></n-card>
      <n-card v-if="result.filtered_text" title="过滤后文本" size="small" :bordered="false" style="margin-top: 12px"><div style="line-height: 1.8; white-space: pre-wrap">{{ result.filtered_text }}</div></n-card>
    </template>

    <!-- ── 脱敏 desensitize ── -->
    <template v-else-if="result && kind === 'desensitize'">
      <n-space align="center" style="margin-bottom: 12px">
        <n-statistic label="原始数量" :value="result.result?.original_count || 0" />
        <n-statistic label="脱敏数量" :value="result.result?.anonymized_count || 0" />
      </n-space>
      <n-card v-if="result.result?.masked_fields && asArray(result.result.masked_fields).length" title="掩码字段" size="small" :bordered="false"><n-space><n-tag v-for="(f, i) in asArray(result.result.masked_fields)" :key="i" type="info">{{ f }}</n-tag></n-space></n-card>
      <n-card v-if="asArray(result.desensitized_records).length" title="脱敏记录" size="small" :bordered="false" style="margin-top: 12px">
        <n-collapse>
          <n-collapse-item v-for="(r, i) in asArray(result.desensitized_records)" :key="i" :title="`记录 ${i + 1}`" :name="String(i)">
            <n-code :code="pretty(r)" language="json" />
          </n-collapse-item>
        </n-collapse>
      </n-card>
    </template>

    <!-- ── 评分量规 rubric (LLM dict, 变长) ── -->
    <template v-else-if="result && kind === 'rubric'">
      <n-collapse>
        <n-collapse-item v-for="(v, k) in result" :key="k" :title="label(String(k))" :name="String(k)">
          <div v-if="typeof v === 'string'" style="line-height: 1.8; white-space: pre-wrap">{{ v }}</div>
          <n-list v-else-if="Array.isArray(v)">
            <n-list-item v-for="(item, j) in v" :key="j"><n-thing :description="typeof item === 'string' ? item : pretty(item)" /></n-list-item>
          </n-list>
          <n-code v-else :code="pretty(v)" language="json" />
        </n-collapse-item>
      </n-collapse>
    </template>

    <!-- ── 通用 generic fallback (最后的 JSON 兜底) ── -->
    <template v-else-if="result">
      <n-descriptions v-if="simpleFields.length" label-placement="left" bordered :column="2" size="small">
        <n-descriptions-item v-for="f in simpleFields" :key="f.label" :label="f.label">{{ f.value }}</n-descriptions-item>
      </n-descriptions>
      <n-collapse v-if="Object.keys(result).some(k => Array.isArray(result[k]) || (typeof result[k] === 'object' && result[k] !== null))" style="margin-top: 12px">
        <n-collapse-item v-for="s in Object.entries(result).filter(([k, v]) => Array.isArray(v) || (typeof v === 'object' && v !== null)).map(([k, v]) => ({ key: k, value: v }))" :key="s.key" :title="label(s.key)" :name="s.key">
          <n-code :code="pretty(s.value)" language="json" />
        </n-collapse-item>
      </n-collapse>
    </template>

    <n-empty v-else description="尚未生成" />
  </n-card>
</template>

<style>
@keyframes pulse { 0%,100% { opacity: 0.4 } 50% { opacity: 1 } }
</style>

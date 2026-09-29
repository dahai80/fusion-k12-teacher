<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { NButton, NSlider, NSelect, NSpace, NTag, NCollapse, NCollapseItem, NCode } from 'naive-ui'

const props = defineProps<{ scene: any }>()

const canvasRef = ref<HTMLCanvasElement | null>(null)
const progress = ref(0)
const playing = ref(false)
const speedFactor = ref(1)
let rafId: number | null = null
let lastTs = 0

const speedOpts = [
  { label: '0.5x', value: 0.5 },
  { label: '1x', value: 1 },
  { label: '2x', value: 2 },
  { label: '4x', value: 4 },
]

const tpl = computed(() => props.scene?.template_type || '')
const isTrainBridge = computed(() => tpl.value.includes('train') || tpl.value.includes('bridge'))
const isCutting = computed(() => tpl.value.includes('cutting'))
const isQueue = computed(() => tpl.value === 'queue_counting')
const isFence = computed(() => tpl.value === 'fence_against_wall')
const isUnitary = computed(() => tpl.value === 'unitary_method')
const isChickenRabbit = computed(() => tpl.value === 'chicken_rabbit')
const isMotion = computed(() => tpl.value === 'basic_motion')
const isWork = computed(() => tpl.value === 'work_problem')
const isAverage = computed(() => tpl.value === 'average_problem')
const isOverlap = computed(() => tpl.value === 'overlap_splice')
const isRoundTrip = computed(() => tpl.value === 'round_trip')
const isSumMultiple = computed(() => tpl.value === 'sum_multiple')
const isSprinkler = computed(() => tpl.value === 'sprinkler_area')
const isTreePlanting = computed(() => tpl.value === 'tree_planting')
const isDisplacement = computed(() => tpl.value === 'displacement_volume')
const isProfitLoss = computed(() => tpl.value === 'profit_loss')
const isInterest = computed(() => tpl.value === 'simple_interest')
const isTiered = computed(() => tpl.value === 'tiered_pricing')
const isWeekday = computed(() => tpl.value === 'weekday_calc')
const isSemicircle = computed(() => tpl.value === 'semicircle_perimeter')
const isCuboidCombine = computed(() => tpl.value === 'cuboid_combine_surface')
const isCombination = computed(() => tpl.value === 'combination_count')
const isUnitaryCombined = computed(() => tpl.value === 'unitary_combined')
const isRedundant = computed(() => tpl.value === 'redundant_filter')
const isFoldCut = computed(() => tpl.value === 'fold_cut')
const isStarsBars = computed(() => tpl.value === 'stars_bars')
const isSpecial = computed(() => isCutting.value || isQueue.value || isFence.value || isUnitary.value || isChickenRabbit.value || isMotion.value || isWork.value || isAverage.value || isOverlap.value || isRoundTrip.value || isSumMultiple.value || isSprinkler.value || isTreePlanting.value || isDisplacement.value || isProfitLoss.value || isInterest.value || isTiered.value || isWeekday.value || isSemicircle.value || isCuboidCombine.value || isCombination.value || isUnitaryCombined.value || isRedundant.value || isFoldCut.value || isStarsBars.value)

// 通用路径 (S1解析→S2 DSL→S3渲染): 后端 generic 管线产出的可视化原语 DSL
const isGeneric = computed(() => props.scene?.meta?.pipeline === 'generic' || tpl.value === 'generic_solve')
// 分步推导链 (Gemini 方案融合): 按进度定位当前步骤, HUD 显示标题/公式/结果
const genericPipeline = computed<any[]>(() => props.scene?.canvas_config?.pipeline || [])
const currentStep = computed(() => {
  const steps = genericPipeline.value
  if (!steps.length) return null
  const p = progress.value
  const n = steps.length
  // 步骤 i 占 [i/n, (i+1)/n), 最后一步到 100%
  const idx = Math.min(n - 1, Math.floor((p / 100) * n))
  return steps[idx] || null
})
const genericVisual = computed(() => {
  const v = props.scene?.canvas_config?.visual || {}
  return {
    kind: String(v.kind || 'number_line'),
    startLabel: String(v.start_label || ''),
    endLabel: String(v.end_label || ''),
    title: String(v.title || ''),
    unit: String(v.unit || ''),
    segments: Array.isArray(v.segments) ? v.segments : [],
  }
})

const ent = computed(() => {
  const list = props.scene?.entities || []
  const byId: Record<string, any> = {}
  for (const e of list) byId[e.id] = e
  const bridge = list.find((e: any) => /bridge|桥/.test(e.id + e.label)) || list.find((e: any) => e.type === 'static_structure')
  const train = list.find((e: any) => /train|车/.test(e.id + e.label)) || list.find((e: any) => e.type === 'moving_object')
  const tl = props.scene?.timeline || {}
  const totalDist = Number(tl.total_distance || 0)
  const totalTime = Number(tl.total_time || 0)
  const speed = totalTime > 0 ? totalDist / totalTime : 0
  const obj = list.find((e: any) => e.id === 'object' || /木|绳|object/.test(e.id + e.label))
  const nSeg = obj ? Number(obj.value) || 0 : 0
  const nCuts = Number(byId['n_cuts']?.value || 0)
  const tPer = nCuts > 0 && totalTime > 0 ? totalTime / nCuts : 0
  const v = (k: string) => Number(byId[k]?.value || 0)
  return {
    bridge, train, totalDist, totalTime, speed, obj, nSeg, nCuts, tPer,
    rankFront: v('rank_front'), rankBehind: v('rank_behind'), totalPeople: v('total_people'),
    fenceLen: v('length'), perimeter: v('perimeter'), width: v('width'), area: v('area'),
    nItems: v('n_items'), totalValue: v('total_value'), nTarget: v('n_target'),
    unitValue: v('unit_value'), targetValue: v('target_value'),
    heads: v('heads'), legs: v('legs'), rabbit: v('rabbit'), chicken: v('chicken'),
    distance: v('distance'), motionSpeed: v('speed'), motionTime: v('time'),
    worker1: v('worker1_days'), worker2: v('worker2_days'), totalDays: v('total_days'),
    totalSum: v('total_sum'), count: v('count'), average: v('average'),
    board1: v('board1'), board2: v('board2'), overlap: v('overlap'), totalLength: v('total_length'),
    trips: v('trips'), totalDistance: v('total_distance'),
    sumVal: v('sum'), multiple: v('multiple'), small: v('small'), big: v('big'),
    sprinklerSpeed: v('speed'), sprinklerWidth: v('width'), sprinklerTime: v('time'), sprinklerLen: v('length'), sprinklerArea: v('area'),
    roadLen: v('length'), spacing: v('spacing'), modeCode: v('mode_code'), segments: v('segments'), trees: v('trees'),
    tankLen: v('length'), tankWidth: v('width'), rise: v('rise'), volume: v('volume'),
    surplus: v('surplus'), deficit: v('deficit'), diff: v('diff'), people: v('people'),
    principal: v('principal'), rate: v('rate'), years: v('years'), interest: v('interest'), interestTotal: v('total'),
    baseDistance: v('base_distance'), basePrice: v('base_price'), unitPrice: v('unit_price'), totalDist2: v('total_distance'), extraDistance: v('extra_distance'), totalPrice: v('total_price'),
    startDay: v('start_day'), addDays: v('add_days'), targetDay: v('target_day'),
    radius: v('radius'), arc: v('arc'), diameter: v('diameter'), semicirclePerimeter: v('perimeter'),
    boxLen: v('length'), boxWidth: v('width'), boxHeight: v('height'), minFace: v('min_face'), maxFace: v('max_face'), singleSa: v('single_sa'), maxSa: v('max_sa'), minSa: v('min_sa'),
    nItems1: v('n_items1'), nItems2: v('n_items2'), combinations: v('combinations'),
    nPeople: v('n_people'), nDays: v('n_days'), totalWork: v('total_work'), targetPeople: v('target_people'), targetDays: v('target_days'), unitRate: v('unit_rate'), workResult: v('result'),
    redTotal: v('total'), redRemoved: v('removed'), redDistraction: v('distraction'), redRemaining: v('remaining'),
    folds: v('folds'), foldSegments: v('segments'),
    sbItems: v('n_items'), sbBins: v('n_bins'), sbWays: v('ways'), sbMinPer: v('min_per') || 1,
  }
})

const milestones = computed(() => props.scene?.timeline?.milestones || [])

const teachingHint = computed(() => {
  const raw = String(props.scene?.pedagogy?.misconception_breakdown || '')
  if (raw) return raw
  if (isTrainBridge.value) return '小学生易把大桥长度当作总路程。看红色车头轨迹线: 完全过桥时车头实际行驶 = 桥长 + 车长。'
  if (isStarsBars.value) {
    const m = ent.value.sbMinPer || 1
    return m <= 1 ? '相同物品放不同容器, 每篮至少1, 用隔板法 C(n-1, k-1), 非排列非乘法。' : `每容器最少${m}块, 先预留 ${m}×k 块保底, 剩余再用隔板法 C(n-m×k+k-1, k-1)。`
  }
  return ''
})

function jumpMilestone(pct: number) {
  progress.value = Number(pct) || 0
}

const status = computed(() => {
  const e = ent.value
  if (isCutting.value) {
    const cutsDone = Math.floor((progress.value / 100) * e.nCuts)
    const t = cutsDone * e.tPer
    return { cur: cutsDone, t, totalDist: e.nCuts, totalTime: e.totalTime, speed: e.tPer, label: '已锯 X/Y 次' }
  }
  if (isQueue.value) {
    return { cur: Math.floor((progress.value / 100) * e.totalPeople), t: 0, totalDist: e.totalPeople, totalTime: e.totalPeople, speed: 0, label: '人数 X/Y' }
  }
  if (isChickenRabbit.value) {
    return { cur: Math.floor((progress.value / 100) * (e.rabbit + e.chicken)), t: 0, totalDist: e.rabbit + e.chicken, totalTime: e.rabbit + e.chicken, speed: 0, label: '只数 X/Y' }
  }
  if (isWork.value) {
    return { cur: (progress.value / 100) * e.totalDays, t: 0, totalDist: e.totalDays, totalTime: e.totalDays, speed: 0, label: '天数 X/Y' }
  }
  if (isAverage.value) {
    return { cur: (progress.value / 100) * e.average, t: 0, totalDist: e.average, totalTime: e.average, speed: 0, label: '平均 X/Y' }
  }
  if (isFence.value) {
    return { cur: (progress.value / 100) * e.area, t: 0, totalDist: e.area, totalTime: e.area, speed: 0, label: '面积 X/Y' }
  }
  if (isUnitary.value) {
    return { cur: (progress.value / 100) * e.targetValue, t: 0, totalDist: e.targetValue, totalTime: e.targetValue, speed: 0, label: '总价 X/Y' }
  }
  if (isOverlap.value) {
    return { cur: (progress.value / 100) * e.totalLength, t: 0, totalDist: e.totalLength, totalTime: e.totalLength, speed: 0, label: '总长 X/Y' }
  }
  if (isRoundTrip.value) {
    return { cur: (progress.value / 100) * e.totalDistance, t: 0, totalDist: e.totalDistance, totalTime: e.totalDistance, speed: 0, label: '总程 X/Y' }
  }
  if (isSumMultiple.value) {
    return { cur: (progress.value / 100) * e.big, t: 0, totalDist: e.big, totalTime: e.big, speed: 0, label: '大数 X/Y' }
  }
  if (isSprinkler.value) {
    return { cur: (progress.value / 100) * e.sprinklerArea, t: 0, totalDist: e.sprinklerArea, totalTime: e.sprinklerArea, speed: 0, label: '面积 X/Y' }
  }
  if (isTreePlanting.value) {
    return { cur: Math.floor((progress.value / 100) * e.trees), t: 0, totalDist: e.trees, totalTime: e.trees, speed: 0, label: '棵数 X/Y' }
  }
  if (isDisplacement.value) {
    return { cur: (progress.value / 100) * e.volume, t: 0, totalDist: e.volume, totalTime: e.volume, speed: 0, label: '体积 X/Y' }
  }
  if (isProfitLoss.value) {
    return { cur: (progress.value / 100) * e.people, t: 0, totalDist: e.people, totalTime: e.people, speed: 0, label: '人数 X/Y' }
  }
  if (isInterest.value) {
    return { cur: (progress.value / 100) * e.interest, t: 0, totalDist: e.interest, totalTime: e.interestTotal, speed: 0, label: '利息 X/Y' }
  }
  if (isTiered.value) {
    return { cur: (progress.value / 100) * e.totalPrice, t: 0, totalDist: e.totalPrice, totalTime: e.totalPrice, speed: 0, label: '车费 X/Y' }
  }
  if (isWeekday.value) {
    return { cur: Math.floor((progress.value / 100) * e.addDays), t: 0, totalDist: e.targetDay, totalTime: e.addDays, speed: 0, label: '天数 X/Y' }
  }
  if (isSemicircle.value) {
    return { cur: (progress.value / 100) * e.perimeter, t: 0, totalDist: e.perimeter, totalTime: e.perimeter, speed: 0, label: '周长 X/Y' }
  }
  if (isCuboidCombine.value) {
    return { cur: (progress.value / 100) * e.maxSa, t: 0, totalDist: e.maxSa, totalTime: e.minSa, speed: 0, label: '表面积 X/Y' }
  }
  if (isCombination.value) {
    return { cur: Math.floor((progress.value / 100) * e.combinations), t: 0, totalDist: e.combinations, totalTime: e.combinations, speed: 0, label: '搭配 X/Y' }
  }
  if (isUnitaryCombined.value) {
    return { cur: (progress.value / 100) * e.workResult, t: 0, totalDist: e.workResult, totalTime: e.workResult, speed: 0, label: '产量 X/Y' }
  }
  if (isRedundant.value) {
    return { cur: Math.floor((progress.value / 100) * e.redRemaining), t: 0, totalDist: e.redRemaining, totalTime: e.redRemaining, speed: 0, label: '剩余 X/Y' }
  }
  if (isFoldCut.value) {
    return { cur: Math.floor((progress.value / 100) * e.foldSegments), t: 0, totalDist: e.foldSegments, totalTime: e.foldSegments, speed: 0, label: '段数 X/Y' }
  }
  if (isStarsBars.value) {
    return { cur: Math.floor((progress.value / 100) * e.sbWays), t: 0, totalDist: e.sbWays, totalTime: e.sbWays, speed: 0, label: '放法 X/Y' }
  }
  const cur = (progress.value / 100) * e.totalDist
  const t = e.speed > 0 ? cur / e.speed : 0
  return { cur, t, totalDist: e.totalDist, totalTime: e.totalTime, speed: e.speed, label: '' }
})

function draw() {
  const cv = canvasRef.value
  if (!cv) return
  const ctx = cv.getContext('2d')!
  const W = cv.width, H = cv.height
  ctx.clearRect(0, 0, W, H)
  ctx.fillStyle = '#f8fafc'
  ctx.fillRect(0, 0, W, H)

  if (isGeneric.value) {
    drawGenericScene(ctx, W, H)
  } else if (isCutting.value) {
    drawCutting(ctx, W, H)
  } else if (isQueue.value) {
    drawQueue(ctx, W, H)
  } else if (isFence.value) {
    drawFence(ctx, W, H)
  } else if (isUnitary.value) {
    drawUnitary(ctx, W, H)
  } else if (isChickenRabbit.value) {
    drawChickenRabbit(ctx, W, H)
  } else if (isMotion.value) {
    drawMotion(ctx, W, H)
  } else if (isWork.value) {
    drawWork(ctx, W, H)
  } else if (isAverage.value) {
    drawAverage(ctx, W, H)
  } else if (isOverlap.value) {
    drawOverlap(ctx, W, H)
  } else if (isRoundTrip.value) {
    drawRoundTrip(ctx, W, H)
  } else if (isSumMultiple.value) {
    drawSumMultiple(ctx, W, H)
  } else if (isSprinkler.value) {
    drawSprinkler(ctx, W, H)
  } else if (isTreePlanting.value) {
    drawTreePlanting(ctx, W, H)
  } else if (isDisplacement.value) {
    drawDisplacement(ctx, W, H)
  } else if (isProfitLoss.value) {
    drawProfitLoss(ctx, W, H)
  } else if (isInterest.value) {
    drawInterest(ctx, W, H)
  } else if (isTiered.value) {
    drawTiered(ctx, W, H)
  } else if (isWeekday.value) {
    drawWeekday(ctx, W, H)
  } else if (isSemicircle.value) {
    drawSemicircle(ctx, W, H)
  } else if (isCuboidCombine.value) {
    drawCuboidCombine(ctx, W, H)
  } else if (isCombination.value) {
    drawCombination(ctx, W, H)
  } else if (isUnitaryCombined.value) {
    drawUnitaryCombined(ctx, W, H)
  } else if (isRedundant.value) {
    drawRedundant(ctx, W, H)
  } else if (isFoldCut.value) {
    drawFoldCut(ctx, W, H)
  } else if (isStarsBars.value) {
    drawStarsBars(ctx, W, H)
  } else if (isTrainBridge.value && ent.value.bridge && ent.value.train) {
    drawTrainBridge(ctx, W, H)
  } else {
    drawGeneric(ctx, W, H)
  }
}

function drawDashed(ctx: CanvasRenderingContext2D, x1: number, y1: number, x2: number, y2: number, color: string) {
  ctx.save()
  ctx.strokeStyle = color
  ctx.lineWidth = 1.5
  ctx.setLineDash([4, 4])
  ctx.beginPath()
  ctx.moveTo(x1, y1)
  ctx.lineTo(x2, y2)
  ctx.stroke()
  ctx.restore()
}

function drawText(ctx: CanvasRenderingContext2D, s: string, x: number, y: number, color: string, align: CanvasTextAlign = 'left', font = '11px sans-serif') {
  ctx.fillStyle = color
  ctx.font = font
  ctx.textAlign = align
  ctx.fillText(s, x, y)
}

function drawCutting(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const { nSeg, nCuts, tPer, totalTime } = ent.value
  if (nCuts <= 0) {
    drawText(ctx, '无需锯切 (1段 = 0次)', W / 2, H / 2, '#64748b', 'center', '16px sans-serif')
    return
  }
  const marginX = 80
  const logY = H / 2 - 20
  const availPx = W - marginX * 2
  const segPx = availPx / nSeg
  const logH = 28
  const cutsDone = Math.floor((progress.value / 100) * nCuts)

  // 画原木段
  for (let i = 0; i < nSeg; i++) {
    const segStart = marginX + i * segPx
    const isSeparated = i > 0 && i <= cutsDone
    const offset = isSeparated ? 24 : 0
    ctx.fillStyle = '#a16207'
    ctx.beginPath()
    ctx.roundRect(segStart + (isSeparated ? 6 : 0), logY + offset, segPx - (isSeparated ? 12 : 4), logH, [6, 6, 6, 6])
    ctx.fill()
    // 木纹
    ctx.strokeStyle = '#78350f'
    ctx.lineWidth = 1
    for (let g = 1; g < 4; g++) {
      ctx.beginPath()
      ctx.moveTo(segStart + (isSeparated ? 6 : 0) + 4, logY + offset + (logH / 4) * g)
      ctx.lineTo(segStart + (isSeparated ? 6 : 0) + segPx - (isSeparated ? 12 : 4) - 4, logY + offset + (logH / 4) * g)
      ctx.stroke()
    }
    // 段标号
    drawText(ctx, `第${i + 1}段`, segStart + segPx / 2, logY + offset + logH + 14, '#78350f', 'center', '11px sans-serif')
  }

  // 画锯切口标记 (红锯齿线)
  for (let i = 0; i < nCuts; i++) {
    const cutX = marginX + (i + 1) * segPx
    const isCut = i < cutsDone
    drawDashed(ctx, cutX, logY - 30, cutX, logY + 70, isCut ? '#dc2626' : '#94a3b8')
    // 锯齿图标
    ctx.strokeStyle = isCut ? '#dc2626' : '#94a3b8'
    ctx.lineWidth = 2
    ctx.beginPath()
    for (let z = 0; z < 5; z++) {
      const zx = cutX - 6 + (z % 2 === 0 ? 0 : 12)
      const zy = logY - 26 + z * 4
      if (z === 0) ctx.moveTo(zx, zy)
      else ctx.lineTo(zx, zy)
    }
    ctx.stroke()
    drawText(ctx, `锯${i + 1}`, cutX, logY - 32, isCut ? '#dc2626' : '#94a3b8', 'center', 'bold 10px sans-serif')
  }

  // 里程碑标记
  for (const m of milestones.value) {
    const mx = marginX + (Number(m.progress_percentage) / 100) * availPx
    drawDashed(ctx, mx, logY + 80, mx, logY + 100, '#a855f7')
    drawText(ctx, m.event_name, mx, logY + 112, '#a855f7', 'center', '10px sans-serif')
  }
}

function drawQueue(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const { rankFront, rankBehind, totalPeople } = ent.value
  const marginX = 60
  const cy = H / 2
  const availPx = W - marginX * 2
  const personPx = Math.min(40, availPx / Math.max(totalPeople, 1))
  const startX = marginX + (availPx - personPx * totalPeople) / 2
  const mingIdx = rankFront - 1
  for (let i = 0; i < totalPeople; i++) {
    const x = startX + i * personPx
    const isMing = i === mingIdx
    const isFront = i < mingIdx
    ctx.fillStyle = isMing ? '#dc2626' : isFront ? '#3b82f6' : '#10b981'
    ctx.beginPath()
    ctx.arc(x + personPx / 2, cy - 8, personPx / 3, 0, Math.PI * 2)
    ctx.fill()
    ctx.fillRect(x + personPx / 2 - personPx / 6, cy - 6, personPx / 3, 16)
    drawText(ctx, `${i + 1}`, x + personPx / 2, cy + 22, '#475569', 'center', '10px sans-serif')
    if (isMing) {
      drawDashed(ctx, x + personPx / 2, 40, x + personPx / 2, cy + 30, '#dc2626')
      drawText(ctx, '小明', x + personPx / 2, 32, '#dc2626', 'center', 'bold 11px sans-serif')
    }
  }
  const cur = Math.floor((progress.value / 100) * totalPeople)
  drawText(ctx, `从前第${rankFront} + 从后第${rankBehind} - 1 = ${totalPeople}人 (当前数到${cur})`, W / 2, H - 16, '#334155', 'center', '12px sans-serif')
  for (const m of milestones.value) {
    const mx = startX + (Number(m.progress_percentage) / 100) * (personPx * totalPeople)
    drawDashed(ctx, mx, cy - 30, mx, cy - 18, '#a855f7')
  }
}

function drawFence(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const { fenceLen, perimeter, width, area } = ent.value
  const marginX = 80
  const wallY = H / 2 - 60
  const baseY = H / 2 + 60
  const availPx = W - marginX * 2
  const lenPx = Math.min(availPx * 0.7, fenceLen * 20)
  const widPx = width * 20
  const lx = (W - lenPx) / 2
  const rx = lx + lenPx
  ctx.strokeStyle = '#475569'
  ctx.lineWidth = 6
  ctx.beginPath()
  ctx.moveTo(0, wallY)
  ctx.lineTo(W, wallY)
  ctx.stroke()
  drawText(ctx, '墙', 20, wallY - 10, '#475569', 'left', 'bold 12px sans-serif')
  ctx.strokeStyle = '#a16207'
  ctx.lineWidth = 4
  ctx.beginPath()
  ctx.moveTo(lx, wallY)
  ctx.lineTo(lx, baseY)
  ctx.lineTo(rx, baseY)
  ctx.lineTo(rx, wallY)
  ctx.stroke()
  ctx.fillStyle = 'rgba(34,197,94,0.12)'
  ctx.fillRect(lx, wallY, lenPx, baseY - wallY)
  drawText(ctx, `长 ${fenceLen}m`, (lx + rx) / 2, baseY + 20, '#334155', 'center', 'bold 12px sans-serif')
  drawText(ctx, `宽 ${width}m`, lx - 14, (wallY + baseY) / 2, '#334155', 'right', '12px sans-serif')
  drawText(ctx, `周长(三边) = 2×${width} + ${fenceLen} = ${perimeter}m`, W / 2, H - 30, '#334155', 'center', '12px sans-serif')
  drawText(ctx, `面积 = ${fenceLen} × ${width} = ${area}m² (当前 ${Math.round((progress.value/100)*area)}m²)`, W / 2, H - 12, '#16a34a', 'center', 'bold 12px sans-serif')
}

function drawUnitary(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const { nItems, totalValue, nTarget, unitValue, targetValue } = ent.value
  const marginX = 60
  const groupY = H / 2 - 30
  const targetY = H / 2 + 50
  const itemPx = 28
  const groupW = nItems * itemPx
  const drawItems = (x: number, y: number, n: number, color: string, label: string) => {
    for (let i = 0; i < n; i++) {
      ctx.fillStyle = color
      ctx.fillRect(x + i * itemPx, y, itemPx - 4, 24)
      ctx.strokeStyle = '#fff'
      ctx.strokeRect(x + i * itemPx, y, itemPx - 4, 24)
    }
    drawText(ctx, label, x + groupW / 2, y - 8, '#334155', 'center', '11px sans-serif')
  }
  const gx = (W - groupW) / 2
  drawItems(gx, groupY, nItems, '#3b82f6', `${nItems}件 = ${totalValue}元`)
  drawText(ctx, `单价 = ${totalValue} ÷ ${nItems} = ${unitValue}元/件`, W / 2, groupY + 38, '#dc2626', 'center', 'bold 12px sans-serif')
  const tx = (W - nTarget * itemPx) / 2
  drawItems(tx, targetY, nTarget, '#16a34a', `${nTarget}件 = ${targetValue}元`)
  drawText(ctx, `目标 = ${unitValue} × ${nTarget} = ${targetValue}元 (当前 ${Math.round((progress.value/100)*targetValue)}元)`, W / 2, H - 12, '#16a34a', 'center', 'bold 12px sans-serif')
}

function drawChickenRabbit(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const { heads, legs, rabbit, chicken } = ent.value
  const marginX = 60
  const cy = H / 2
  const total = chicken + rabbit
  const itemPx = Math.min(50, (W - marginX * 2) / Math.max(total, 1))
  const startX = (W - itemPx * total) / 2
  const cur = Math.floor((progress.value / 100) * total)
  for (let i = 0; i < total; i++) {
    const x = startX + i * itemPx
    const isRabbit = i >= chicken
    const shown = i < cur
    ctx.fillStyle = shown ? (isRabbit ? '#a855f7' : '#f59e0b') : '#cbd5e1'
    ctx.beginPath()
    ctx.arc(x + itemPx / 2, cy - 6, itemPx / 4, 0, Math.PI * 2)
    ctx.fill()
    ctx.fillRect(x + itemPx / 2 - itemPx / 6, cy - 4, itemPx / 3, 14)
    drawText(ctx, isRabbit ? '兔' : '鸡', x + itemPx / 2, cy + 24, isRabbit ? '#a855f7' : '#f59e0b', 'center', '11px sans-serif')
  }
  drawText(ctx, `假设全鸡: ${heads}头应${heads * 2}腿, 实际${legs}腿, 差${legs - heads * 2}`, W / 2, 40, '#334155', 'center', '11px sans-serif')
  drawText(ctx, `兔 = (${legs} - 2×${heads}) / 2 = ${rabbit}只, 鸡 = ${heads} - ${rabbit} = ${chicken}只 (当前显${cur})`, W / 2, H - 16, '#16a34a', 'center', 'bold 12px sans-serif')
}

function drawMotion(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const { totalDist, totalTime } = ent.value
  const distance = totalDist || ent.value.distance
  const motionTime = totalTime || ent.value.motionTime
  const motionSpeed = (motionTime && distance) ? distance / motionTime : ent.value.motionSpeed
  const marginX = 60
  const trackY = H / 2
  const availPx = W - marginX * 2
  const cur = (progress.value / 100) * distance
  const headX = marginX + (distance > 0 ? (cur / distance) * availPx : 0)
  ctx.strokeStyle = '#334155'
  ctx.lineWidth = 3
  ctx.beginPath()
  ctx.moveTo(marginX, trackY)
  ctx.lineTo(marginX + availPx, trackY)
  ctx.stroke()
  drawDashed(ctx, marginX, trackY - 40, marginX, trackY + 20, '#0284c7')
  drawText(ctx, '起点 0m', marginX, trackY - 46, '#0284c7', 'center')
  drawDashed(ctx, marginX + availPx, trackY - 40, marginX + availPx, trackY + 20, '#16a34a')
  drawText(ctx, `终点 ${distance}m`, marginX + availPx, trackY - 46, '#16a34a', 'center')
  ctx.fillStyle = '#ef4444'
  ctx.beginPath()
  ctx.arc(headX, trackY, 10, 0, Math.PI * 2)
  ctx.fill()
  if (cur > 0) {
    ctx.strokeStyle = '#ef4444'
    ctx.lineWidth = 2
    ctx.beginPath()
    ctx.moveTo(marginX, trackY)
    ctx.lineTo(headX, trackY)
    ctx.stroke()
  }
  drawText(ctx, `s = v × t = ${motionSpeed} × ${motionTime} = ${distance}m (当前 ${Math.round(cur)}m)`, W / 2, H - 16, '#334155', 'center', 'bold 12px sans-serif')
}

function drawWork(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const { worker1, worker2, totalDays } = ent.value
  const marginX = 60
  const barH = 28
  const barW = W - marginX * 2
  const y1 = H / 2 - 50
  const y2 = H / 2 - 10
  const ySum = H / 2 + 30
  const cur = (progress.value / 100) * totalDays
  const rate1 = 1 / worker1
  const rate2 = 1 / worker2
  const fill1 = Math.min(cur * rate1, 1) * barW
  const fill2 = Math.min(cur * rate2, 1) * barW
  const fillSum = Math.min(cur * (rate1 + rate2), 1) * barW
  const bar = (y: number, fill: number, color: string, label: string) => {
    ctx.strokeStyle = '#334155'
    ctx.lineWidth = 1
    ctx.strokeRect(marginX, y, barW, barH)
    ctx.fillStyle = color
    ctx.fillRect(marginX, y, fill, barH)
    drawText(ctx, label, marginX + barW / 2, y + barH / 2 + 4, '#fff', 'center', '11px sans-serif')
  }
  bar(y1, fill1, '#3b82f6', `甲: ${worker1}天 (效率${rate1.toFixed(3)})`)
  bar(y2, fill2, '#10b981', `乙: ${worker2}天 (效率${rate2.toFixed(3)})`)
  bar(ySum, fillSum, '#dc2626', `合作: 1/(${rate1.toFixed(2)}+${rate2.toFixed(2)}) = ${totalDays.toFixed(1)}天`)
  drawText(ctx, `当前第 ${cur.toFixed(1)} 天 (合作进度 ${(cur*(rate1+rate2)*100).toFixed(0)}%)`, W / 2, H - 14, '#334155', 'center', '12px sans-serif')
}

function drawAverage(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const { totalSum, count, average } = ent.value
  const marginX = 60
  const baseY = H - 60
  const availPx = W - marginX * 2
  const barW = availPx / count - 8
  const maxVal = average * 1.5
  const cur = (progress.value / 100) * average
  const values: number[] = []
  for (let i = 0; i < count; i++) {
    const v = (totalSum / count) * (0.7 + (i * 0.3 / Math.max(count - 1, 1)))
    values.push(v)
  }
  for (let i = 0; i < count; i++) {
    const x = marginX + i * (barW + 8)
    const h = (values[i] / maxVal) * (baseY - 60)
    ctx.fillStyle = '#3b82f6'
    ctx.fillRect(x, baseY - h, barW, h)
    drawText(ctx, `${i + 1}`, x + barW / 2, baseY + 14, '#475569', 'center', '10px sans-serif')
    drawText(ctx, `${Math.round(values[i])}`, x + barW / 2, baseY - h - 4, '#334155', 'center', '9px sans-serif')
  }
  const avgY = baseY - (average / maxVal) * (baseY - 60)
  drawDashed(ctx, marginX, avgY, marginX + availPx, avgY, '#dc2626')
  drawText(ctx, `平均线 = ${totalSum} ÷ ${count} = ${average}`, W / 2, avgY - 6, '#dc2626', 'center', 'bold 12px sans-serif')
  drawText(ctx, `当前 ${Math.round(cur)}`, W / 2, H - 14, '#334155', 'center', '11px sans-serif')
}

function drawOverlap(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const { board1, board2, overlap, totalLength } = ent.value
  const marginX = 60
  const baseY = H / 2 + 10
  const barH = 30
  const total = totalLength || (board1 + board2 - overlap)
  const pxPer = (W - marginX * 2) / Math.max(total, 1)
  const cur = (progress.value / 100) * total
  const overlapPx = overlap * pxPer
  const board1Px = board1 * pxPer
  const board2Px = board2 * pxPer
  const x1 = marginX
  const x2 = x1 + board1Px - overlapPx
  ctx.fillStyle = '#a16207'
  ctx.fillRect(x1, baseY - barH, board1Px, barH)
  ctx.strokeStyle = '#78350f'
  ctx.strokeRect(x1, baseY - barH, board1Px, barH)
  drawText(ctx, `板1 ${board1}cm`, x1 + board1Px / 2, baseY - barH - 6, '#78350f', 'center', '11px sans-serif')
  ctx.fillStyle = '#0369a1'
  ctx.fillRect(x2, baseY + 6, board2Px, barH)
  ctx.strokeStyle = '#075985'
  ctx.strokeRect(x2, baseY + 6, board2Px, barH)
  drawText(ctx, `板2 ${board2}cm`, x2 + board2Px / 2, baseY + 6 + barH + 14, '#075985', 'center', '11px sans-serif')
  ctx.fillStyle = 'rgba(220,38,38,0.3)'
  ctx.fillRect(x2, baseY - barH, overlapPx, barH * 2 + 6)
  drawDashed(ctx, x2, baseY - barH - 20, x2, baseY + barH * 2 + 26, '#dc2626')
  drawText(ctx, `重叠 ${overlap}cm`, x2 + overlapPx / 2, baseY - barH - 24, '#dc2626', 'center', '10px sans-serif')
  drawText(ctx, `总长 = ${board1} + ${board2} - ${overlap} = ${total}cm`, W / 2, H - 14, '#334155', 'center', 'bold 12px sans-serif')
  drawText(ctx, `已拼 ${Math.round(cur)}cm`, W / 2, 24, '#64748b', 'center', '11px sans-serif')
}

function drawRoundTrip(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const { distance, trips, totalDistance } = ent.value
  const marginX = 80
  const homeX = marginX
  const schoolX = W - marginX
  const pathY = H / 2
  const total = totalDistance || distance * 2 * trips
  const legs = trips * 2
  const curLeg = Math.floor((progress.value / 100) * legs)
  const curInLeg = ((progress.value / 100) * legs) - curLeg
  ctx.strokeStyle = '#94a3b8'
  ctx.lineWidth = 2
  ctx.beginPath()
  ctx.moveTo(homeX, pathY)
  ctx.lineTo(schoolX, pathY)
  ctx.stroke()
  drawText(ctx, '家', homeX - 10, pathY + 24, '#334155', 'center', '12px sans-serif')
  drawText(ctx, '学校', schoolX + 10, pathY + 24, '#334155', 'center', '12px sans-serif')
  const going = curLeg % 2 === 0
  const startX = going ? homeX : schoolX
  const endX = going ? schoolX : homeX
  const px = startX + (endX - startX) * curInLeg
  ctx.fillStyle = '#dc2626'
  ctx.beginPath()
  ctx.arc(px, pathY, 8, 0, Math.PI * 2)
  ctx.fill()
  drawText(ctx, going ? '→去' : '←回', px, pathY - 14, '#dc2626', 'center', '11px sans-serif')
  const doneTrips = Math.floor((curLeg + (going ? curInLeg : 1 - curInLeg)) / 2)
  drawText(ctx, `往返 ${doneTrips}/${trips} 次`, W / 2, pathY - 40, '#64748b', 'center', '11px sans-serif')
  drawText(ctx, `总程 = ${distance}×2×${trips} = ${total}m`, W / 2, H - 14, '#334155', 'center', 'bold 12px sans-serif')
}

function drawSumMultiple(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const { sumVal, multiple, small, big } = ent.value
  const marginX = 80
  const baseY = H - 70
  const availPx = W - marginX * 2
  const total = sumVal || (small + big)
  const pxPer = availPx / Math.max(total, 1)
  const cur = (progress.value / 100) * total
  const smallPx = small * pxPer
  const bigPx = big * pxPer
  ctx.fillStyle = '#3b82f6'
  ctx.fillRect(marginX, baseY - 24, smallPx, 24)
  drawText(ctx, `乙(小) ${small}`, marginX + smallPx / 2, baseY - 30, '#1e40af', 'center', '11px sans-serif')
  ctx.fillStyle = '#f59e0b'
  ctx.fillRect(marginX + smallPx, baseY - 24, bigPx, 24)
  drawText(ctx, `甲(大) ${big}`, marginX + smallPx + bigPx / 2, baseY - 30, '#92400e', 'center', '11px sans-serif')
  drawDashed(ctx, marginX, baseY - 44, marginX + availPx, baseY - 44, '#dc2626')
  drawText(ctx, `和 = ${sumVal}`, marginX + availPx / 2, baseY - 50, '#dc2626', 'center', 'bold 12px sans-serif')
  const fillPx = (cur / total) * availPx
  ctx.fillStyle = 'rgba(34,197,94,0.25)'
  ctx.fillRect(marginX, baseY - 24, fillPx, 24)
  drawText(ctx, `乙 = ${sumVal}÷(${multiple}+1) = ${small}`, W / 2, 28, '#334155', 'center', 'bold 11px sans-serif')
  drawText(ctx, `甲 = ${small}×${multiple} = ${big}`, W / 2, 46, '#334155', 'center', 'bold 11px sans-serif')
  drawText(ctx, `当前 ${Math.round(cur)}`, W / 2, H - 14, '#64748b', 'center', '11px sans-serif')
}

function drawSprinkler(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const { sprinklerSpeed: speed, sprinklerWidth: width, sprinklerTime: time, sprinklerLen: len, sprinklerArea: area } = ent.value
  const marginX = 60
  const baseY = H - 70
  const fullLen = len || speed * time
  const availPx = W - marginX * 2
  const pxPer = availPx / Math.max(fullLen, 1)
  const curLen = (progress.value / 100) * fullLen
  const curArea = curLen * width
  const fillPx = curLen * pxPer
  ctx.fillStyle = '#bbf7d0'
  ctx.fillRect(marginX, baseY - 40, fillPx, 40)
  ctx.strokeStyle = '#16a34a'
  ctx.lineWidth = 1.5
  ctx.strokeRect(marginX, baseY - 40, availPx, 40)
  ctx.fillStyle = '#15803d'
  ctx.fillRect(marginX, baseY - 40, fillPx, 6)
  ctx.fillStyle = '#1d4ed8'
  ctx.beginPath()
  ctx.arc(marginX + fillPx, baseY - 40, 8, 0, Math.PI * 2)
  ctx.fill()
  drawText(ctx, '洒水车', marginX + fillPx, baseY - 56, '#1d4ed8', 'center', '11px sans-serif')
  drawText(ctx, `宽 ${width}m`, marginX + availPx + 8, baseY - 20, '#334155', 'left', '10px sans-serif')
  drawText(ctx, `长 = ${speed}×${time} = ${fullLen}m`, W / 2, 28, '#334155', 'center', 'bold 11px sans-serif')
  drawText(ctx, `面积 = ${fullLen}×${width} = ${area}m²`, W / 2, 46, '#334155', 'center', 'bold 11px sans-serif')
  drawText(ctx, `已洒 ${Math.round(curArea)}m²`, W / 2, H - 14, '#16a34a', 'center', '11px sans-serif')
}

function drawTreePlanting(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const { roadLen, spacing, trees, segments, modeCode } = ent.value
  const marginX = 60
  const pathY = H / 2 + 10
  const availPx = W - marginX * 2
  const segs = segments || roadLen / spacing
  const totalTrees = trees || (modeCode === 1 ? segs + 1 : modeCode === 3 ? segs - 1 : segs)
  const segPx = availPx / Math.max(segs, 1)
  const treesDone = Math.floor((progress.value / 100) * totalTrees)
  ctx.strokeStyle = '#94a3b8'
  ctx.lineWidth = 3
  ctx.beginPath()
  ctx.moveTo(marginX, pathY)
  ctx.lineTo(marginX + availPx, pathY)
  ctx.stroke()
  const modeLabel = modeCode === 1 ? '两端栽' : modeCode === 2 ? '一端栽' : modeCode === 3 ? '两端不栽' : '封闭'
  for (let i = 0; i < totalTrees; i++) {
    const tx = marginX + i * segPx
    const planted = i < treesDone
    ctx.fillStyle = planted ? '#16a34a' : '#cbd5e1'
    ctx.beginPath()
    ctx.arc(tx, pathY - 14, 7, 0, Math.PI * 2)
    ctx.fill()
    ctx.strokeStyle = '#14532d'
    ctx.lineWidth = 2
    ctx.beginPath()
    ctx.moveTo(tx, pathY - 7)
    ctx.lineTo(tx, pathY)
    ctx.stroke()
  }
  for (let i = 0; i <= segs; i++) {
    const sx = marginX + i * segPx
    drawDashed(ctx, sx, pathY - 4, sx, pathY + 16, '#94a3b8')
  }
  drawText(ctx, `路长 ${roadLen}m 间距 ${spacing}m 段数 ${segs}`, W / 2, 28, '#334155', 'center', '11px sans-serif')
  drawText(ctx, `${modeLabel}: 棵 = ${trees} (段${modeCode === 1 ? '+1' : modeCode === 3 ? '-1' : ''})`, W / 2, 46, '#16a34a', 'center', 'bold 11px sans-serif')
  drawText(ctx, `已栽 ${treesDone}/${totalTrees}`, W / 2, H - 14, '#16a34a', 'center', '11px sans-serif')
}

function drawDisplacement(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const { tankLen, tankWidth, rise, volume } = ent.value
  const marginX = 70
  const baseY = H - 60
  const availPx = W - marginX * 2
  const tankPx = availPx
  const fullH = 120
  const waterMaxH = fullH * 0.6
  const riseH = (rise / (rise * 2.5)) * fullH
  const curRise = (progress.value / 100) * rise
  const curVol = tankLen * tankWidth * curRise
  ctx.strokeStyle = '#334155'
  ctx.lineWidth = 2
  ctx.strokeRect(marginX, baseY - fullH, tankPx, fullH)
  ctx.fillStyle = '#bae6fd'
  ctx.fillRect(marginX, baseY - waterMaxH, tankPx, waterMaxH)
  ctx.fillStyle = 'rgba(59,130,246,0.6)'
  ctx.fillRect(marginX, baseY - waterMaxH - curRise, tankPx, curRise)
  drawDashed(ctx, marginX, baseY - waterMaxH, marginX + tankPx, baseY - waterMaxH, '#0284c7')
  drawText(ctx, `原水位`, marginX - 6, baseY - waterMaxH, '#0284c7', 'right', '10px sans-serif')
  drawDashed(ctx, marginX, baseY - waterMaxH - rise, marginX + tankPx, baseY - waterMaxH - rise, '#dc2626')
  drawText(ctx, `上升 ${rise}cm`, marginX + tankPx + 6, baseY - waterMaxH - rise, '#dc2626', 'left', '10px sans-serif')
  ctx.fillStyle = '#78350f'
  ctx.fillRect(marginX + tankPx / 2 - 20, baseY - waterMaxH - rise - 20, 40, 20)
  drawText(ctx, '石', marginX + tankPx / 2, baseY - waterMaxH - rise - 6, '#fff', 'center', '10px sans-serif')
  drawText(ctx, `底 ${tankLen}×${tankWidth}`, W / 2, 28, '#334155', 'center', '11px sans-serif')
  drawText(ctx, `体积 = ${tankLen}×${tankWidth}×${rise} = ${volume}cm³`, W / 2, 46, '#334155', 'center', 'bold 11px sans-serif')
  drawText(ctx, `当前 ${Math.round(curVol)}cm³`, W / 2, H - 14, '#1d4ed8', 'center', '11px sans-serif')
}

function drawProfitLoss(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const { surplus, deficit, diff, people } = ent.value
  const marginX = 80
  const baseY = H - 70
  const availPx = W - marginX * 2
  const maxVal = Math.max(surplus, deficit) * 1.2
  const curPeople = (progress.value / 100) * people
  const sH = (surplus / maxVal) * (baseY - 60)
  const dH = (deficit / maxVal) * (baseY - 60)
  ctx.fillStyle = '#16a34a'
  ctx.fillRect(marginX, baseY - sH, 60, sH)
  drawText(ctx, `盈\n${surplus}`, marginX + 30, baseY - sH - 8, '#15803d', 'center', '11px sans-serif')
  ctx.fillStyle = '#dc2626'
  ctx.fillRect(marginX + availPx - 60, baseY - dH, 60, dH)
  drawText(ctx, `亏\n${deficit}`, marginX + availPx - 30, baseY - dH - 8, '#991b1b', 'center', '11px sans-serif')
  drawDashed(ctx, marginX + 60, baseY, marginX + availPx - 60, baseY, '#64748b')
  drawText(ctx, `分配差 ${diff}`, marginX + availPx / 2, baseY + 16, '#64748b', 'center', '10px sans-serif')
  const fillPx = (curPeople / people) * availPx
  ctx.strokeStyle = '#7c3aed'
  ctx.lineWidth = 2
  ctx.beginPath()
  ctx.moveTo(marginX, baseY + 36)
  ctx.lineTo(marginX + fillPx, baseY + 36)
  ctx.stroke()
  for (let i = 0; i <= people; i++) {
    const px = marginX + (i / people) * availPx
    drawDashed(ctx, px, baseY + 32, px, baseY + 40, '#7c3aed')
  }
  drawText(ctx, `人数 = (${surplus}+${deficit})÷${diff} = ${people}`, W / 2, 28, '#334155', 'center', 'bold 12px sans-serif')
  drawText(ctx, `当前 ${Math.round(curPeople)}人`, W / 2, H - 14, '#7c3aed', 'center', '11px sans-serif')
}

function drawInterest(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const { principal, rate, years, interest, interestTotal } = ent.value
  const marginX = 70
  const baseY = H - 60
  const availPx = W - marginX * 2
  const fullH = baseY - 60
  const maxVal = interestTotal || (principal + interest) || principal * 1.2
  const pxPerY = years > 1 ? availPx / (years - 1) : availPx / 2
  const yearProg = (progress.value / 100) * years
  const curYear = Math.floor(yearProg)
  const curInterest = principal * rate * yearProg
  const curTotal = principal + curInterest
  const principalH = (principal / maxVal) * fullH
  ctx.fillStyle = '#3b82f6'
  ctx.fillRect(marginX, baseY - principalH, 36, principalH)
  drawText(ctx, '本金', marginX + 18, baseY - principalH - 6, '#1e40af', 'center', '10px sans-serif')
  drawText(ctx, `${principal}元`, marginX + 18, baseY + 14, '#1e40af', 'center', '10px sans-serif')
  for (let y = 1; y <= years; y++) {
    const x = marginX + 50 + (y - 1) * pxPerY
    const acc = principal * rate * y
    const accH = (acc / maxVal) * fullH
    const done = y <= curYear
    ctx.fillStyle = done ? '#16a34a' : '#cbd5e1'
    ctx.fillRect(x, baseY - accH, 36, accH)
    drawText(ctx, `第${y}年`, x + 18, baseY + 14, done ? '#15803d' : '#64748b', 'center', '9px sans-serif')
    drawText(ctx, `+${Math.round(principal * rate * y)}`, x + 18, baseY - accH - 6, done ? '#15803d' : '#94a3b8', 'center', '9px sans-serif')
  }
  const totalH = (curTotal / maxVal) * fullH
  ctx.strokeStyle = '#dc2626'
  ctx.lineWidth = 2
  ctx.beginPath()
  ctx.moveTo(marginX, baseY - totalH)
  ctx.lineTo(W - marginX, baseY - totalH)
  ctx.stroke()
  drawText(ctx, `本息 ${Math.round(curTotal)}元`, W - marginX, baseY - totalH - 6, '#dc2626', 'right', '10px sans-serif')
  drawText(ctx, `利息 = ${principal} × ${rate} × ${years} = ${interest}元`, W / 2, 28, '#334155', 'center', 'bold 11px sans-serif')
  drawText(ctx, `本息 = ${principal} + ${interest} = ${interestTotal}元`, W / 2, 46, '#334155', 'center', 'bold 11px sans-serif')
  drawText(ctx, `第 ${Math.min(curYear + 1, years)} 年 · 利息 ${Math.round(curInterest)}元`, W / 2, H - 14, '#16a34a', 'center', '11px sans-serif')
}

function drawTiered(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const { baseDistance, basePrice, unitPrice, totalDist2, extraDistance, totalPrice } = ent.value
  const marginX = 70
  const pathY = H / 2 + 20
  const availPx = W - marginX * 2
  const pxPerKm = availPx / Math.max(totalDist2, 1)
  const basePx = baseDistance * pxPerKm
  const cur = (progress.value / 100) * totalDist2
  ctx.strokeStyle = '#94a3b8'
  ctx.lineWidth = 3
  ctx.beginPath()
  ctx.moveTo(marginX, pathY)
  ctx.lineTo(marginX + availPx, pathY)
  ctx.stroke()
  ctx.fillStyle = '#3b82f6'
  ctx.fillRect(marginX, pathY - 30, basePx, 6)
  ctx.fillStyle = '#f59e0b'
  ctx.fillRect(marginX + basePx, pathY - 30, (totalDist2 - baseDistance) * pxPerKm, 6)
  drawText(ctx, `起步${baseDistance}km ${basePrice}元`, marginX + basePx / 2, pathY - 40, '#1e40af', 'center', '10px sans-serif')
  drawText(ctx, `超出${extraDistance}km ×${unitPrice}`, marginX + basePx + (totalDist2 - baseDistance) * pxPerKm / 2, pathY - 40, '#92400e', 'center', '10px sans-serif')
  const carX = marginX + cur * pxPerKm
  ctx.fillStyle = '#dc2626'
  ctx.beginPath()
  ctx.arc(carX, pathY, 8, 0, Math.PI * 2)
  ctx.fill()
  drawText(ctx, `${cur.toFixed(1)}km`, carX, pathY + 24, '#dc2626', 'center', '10px sans-serif')
  const accPrice = basePrice + Math.max(cur - baseDistance, 0) * unitPrice
  drawText(ctx, `车费 = ${basePrice} + ${extraDistance}×${unitPrice} = ${totalPrice}元`, W / 2, 28, '#334155', 'center', 'bold 11px sans-serif')
  drawText(ctx, `当前 ${Math.round(accPrice)}元`, W / 2, H - 14, '#f59e0b', 'center', '11px sans-serif')
}

function drawWeekday(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const { startDay, addDays, targetDay } = ent.value
  const names = ['', '周一', '周二', '周三', '周四', '周五', '周六', '周日']
  const cx = W / 2
  const cy = H / 2 - 10
  const r = Math.min(W, H) / 3.5
  const curDay = ((startDay + Math.floor((progress.value / 100) * addDays) - 1) % 7) + 1
  for (let i = 1; i <= 7; i++) {
    const ang = -Math.PI / 2 + ((i - 1) / 7) * Math.PI * 2
    const x = cx + Math.cos(ang) * r
    const y = cy + Math.sin(ang) * r
    const isStart = i === startDay
    const isTarget = i === targetDay
    const isCur = i === curDay
    ctx.fillStyle = isStart ? '#3b82f6' : isTarget ? '#16a34a' : isCur ? '#f59e0b' : '#cbd5e1'
    ctx.beginPath()
    ctx.arc(x, y, 18, 0, Math.PI * 2)
    ctx.fill()
    drawText(ctx, names[i], x, y + 4, isStart || isTarget || isCur ? '#fff' : '#475569', 'center', '10px sans-serif')
  }
  ctx.strokeStyle = '#94a3b8'
  ctx.lineWidth = 1.5
  ctx.beginPath()
  ctx.arc(cx, cy, r, 0, Math.PI * 2)
  ctx.stroke()
  drawText(ctx, `今天${names[startDay]} +${addDays}天 = ${names[targetDay]}`, W / 2, 28, '#334155', 'center', 'bold 11px sans-serif')
  drawText(ctx, `${addDays} ÷ 7 = ${Math.floor(addDays / 7)}周余${addDays % 7}天`, W / 2, 46, '#64748b', 'center', '10px sans-serif')
  drawText(ctx, `当前 ${names[curDay]}`, W / 2, H - 14, '#f59e0b', 'center', '11px sans-serif')
}

function drawSemicircle(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const { radius, arc, diameter, perimeter } = ent.value
  const cx = W / 2
  const cy = H / 2 + 30
  const r = Math.min(radius * 15, 80)
  const cur = (progress.value / 100) * perimeter
  ctx.strokeStyle = '#334155'
  ctx.lineWidth = 2
  ctx.beginPath()
  ctx.moveTo(cx - r, cy)
  ctx.lineTo(cx + r, cy)
  ctx.stroke()
  drawText(ctx, `直径 ${diameter}cm`, cx, cy + 18, '#334155', 'center', '10px sans-serif')
  const arcRatio = Math.min(cur / arc, 1)
  ctx.strokeStyle = '#3b82f6'
  ctx.lineWidth = 4
  ctx.beginPath()
  ctx.arc(cx, cy, r, Math.PI, Math.PI + Math.PI * arcRatio)
  ctx.stroke()
  ctx.strokeStyle = '#94a3b8'
  ctx.lineWidth = 1
  ctx.setLineDash([4, 4])
  ctx.beginPath()
  ctx.arc(cx, cy, r, Math.PI, Math.PI * 2)
  ctx.stroke()
  ctx.setLineDash([])
  drawText(ctx, `弧 = π×r = ${arc.toFixed(2)}cm`, cx, cy - r - 14, '#1d4ed8', 'center', '10px sans-serif')
  drawText(ctx, `周长 = 弧+直径 = ${arc.toFixed(2)}+${diameter} = ${perimeter.toFixed(2)}cm`, W / 2, 28, '#334155', 'center', 'bold 11px sans-serif')
  drawText(ctx, `当前 ${cur.toFixed(2)}cm`, W / 2, H - 14, '#3b82f6', 'center', '11px sans-serif')
}

function drawCuboidCombine(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const { boxLen, boxWidth, boxHeight, minFace, maxFace, singleSa, maxSa, minSa } = ent.value
  const marginX = 60
  const baseY = H - 70
  const availPx = W - marginX * 2
  const maxVal = maxSa
  const cur = (progress.value / 100) * maxSa
  const bars = [
    { label: '拼接最小面', val: maxSa, color: '#16a34a', note: `减2×${minFace}` },
    { label: '拼接最大面', val: minSa, color: '#dc2626', note: `减2×${maxFace}` },
    { label: '单个表面积×2', val: singleSa * 2, color: '#64748b', note: `2×${singleSa}` },
  ]
  const barW = availPx / bars.length - 20
  for (let i = 0; i < bars.length; i++) {
    const b = bars[i]
    const x = marginX + i * (barW + 20)
    const h = (b.val / maxVal) * (baseY - 80)
    ctx.fillStyle = b.color
    ctx.fillRect(x, baseY - h, barW, h)
    drawText(ctx, b.label, x + barW / 2, baseY - h - 16, b.color, 'center', '10px sans-serif')
    drawText(ctx, b.note, x + barW / 2, baseY - h - 30, '#64748b', 'center', '9px sans-serif')
    drawText(ctx, `${Math.round(b.val)}`, x + barW / 2, baseY + 14, '#334155', 'center', '10px sans-serif')
  }
  const fillPx = (cur / maxVal) * (baseY - 80)
  ctx.fillStyle = 'rgba(34,197,94,0.2)'
  ctx.fillRect(marginX, baseY - fillPx, availPx, fillPx)
  drawText(ctx, `${boxLen}×${boxWidth}×${boxHeight} 拼最小面 → 最大表面积 ${maxSa}cm²`, W / 2, 28, '#334155', 'center', 'bold 11px sans-serif')
  drawText(ctx, `当前 ${Math.round(cur)}cm²`, W / 2, H - 14, '#16a34a', 'center', '11px sans-serif')
}

function drawCombination(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const { nItems1, nItems2, combinations } = ent.value
  const marginX = 60
  const topY = 70
  const botY = H - 70
  const availPx = W - marginX * 2
  const stepX1 = availPx / Math.max(nItems1, 1)
  const stepX2 = availPx / Math.max(nItems2, 1)
  const curLinks = Math.floor((progress.value / 100) * combinations)
  let linkCount = 0
  for (let i = 0; i < nItems1; i++) {
    const x1 = marginX + i * stepX1 + stepX1 / 2
    ctx.fillStyle = '#3b82f6'
    ctx.beginPath()
    ctx.arc(x1, topY, 16, 0, Math.PI * 2)
    ctx.fill()
    drawText(ctx, `衣${i + 1}`, x1, topY + 4, '#fff', 'center', '9px sans-serif')
  }
  for (let j = 0; j < nItems2; j++) {
    const x2 = marginX + j * stepX2 + stepX2 / 2
    ctx.fillStyle = '#f59e0b'
    ctx.beginPath()
    ctx.arc(x2, botY, 16, 0, Math.PI * 2)
    ctx.fill()
    drawText(ctx, `裤${j + 1}`, x2, botY + 4, '#fff', 'center', '9px sans-serif')
  }
  for (let i = 0; i < nItems1; i++) {
    for (let j = 0; j < nItems2; j++) {
      const x1 = marginX + i * stepX1 + stepX1 / 2
      const x2 = marginX + j * stepX2 + stepX2 / 2
      const drawn = linkCount < curLinks
      ctx.strokeStyle = drawn ? '#dc2626' : '#e2e8f0'
      ctx.lineWidth = drawn ? 1.5 : 1
      ctx.beginPath()
      ctx.moveTo(x1, topY + 16)
      ctx.lineTo(x2, botY - 16)
      ctx.stroke()
      linkCount++
    }
  }
  drawText(ctx, `${nItems1} × ${nItems2} = ${combinations} 种搭配`, W / 2, 30, '#334155', 'center', 'bold 12px sans-serif')
  drawText(ctx, `已连 ${curLinks}/${combinations}`, W / 2, H - 14, '#dc2626', 'center', '11px sans-serif')
}

function drawUnitaryCombined(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const { nPeople, nDays, totalWork, targetPeople, targetDays, unitRate, workResult } = ent.value
  const marginX = 70
  const baseY = H - 60
  const availPx = W - marginX * 2
  const maxVal = Math.max(totalWork, workResult) * 1.1
  const cur = (progress.value / 100) * workResult
  const origH = (totalWork / maxVal) * (baseY - 70)
  const resH = (workResult / maxVal) * (baseY - 70)
  ctx.fillStyle = '#3b82f6'
  ctx.fillRect(marginX, baseY - origH, 50, origH)
  drawText(ctx, `原: ${nPeople}人×${nDays}天`, marginX + 25, baseY - origH - 8, '#1e40af', 'center', '9px sans-serif')
  drawText(ctx, `${totalWork}个`, marginX + 25, baseY + 14, '#1e40af', 'center', '10px sans-serif')
  ctx.fillStyle = '#16a34a'
  ctx.fillRect(marginX + availPx - 50, baseY - resH, 50, resH)
  drawText(ctx, `新: ${targetPeople}人×${targetDays}天`, marginX + availPx - 25, baseY - resH - 8, '#15803d', 'center', '9px sans-serif')
  drawText(ctx, `${workResult}个`, marginX + availPx - 25, baseY + 14, '#15803d', 'center', '10px sans-serif')
  ctx.strokeStyle = '#dc2626'
  ctx.lineWidth = 2
  ctx.setLineDash([4, 4])
  ctx.beginPath()
  ctx.moveTo(marginX + 50, baseY - origH)
  ctx.lineTo(marginX + availPx - 50, baseY - resH)
  ctx.stroke()
  ctx.setLineDash([])
  drawText(ctx, `单人单日 = ${totalWork}÷${nPeople}÷${nDays} = ${unitRate}个`, W / 2, 28, '#334155', 'center', 'bold 11px sans-serif')
  drawText(ctx, `结果 = ${unitRate}×${targetPeople}×${targetDays} = ${workResult}个`, W / 2, 46, '#334155', 'center', 'bold 11px sans-serif')
  drawText(ctx, `当前 ${Math.round(cur)}个`, W / 2, H - 14, '#16a34a', 'center', '11px sans-serif')
}

function drawRedundant(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const { redTotal, redRemoved, redDistraction, redRemaining } = ent.value
  const baseY = H - 70
  const birdsShown = Math.ceil((progress.value / 100) * redTotal)
  const flown = Math.floor((progress.value / 100) * redRemoved)
  const birdR = 8
  const gap = 22
  const startX = (W - redTotal * gap) / 2
  for (let i = 0; i < redTotal; i++) {
    const x = startX + i * gap
    const flownAway = i < flown
    const remaining = i >= redRemoved
    if (flownAway) {
      ctx.globalAlpha = 0.3
      ctx.strokeStyle = '#94a3b8'
    } else {
      ctx.globalAlpha = 1
      ctx.strokeStyle = '#16a34a'
    }
    ctx.lineWidth = 2
    ctx.beginPath()
    ctx.arc(x, baseY, birdR, 0, Math.PI * 2)
    ctx.stroke()
    ctx.beginPath()
    ctx.moveTo(x - birdR, baseY + birdR)
    ctx.lineTo(x + birdR, baseY - birdR)
    ctx.stroke()
    ctx.globalAlpha = 1
  }
  drawText(ctx, `原有 ${redTotal} 只`, W / 2, 30, '#334155', 'center', 'bold 11px sans-serif')
  drawText(ctx, `飞走 ${redRemoved} 只 (虚化)`, W / 2, 48, '#94a3b8', 'center', '10px sans-serif')
  drawText(ctx, `${redTotal} - ${redRemoved} = ${redRemaining} 只`, W / 2, 66, '#16a34a', 'center', 'bold 11px sans-serif')
  if (redDistraction > 0) {
    const dx = W - 90
    ctx.globalAlpha = 0.4
    ctx.fillStyle = '#f59e0b'
    for (let i = 0; i < redDistraction; i++) {
      ctx.beginPath()
      ctx.arc(dx, 40 + i * 26, 6, 0, Math.PI * 2)
      ctx.fill()
    }
    ctx.globalAlpha = 1
    drawText(ctx, `干扰: ${redDistraction}朵花`, dx, 28, '#f59e0b', 'center', '9px sans-serif')
    drawText(ctx, `(不参与运算)`, dx, H - 40, '#f59e0b', 'center', '9px sans-serif')
    ctx.strokeStyle = '#dc2626'
    ctx.lineWidth = 1.5
    ctx.setLineDash([3, 3])
    ctx.beginPath()
    ctx.moveTo(dx - 30, 40)
    ctx.lineTo(dx + 30, 40 + redDistraction * 26)
    ctx.stroke()
    ctx.setLineDash([])
  }
  const remCount = redTotal - flown
  drawText(ctx, `树上剩 ${remCount} 只`, W / 2, H - 14, '#16a34a', 'center', '11px sans-serif')
}

function drawFoldCut(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const { folds, foldSegments } = ent.value
  const baseY = H / 2
  const shownSegs = Math.max(1, Math.ceil((progress.value / 100) * foldSegments))
  const segW = Math.min(60, (W - 120) / foldSegments)
  const startX = (W - foldSegments * segW) / 2
  ctx.strokeStyle = '#334155'
  ctx.lineWidth = 3
  for (let i = 0; i < foldSegments; i++) {
    const x = startX + i * segW
    const drawn = i < shownSegs
    ctx.globalAlpha = drawn ? 1 : 0.25
    ctx.beginPath()
    ctx.moveTo(x, baseY - 15)
    ctx.lineTo(x + segW - 8, baseY - 15)
    ctx.stroke()
    if (i < foldSegments - 1) {
      ctx.beginPath()
      ctx.moveTo(x + segW - 8, baseY - 15)
      ctx.lineTo(x + segW - 8, baseY + 15)
      ctx.stroke()
    }
    ctx.globalAlpha = 1
  }
  const cutX = startX + foldSegments * segW / 2
  ctx.strokeStyle = '#dc2626'
  ctx.lineWidth = 2
  ctx.setLineDash([5, 3])
  ctx.beginPath()
  ctx.moveTo(cutX, baseY - 35)
  ctx.lineTo(cutX, baseY + 35)
  ctx.stroke()
  ctx.setLineDash([])
  drawText(ctx, '✂ 剪开', cutX, baseY - 40, '#dc2626', 'center', 'bold 10px sans-serif')
  drawText(ctx, `对折 ${folds} 次`, W / 2, 30, '#334155', 'center', 'bold 11px sans-serif')
  drawText(ctx, `段数 = 2^${folds} + 1 = ${foldSegments} 段`, W / 2, 50, '#16a34a', 'center', 'bold 11px sans-serif')
  drawText(ctx, `当前 ${shownSegs} / ${foldSegments} 段`, W / 2, H - 14, '#16a34a', 'center', '11px sans-serif')
}

function genStarsBarsSolutions(remaining: number, k: number): number[][] {
  const out: number[][] = []
  const cur: number[] = []
  function rec(idx: number, left: number) {
    if (out.length >= 120) return
    if (idx === k - 1) { cur[idx] = left; out.push([...cur]); return }
    for (let v = 0; v <= left; v++) {
      cur[idx] = v
      rec(idx + 1, left - v)
    }
  }
  rec(0, remaining)
  return out
}

function drawStarsBars(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const { sbItems, sbBins, sbWays, sbMinPer } = ent.value
  const minPer = sbMinPer || 1
  const reserved = minPer * sbBins
  const remaining = Math.max(0, sbItems - reserved)
  const solutions = genStarsBarsSolutions(remaining, sbBins)
  const totalWays = solutions.length || sbWays
  const curIdx = Math.min(Math.floor((progress.value / 100) * totalWays), totalWays - 1)
  const curCase = solutions[curIdx] || new Array(sbBins).fill(Math.floor(remaining / sbBins))
  const binColors = ['#ec4899', '#8b5cf6', '#06b6d4', '#f59e0b', '#10b981', '#ef4444']
  const kidNames = ['A', 'B', 'C', 'D', 'E', 'F']

  ctx.clearRect(0, 0, W, H)
  ctx.fillStyle = '#701a75'
  ctx.font = 'bold 13px sans-serif'
  ctx.textAlign = 'left'
  ctx.fillText(`总巧克力 ${sbItems} 块 · 保底发放 ${reserved} 块 · 剩余自由分配 ${remaining} 块`, 24, 32)

  const basketY = 70
  const basketH = 200
  const gap = 16
  const basketW = (W - gap * (sbBins + 1)) / sbBins
  for (let i = 0; i < sbBins; i++) {
    const bx = gap + i * (basketW + gap)
    const total = minPer + (curCase[i] || 0)
    const color = binColors[i % binColors.length]
    ctx.fillStyle = '#fdf4ff'
    ctx.strokeStyle = color
    ctx.lineWidth = 3
    ctx.beginPath()
    if (ctx.roundRect) { ctx.roundRect(bx, basketY, basketW, basketH, 16) } else { ctx.rect(bx, basketY, basketW, basketH) }
    ctx.fill()
    ctx.stroke()
    ctx.fillStyle = color
    ctx.font = 'bold 15px sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText(`小朋友 ${kidNames[i]}`, bx + basketW / 2, basketY - 10)
    ctx.fillStyle = '#475569'
    ctx.font = 'bold 13px sans-serif'
    ctx.fillText(`共获得 ${total} 块`, bx + basketW / 2, basketY + basketH + 22)
    const cols = 3
    const cw = 40, ch = 26, cdx = (basketW - cols * cw) / (cols + 1)
    for (let p = 0; p < total; p++) {
      const row = Math.floor(p / cols), col = p % cols
      const cx = bx + cdx + col * (cw + cdx)
      const cy = basketY + 18 + row * (ch + 8)
      if (cy + ch > basketY + basketH - 8) break
      const isBaseline = p < minPer
      ctx.fillStyle = isBaseline ? '#f59e0b' : '#78350f'
      ctx.beginPath()
      if (ctx.roundRect) { ctx.roundRect(cx, cy, cw, ch, 6) } else { ctx.rect(cx, cy, cw, ch) }
      ctx.fill()
      ctx.fillStyle = isBaseline ? '#fcd34d' : '#9a3412'
      ctx.fillRect(cx + 6, cy + 6, cw - 12, ch - 12)
      ctx.fillStyle = isBaseline ? '#78350f' : '#ffffff'
      ctx.font = '9px sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText(isBaseline ? '保底' : '额外', cx + cw / 2, cy + ch / 2 + 3)
    }
  }

  const dotsY = H - 42
  const dotR = 6, dotGap = 24
  const dotsW = totalWays * dotGap
  const dotsStart = (W - dotsW) / 2 + dotGap / 2
  for (let i = 0; i < totalWays; i++) {
    const dx = dotsStart + i * dotGap
    ctx.beginPath()
    ctx.arc(dx, dotsY, i === curIdx ? 10 : dotR, 0, Math.PI * 2)
    ctx.fillStyle = i === curIdx ? '#c026d3' : '#cbd5e1'
    ctx.fill()
    if (i === curIdx) {
      ctx.fillStyle = '#ffffff'
      ctx.font = 'bold 10px sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText(`${i + 1}`, dx, dotsY + 3.5)
    }
  }
  ctx.fillStyle = '#334155'
  ctx.font = 'bold 13px sans-serif'
  ctx.textAlign = 'left'
  ctx.fillText(`当前第 ${curIdx + 1} / ${totalWays} 种: (${curCase.map((v: number) => minPer + v).join(', ')})`, 24, H - 12)
}

function drawTrainBridge(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const { bridge, train, totalDist, totalTime, speed } = ent.value
  const bridgeLen = Number(bridge.value) || 800
  const trainLen = Number(train.value) || 200
  const marginX = 90
  const trackY = H - 90
  const availPx = W - marginX * 2
  const pxPerM = availPx / totalDist
  const bridgePx = bridgeLen * pxPerM
  const trainPx = trainLen * pxPerM
  const bridgeStart = marginX
  const bridgeEnd = bridgeStart + bridgePx
  const cur = (progress.value / 100) * totalDist
  const headX = bridgeStart + cur * pxPerM
  const tailX = headX - trainPx

  // 河流
  const riverGrad = ctx.createLinearGradient(0, trackY + 14, 0, trackY + 74)
  riverGrad.addColorStop(0, '#7dd3fc')
  riverGrad.addColorStop(1, '#0284c7')
  ctx.fillStyle = riverGrad
  ctx.fillRect(bridgeStart, trackY + 14, bridgePx, 60)
  // 桥墩
  ctx.fillStyle = '#94a3b8'
  const pierW = 14, pierN = 3
  for (let i = 0; i <= pierN; i++) {
    const px = bridgeStart + (bridgePx / pierN) * i - pierW / 2
    ctx.fillRect(px, trackY + 12, pierW, 56)
  }
  // 桥面
  ctx.fillStyle = '#475569'
  ctx.fillRect(bridgeStart, trackY, bridgePx, 10)
  // 护栏拱
  ctx.strokeStyle = '#94a3b8'
  ctx.lineWidth = 3
  ctx.beginPath()
  ctx.moveTo(bridgeStart, trackY)
  ctx.quadraticCurveTo(bridgeStart + bridgePx / 2, trackY - 56, bridgeEnd, trackY)
  ctx.stroke()
  // 铁轨
  ctx.strokeStyle = '#334155'
  ctx.lineWidth = 4
  ctx.beginPath()
  ctx.moveTo(0, trackY - 2)
  ctx.lineTo(W, trackY - 2)
  ctx.stroke()

  // 参考线
  drawDashed(ctx, bridgeStart, 60, bridgeStart, trackY + 82, '#0284c7')
  drawText(ctx, `桥头 (0m)`, bridgeStart, 50, '#0284c7', 'center')
  drawDashed(ctx, bridgeEnd, 60, bridgeEnd, trackY + 82, '#0284c7')
  drawText(ctx, `桥尾 (${bridgeLen}m)`, bridgeEnd, 50, '#0284c7', 'center')
  const exitPx = bridgeStart + totalDist * pxPerM
  drawDashed(ctx, exitPx, 60, exitPx, trackY + 82, '#16a34a')
  drawText(ctx, `完全离开 (${totalDist}m)`, exitPx, 50, '#16a34a', 'center')

  // 行驶轨迹
  if (cur > 0) {
    ctx.strokeStyle = '#ef4444'
    ctx.lineWidth = 5
    ctx.beginPath()
    ctx.moveTo(bridgeStart, trackY - 35)
    ctx.lineTo(headX, trackY - 35)
    ctx.stroke()
    ctx.fillStyle = '#ef4444'
    ctx.beginPath()
    ctx.arc(headX, trackY - 35, 6, 0, Math.PI * 2)
    ctx.fill()
    const midX = (bridgeStart + headX) / 2
    drawText(ctx, `车头已走: ${Math.round(cur)}m`, midX, trackY - 45, '#dc2626', 'center', 'bold 12px sans-serif')
  }

  // 火车
  ctx.fillStyle = '#2563eb'
  ctx.beginPath()
  ctx.roundRect(tailX, trackY - 30, trainPx, 24, [4, 4, 0, 0])
  ctx.fill()
  // 车窗
  ctx.fillStyle = '#93c5fd'
  let wx = tailX + 6
  while (wx + 8 < headX - 8) {
    ctx.fillRect(wx, trackY - 24, 8, 8)
    wx += 20
  }
  // 车头灯
  ctx.fillStyle = '#1e40af'
  ctx.fillRect(headX - 6, trackY - 34, 5, 6)
  // 车轮
  ctx.fillStyle = '#1e293b'
  let wlx = tailX + 8
  while (wlx < headX) {
    ctx.beginPath()
    ctx.arc(wlx, trackY - 2, 4, 0, Math.PI * 2)
    ctx.fill()
    wlx += 16
  }
  drawText(ctx, `火车 (${trainLen}m)`, tailX + trainPx / 2, trackY - 14, '#ffffff', 'center', 'bold 10px sans-serif')

  // 里程碑标记
  for (const m of milestones.value) {
    const mx = bridgeStart + (Number(m.progress_percentage) / 100) * totalDist * pxPerM
    if (mx >= bridgeStart && mx <= W - 10) {
      drawDashed(ctx, mx, trackY + 90, mx, trackY + 110, '#a855f7')
      drawText(ctx, m.event_name, mx, trackY + 122, '#a855f7', 'center', '10px sans-serif')
    }
  }
}

// ── 通用路径渲染器 (S3): 按可视化原语绘制, 不依赖具体题型模板 ──
const genericAnswer = computed(() => {
  const tl = props.scene?.timeline || {}
  return { answer: Number(tl.answer || 0), unit: String(tl.answer_unit || ''), totalDist: Number(tl.total_distance || 1) }
})

function drawGenericScene(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const kind = genericVisual.value.kind
  // 分步 HUD (Gemini 方案融合): 当前步骤标题/公式/结果, 步骤进度条
  const step = currentStep.value
  if (step) {
    drawText(ctx, `步骤 ${step.step}: ${step.title}`, 20, 26, '#0f172a', 'left', 'bold 14px sans-serif')
    drawText(ctx, `${step.formula} → ${fmtNum(Number(step.value))}${step.result_unit || ''}`, 20, 46, '#0284c7', 'left', 'bold 12px sans-serif')
    const n = genericPipeline.value.length || 1
    const segW = (W - 40) / n
    for (let i = 0; i < n; i++) {
      const done = i < step.step
      ctx.fillStyle = done ? '#0ea5e9' : '#e2e8f0'
      ctx.fillRect(20 + i * segW, 56, segW - 4, 4)
    }
  }
  if (kind === 'bar_model') drawGenericBars(ctx, W, H)
  else if (kind === 'grid') drawGenericGrid(ctx, W, H)
  else if (kind === 'flow') drawGenericFlow(ctx, W, H)
  else if (kind === 'timeline') drawGenericTimeline(ctx, W, H)
  else drawGenericNumberLine(ctx, W, H)
}

function drawGenericNumberLine(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const { totalDist } = genericAnswer.value
  const marginX = 70
  const barY = H / 2 - 10
  const barW = W - marginX * 2
  const segs = genericVisual.value.segments.length ? genericVisual.value.segments : [{ label: '全程' }]
  const totalVal = segs.reduce((s: number, x: any) => s + (Number(x.value) || 0), 0) || totalDist
  ctx.strokeStyle = '#334155'
  ctx.lineWidth = 4
  ctx.beginPath(); ctx.moveTo(marginX, barY); ctx.lineTo(marginX + barW, barY); ctx.stroke()
  // 分段标注
  let acc = 0
  const px = (val: number) => marginX + (val / totalVal) * barW
  segs.forEach((s: any, i: number) => {
    const v = Number(s.value) || 0
    const x1 = px(acc), x2 = px(acc + (v || totalVal / segs.length))
    acc += v || totalVal / segs.length
    if (i > 0) { drawDashed(ctx, x1, barY - 24, x1, barY + 24, '#94a3b8') }
    drawText(ctx, String(s.label), (x1 + x2) / 2, barY - 32, '#475569', 'center', '11px sans-serif')
  })
  // 起终点标签
  drawText(ctx, genericVisual.value.startLabel || '起点', marginX, barY + 26, '#16a34a', 'center', 'bold 11px sans-serif')
  drawText(ctx, genericVisual.value.endLabel || '终点', marginX + barW, barY + 26, '#dc2626', 'center', 'bold 11px sans-serif')
  // 进度动画: 已完成比例填充
  const frac = progress.value / 100
  const donePx = barW * frac
  ctx.fillStyle = 'rgba(59,130,246,0.15)'
  ctx.fillRect(marginX, barY - 8, donePx, 16)
  const headX = marginX + donePx
  ctx.fillStyle = '#2563eb'
  ctx.beginPath(); ctx.arc(headX, barY, 8, 0, Math.PI * 2); ctx.fill()
  // 答案揭示 (进度 >90%)
  if (frac > 0.9) {
    const { answer, unit } = genericAnswer.value
    drawText(ctx, `答案: ${fmtNum(answer)} ${unit}`, W / 2, barY + 60, '#c026d3', 'center', 'bold 15px sans-serif')
  }
  for (const m of milestones.value) {
    const mx = marginX + (Number(m.progress_percentage) / 100) * barW
    drawDashed(ctx, mx, barY - 50, mx, barY - 36, '#a855f7')
    drawText(ctx, m.event_name, mx, barY - 54, '#a855f7', 'center', '10px sans-serif')
  }
}

function drawGenericBars(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const list = (props.scene?.entities || []).filter((e: any) => e.type === 'reference_line' && e.value > 0)
  const segs = genericVisual.value.segments.filter((s: any) => Number(s.value) > 0)
  const bars = segs.length ? segs.map((s: any) => ({ label: s.label, value: Number(s.value) })) : list.map((e: any) => ({ label: e.label || e.id, value: Number(e.value) }))
  if (!bars.length) { drawGenericNumberLine(ctx, W, H); return }
  const maxV = Math.max(...bars.map((b: any) => b.value))
  const { answer, unit } = genericAnswer.value
  const frac = progress.value / 100
  const barW = Math.min(90, (W - 160) / bars.length - 24)
  const baseY = H - 70
  bars.forEach((b: any, i: number) => {
    const x = 100 + i * ((W - 200) / bars.length) + 10
    const fullH = (b.value / maxV) * (H - 160)
    const curH = fullH * Math.min(1, frac * bars.length) // 逐条依次生长
    ctx.fillStyle = '#93c5fd'
    ctx.fillRect(x, baseY - fullH, barW, fullH)
    ctx.fillStyle = '#2563eb'
    ctx.fillRect(x, baseY - curH, barW, curH)
    drawText(ctx, String(b.label), x + barW / 2, baseY + 16, '#475569', 'center', '11px sans-serif')
    drawText(ctx, fmtNum(b.value), x + barW / 2, baseY - fullH - 6, '#334155', 'center', 'bold 11px sans-serif')
  })
  ctx.strokeStyle = '#94a3b8'; ctx.lineWidth = 1.5
  ctx.beginPath(); ctx.moveTo(80, baseY); ctx.lineTo(W - 80, baseY); ctx.stroke()
  if (frac > 0.9) drawText(ctx, `答案: ${fmtNum(answer)} ${unit}`, W / 2, 40, '#c026d3', 'center', 'bold 15px sans-serif')
}

function drawGenericGrid(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const { answer, unit } = genericAnswer.value
  const frac = progress.value / 100
  const rows = Math.min(5, Math.max(2, Math.ceil(Math.sqrt(answer))))
  const cols = Math.min(10, Math.ceil(answer / rows))
  const cell = Math.min(38, (W - 200) / Math.max(cols, 1), (H - 180) / Math.max(rows, 1))
  const startX = (W - cols * cell) / 2
  const startY = (H - rows * cell) / 2 - 10
  const shown = Math.floor(answer * frac)
  for (let i = 0; i < rows * cols; i++) {
    const r = Math.floor(i / cols), c = i % cols
    const x = startX + c * cell, y = startY + r * cell
    const filled = i < shown
    ctx.fillStyle = filled ? '#86efac' : '#e2e8f0'
    ctx.strokeStyle = '#94a3b8'; ctx.lineWidth = 1
    if ((ctx as any).roundRect) { ctx.beginPath(); (ctx as any).roundRect(x + 3, y + 3, cell - 6, cell - 6, 5); ctx.fill(); ctx.stroke() }
    else ctx.fillRect(x + 3, y + 3, cell - 6, cell - 6)
  }
  drawText(ctx, `${shown} / ${fmtNum(answer)} ${unit}`, W / 2, startY + rows * cell + 26, '#334155', 'center', 'bold 13px sans-serif')
}

function drawGenericFlow(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const steps = (props.scene?.pedagogy?.steps || []) as string[]
  const { answer, unit } = genericAnswer.value
  const items = steps.length ? steps : ['提取已知量', '列方程', '求解']
  const frac = progress.value / 100
  const doneCount = Math.ceil(frac * items.length)
  const boxW = Math.min(380, W - 120), boxH = 40
  const gap = (H - 80 - items.length * boxH) / Math.max(items.length + 1, 1)
  items.forEach((s: string, i: number) => {
    const y = 50 + i * (boxH + gap)
    const done = i < doneCount
    ctx.fillStyle = done ? '#dcfce7' : '#f1f5f9'
    ctx.strokeStyle = done ? '#16a34a' : '#cbd5e1'
    ctx.lineWidth = 1.5
    if ((ctx as any).roundRect) { ctx.beginPath(); (ctx as any).roundRect((W - boxW) / 2, y, boxW, boxH, 8); ctx.fill(); ctx.stroke() }
    else { ctx.fillRect((W - boxW) / 2, y, boxW, boxH); ctx.strokeRect((W - boxW) / 2, y, boxW, boxH) }
    ctx.fillStyle = done ? '#166534' : '#64748b'
    ctx.font = 'bold 12px sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText(`${i + 1}. ${s}`, W / 2, y + boxH / 2 + 4)
    if (i < items.length - 1) {
      const ay = y + boxH
      ctx.fillStyle = done ? '#16a34a' : '#cbd5e1'
      ctx.beginPath(); ctx.moveTo(W / 2 - 5, ay + gap * 0.3); ctx.lineTo(W / 2 + 5, ay + gap * 0.3); ctx.lineTo(W / 2, ay + gap * 0.7); ctx.fill()
    }
  })
  if (frac > 0.95) drawText(ctx, `答案: ${fmtNum(answer)} ${unit}`, W / 2, H - 24, '#c026d3', 'center', 'bold 15px sans-serif')
}

function drawGenericTimeline(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const lineY = H / 2
  const marginX = 80
  const lineW = W - marginX * 2
  const { answer, unit } = genericAnswer.value
  const frac = progress.value / 100
  ctx.strokeStyle = '#334155'; ctx.lineWidth = 3
  ctx.beginPath(); ctx.moveTo(marginX, lineY); ctx.lineTo(marginX + lineW, lineY); ctx.stroke()
  // 刻度 0..answer
  const ticks = 6
  for (let i = 0; i <= ticks; i++) {
    const tx = marginX + (lineW / ticks) * i
    const val = (Number(answer) / ticks) * i
    drawDashed(ctx, tx, lineY - 6, tx, lineY + 6, '#94a3b8')
    drawText(ctx, fmtNum(Math.round(val * 10) / 10), tx, lineY + 22, '#64748b', 'center', '10px sans-serif')
  }
  // 进度指针
  const px = marginX + lineW * frac
  ctx.fillStyle = '#f59e0b'
  ctx.beginPath(); ctx.moveTo(px, lineY - 14); ctx.lineTo(px + 8, lineY - 26); ctx.lineTo(px - 8, lineY - 26); ctx.fill()
  drawText(ctx, genericVisual.value.startLabel || '现在', marginX, lineY - 34, '#16a34a', 'center', 'bold 11px sans-serif')
  drawText(ctx, genericVisual.value.endLabel || `+${fmtNum(answer)}${unit}`, marginX + lineW, lineY - 34, '#dc2626', 'center', 'bold 11px sans-serif')
  if (frac > 0.9) drawText(ctx, `答案: ${fmtNum(answer)} ${unit}`, W / 2, lineY + 50, '#c026d3', 'center', 'bold 15px sans-serif')
}

function fmtNum(n: number): string {
  if (!Number.isFinite(n)) return '—'
  return Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/\.?0+$/, '')
}

function drawGeneric(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const { totalDist, cur } = status.value
  const marginX = 60
  const barY = H / 2
  const barW = W - marginX * 2
  ctx.strokeStyle = '#334155'
  ctx.lineWidth = 4
  ctx.beginPath()
  ctx.moveTo(marginX, barY)
  ctx.lineTo(marginX + barW, barY)
  ctx.stroke()
  const headX = marginX + (cur / totalDist) * barW
  ctx.fillStyle = '#ef4444'
  ctx.beginPath()
  ctx.arc(headX, barY, 8, 0, Math.PI * 2)
  ctx.fill()
  drawText(ctx, `进度 ${progress.value.toFixed(0)}%  已走 ${Math.round(cur)}m / ${totalDist}m`, W / 2, barY - 20, '#334155', 'center', '13px sans-serif')
  for (const m of milestones.value) {
    const mx = marginX + (Number(m.progress_percentage) / 100) * barW
    drawDashed(ctx, mx, barY - 30, mx, barY + 30, '#a855f7')
    drawText(ctx, m.event_name, mx, barY + 45, '#a855f7', 'center', '10px sans-serif')
  }
}

function loop(ts: number) {
  if (!playing.value) return
  if (!lastTs) lastTs = ts
  const dt = (ts - lastTs) / 1000
  lastTs = ts
  const { totalTime } = ent.value
  if (totalTime > 0) {
    const pctPerSec = (100 / totalTime) * speedFactor.value
    progress.value = Math.min(100, progress.value + pctPerSec * dt)
    if (progress.value >= 100) {
      playing.value = false
    }
  }
  draw()
  if (playing.value) rafId = requestAnimationFrame(loop)
}

function togglePlay() {
  if (progress.value >= 100) progress.value = 0
  playing.value = !playing.value
  if (playing.value) {
    lastTs = 0
    rafId = requestAnimationFrame(loop)
  } else if (rafId) {
    cancelAnimationFrame(rafId)
  }
}

function reset() {
  playing.value = false
  if (rafId) cancelAnimationFrame(rafId)
  progress.value = 0
  draw()
}

watch(() => progress.value, () => draw())
watch(() => speedFactor.value, () => draw())
watch(() => props.scene, () => { progress.value = 0; draw() }, { deep: true })

onMounted(() => {
  const cv = canvasRef.value
  if (cv) {
    cv.width = cv.clientWidth * 2
    cv.height = 360 * 2
    cv.getContext('2d')!.scale(2, 2)
    cv.width = cv.clientWidth
    cv.height = 360
  }
  draw()
})
onBeforeUnmount(() => {
  if (rafId) cancelAnimationFrame(rafId)
})
</script>
<template>
  <div class="scene-canvas-wrap">
    <div class="teaching-card" v-if="teachingHint">
      <div class="teaching-title">💡 教学破局点 (为何可视化?)</div>
      <p>{{ teachingHint }}</p>
    </div>
    <div class="scene-formula">
      <n-space>
        <n-tag :type="scene.verified ? 'success' : 'warning'" size="small">
          {{ scene.verified ? 'SymPy 校验通过' : '校验失败/降级' }}
        </n-tag>
        <n-tag size="small">模板: {{ scene.template_type }}</n-tag>
      </n-space>
      <div class="formula-panel" v-if="isGeneric" style="grid-template-columns: 1fr;">
        <div class="fcard"><div class="flabel">通用求解 ({{ genericVisual.kind }})</div>
          <div class="fval green" v-for="(s, i) in (scene.pedagogy?.steps || [])" :key="i" style="font-size: 13px; margin: 2px 0">{{ i + 1 }}. {{ s }}</div>
          <div class="fval amber" style="margin-top: 6px">答案: {{ fmtNum(genericAnswer.answer) }} {{ genericAnswer.unit }}</div>
        </div>
      </div>
      <div class="formula-panel formula-train" v-if="isTrainBridge">
        <div class="fcard"><div class="flabel">完全过桥总路程 S</div><div class="fval amber">S = 桥长({{ ent.bridge?.value }}) + 车长({{ ent.train?.value }}) = {{ ent.totalDist }}m</div></div>
        <div class="fcard"><div class="flabel">需要总时间 t</div><div class="fval green">t = S ÷ v = {{ ent.totalDist }} ÷ {{ ent.speed }} = {{ ent.totalTime }}s</div></div>
      </div>
      <div class="formula-line" v-else-if="isCutting">
        <span>锯成 {{ ent.nSeg }} 段 → 需锯 {{ ent.nSeg }} - 1 = {{ ent.nCuts }} 次</span>
        <span style="margin-left: 24px">每次 {{ ent.tPer }} 分钟</span>
        <span style="margin-left: 24px">总时间 = {{ ent.nCuts }} × {{ ent.tPer }} = {{ ent.totalTime }} 分钟</span>
      </div>
      <div class="formula-line" v-else-if="isQueue">
        <span>从前第{{ ent.rankFront }} + 从后第{{ ent.rankBehind }} - 1 = {{ ent.totalPeople }} 人</span>
      </div>
      <div class="formula-line" v-else-if="isFence">
        <span>宽 = (周长{{ ent.perimeter }} - 长{{ ent.fenceLen }}) / 2 = {{ ent.width }}m</span>
        <span style="margin-left: 24px">面积 = {{ ent.fenceLen }} × {{ ent.width }} = {{ ent.area }}m²</span>
      </div>
      <div class="formula-line" v-else-if="isUnitary">
        <span>单价 = {{ ent.totalValue }} ÷ {{ ent.nItems }} = {{ ent.unitValue }}元/件</span>
        <span style="margin-left: 24px">目标 = {{ ent.unitValue }} × {{ ent.nTarget }} = {{ ent.targetValue }}元</span>
      </div>
      <div class="formula-line" v-else-if="isChickenRabbit">
        <span>兔 = ({{ ent.legs }} - 2×{{ ent.heads }}) / 2 = {{ ent.rabbit }}只</span>
        <span style="margin-left: 24px">鸡 = {{ ent.heads }} - {{ ent.rabbit }} = {{ ent.chicken }}只</span>
      </div>
      <div class="formula-line" v-else-if="isMotion">
        <span>s = v × t = {{ (ent.totalTime && ent.totalDist) ? (ent.totalDist/ent.totalTime).toFixed(1) : ent.motionSpeed }} × {{ ent.totalTime || ent.motionTime }} = {{ ent.totalDist || ent.distance }}m</span>
      </div>
      <div class="formula-line" v-else-if="isWork">
        <span>效率: 甲1/{{ ent.worker1 }} + 乙1/{{ ent.worker2 }}</span>
        <span style="margin-left: 24px">合作天数 = 1 / (1/{{ ent.worker1 }} + 1/{{ ent.worker2 }}) = {{ ent.totalDays.toFixed(1) }}天</span>
      </div>
      <div class="formula-line" v-else-if="isAverage">
        <span>平均 = {{ ent.totalSum }} ÷ {{ ent.count }} = {{ ent.average }}</span>
      </div>
      <div class="formula-line" v-else-if="isOverlap">
        <span>总长 = {{ ent.board1 }} + {{ ent.board2 }} - {{ ent.overlap }} = {{ ent.totalLength }}cm</span>
      </div>
      <div class="formula-line" v-else-if="isRoundTrip">
        <span>总程 = {{ ent.distance }} × 2 × {{ ent.trips }} = {{ ent.totalDistance }}m</span>
      </div>
      <div class="formula-line" v-else-if="isSumMultiple">
        <span>乙 = {{ ent.sumVal }} ÷ ({{ ent.multiple }}+1) = {{ ent.small }} · 甲 = {{ ent.small }} × {{ ent.multiple }} = {{ ent.big }}</span>
      </div>
      <div class="formula-line" v-else-if="isSprinkler">
        <span>长 = {{ ent.sprinklerSpeed }} × {{ ent.sprinklerTime }} = {{ ent.sprinklerLen }}m · 面积 = {{ ent.sprinklerLen }} × {{ ent.sprinklerWidth }} = {{ ent.sprinklerArea }}m²</span>
      </div>
      <div class="formula-line" v-else-if="isTreePlanting">
        <span>段 = {{ ent.roadLen }} ÷ {{ ent.spacing }} = {{ ent.segments }} · 棵 = {{ ent.trees }}</span>
      </div>
      <div class="formula-line" v-else-if="isDisplacement">
        <span>体积 = {{ ent.tankLen }} × {{ ent.tankWidth }} × {{ ent.rise }} = {{ ent.volume }}cm³</span>
      </div>
      <div class="formula-line" v-else-if="isProfitLoss">
        <span>人数 = ({{ ent.surplus }} + {{ ent.deficit }}) ÷ {{ ent.diff }} = {{ ent.people }}</span>
      </div>
      <div class="formula-line" v-else-if="isInterest">
        <span>利息 = {{ ent.principal }} × {{ ent.rate }} × {{ ent.years }} = {{ ent.interest }}元 · 本息 = {{ ent.principal }} + {{ ent.interest }} = {{ ent.interestTotal }}元</span>
      </div>
      <div class="formula-line" v-else-if="isTiered">
        <span>车费 = {{ ent.basePrice }} + {{ ent.extraDistance }} × {{ ent.unitPrice }} = {{ ent.totalPrice }}元</span>
      </div>
      <div class="formula-line" v-else-if="isWeekday">
        <span>{{ ent.addDays }} ÷ 7 = 余 {{ ent.addDays % 7 }} · 目标星期 = {{ ent.targetDay }}</span>
      </div>
      <div class="formula-line" v-else-if="isSemicircle">
        <span>弧 = π × {{ ent.radius }} = {{ ent.arc.toFixed(2) }} · 直径 = {{ ent.diameter }} · 周长 = {{ ent.perimeter.toFixed(2) }}cm</span>
      </div>
      <div class="formula-line" v-else-if="isCuboidCombine">
        <span>最大表面积 = 2×{{ ent.singleSa }} - 2×{{ ent.minFace }} = {{ ent.maxSa }}cm² · 最小 = 2×{{ ent.singleSa }} - 2×{{ ent.maxFace }} = {{ ent.minSa }}cm²</span>
      </div>
      <div class="formula-line" v-else-if="isCombination">
        <span>搭配 = {{ ent.nItems1 }} × {{ ent.nItems2 }} = {{ ent.combinations }} 种</span>
      </div>
      <div class="formula-line" v-else-if="isUnitaryCombined">
        <span>单人单日 = {{ ent.totalWork }} ÷ {{ ent.nPeople }} ÷ {{ ent.nDays }} = {{ ent.unitRate }} · 结果 = {{ ent.unitRate }} × {{ ent.targetPeople }} × {{ ent.targetDays }} = {{ ent.workResult }}</span>
      </div>
      <div class="formula-line" v-else-if="isRedundant">
        <span>剩余 = {{ ent.redTotal }} - {{ ent.redRemoved }} = {{ ent.redRemaining }} 只 (干扰 {{ ent.redDistraction }} 不参与)</span>
      </div>
      <div class="formula-line" v-else-if="isFoldCut">
        <span>段数 = 2^{{ ent.folds }} + 1 = {{ ent.foldSegments }} 段 (非 2^n 简单乘法)</span>
      </div>
      <div class="formula-panel formula-stars" v-else-if="isStarsBars">
        <div class="fcard"><div class="flabel">预分配后剩余 R</div><div class="fval amber">R = {{ ent.sbItems }} - {{ ent.sbMinPer }} × {{ ent.sbBins }} = {{ ent.sbItems - ent.sbMinPer * ent.sbBins }} 块</div></div>
        <div class="fcard"><div class="flabel">隔板法总组合 N</div><div class="fval green" v-if="ent.sbMinPer <= 1">N = C({{ ent.sbItems }} - 1, {{ ent.sbBins }} - 1) = C({{ ent.sbItems - 1 }}, {{ ent.sbBins - 1 }}) = {{ ent.sbWays }} 种</div><div class="fval green" v-else>N = C({{ ent.sbItems }} - {{ ent.sbMinPer }}×{{ ent.sbBins }} + {{ ent.sbBins }} - 1, {{ ent.sbBins }} - 1) = C({{ ent.sbItems - ent.sbMinPer * ent.sbBins + ent.sbBins - 1 }}, {{ ent.sbBins - 1 }}) = {{ ent.sbWays }} 种</div></div>
      </div>
    </div>

    <canvas ref="canvasRef" class="scene-canvas" />

    <div class="scene-controls">
      <n-button type="primary" size="small" @click="togglePlay">
        {{ playing ? '⏸ 暂停' : '▶ 播放' }}
      </n-button>
      <n-button size="small" @click="reset">↺ 重置</n-button>
      <n-select v-model:value="speedFactor" :options="speedOpts" size="small" style="width: 90px" />
      <span class="status-text" v-if="isCutting">
        已锯 {{ status.cur }} / {{ status.totalDist }} 次 · 耗时 {{ status.t.toFixed(1) }} / {{ status.totalTime }} 分钟
      </span>
      <span class="status-text" v-else-if="isSpecial">
        {{ Math.round(status.cur) }} / {{ Math.round(status.totalDist) }}
      </span>
      <span class="status-text" v-else>
        时间 {{ status.t.toFixed(1) }}s / {{ status.totalTime }}s · 行驶 {{ Math.round(status.cur) }}m / {{ status.totalDist }}m
      </span>
    </div>

    <n-slider v-model:value="progress" :min="0" :max="100" :step="0.5" style="margin-top: 8px" />

    <div class="milestone-row" v-if="milestones.length">
      <span class="milestone-label">关键里程碑:</span>
      <button v-for="(m, i) in milestones" :key="i" class="milestone-btn" @click="jumpMilestone(m.progress_percentage)">
        {{ i + 1 }}. {{ m.event_name }}
      </button>
    </div>

    <n-collapse style="margin-top: 12px">
      <n-collapse-item title="原始 DSL (调试)" name="dsl">
        <n-code :code="JSON.stringify(scene, null, 2)" language="json" word-wrap />
      </n-collapse-item>
    </n-collapse>
  </div>
</template>
<style scoped>
.scene-canvas-wrap { background: #fff; border-radius: 8px; padding: 12px; border: 1px solid #e2e8f0; }
.scene-canvas { width: 100%; height: 360px; background: linear-gradient(to bottom, #e0f2fe 0%, #f0f9ff 70%, #e2e8f0 100%); border-radius: 6px; margin-top: 8px; }
.scene-controls { display: flex; align-items: center; gap: 12px; margin-top: 10px; flex-wrap: wrap; }
.scene-formula { margin-bottom: 4px; }
.formula-line { margin-top: 8px; font-size: 13px; color: #334155; font-family: ui-monospace, monospace; }
.status-text { font-size: 13px; color: #475569; font-family: ui-monospace, monospace; }
.teaching-card { background: #fffbeb; border-left: 4px solid #f59e0b; border-radius: 8px; padding: 10px 14px; margin-bottom: 10px; }
.teaching-card .teaching-title { font-weight: 700; color: #92400e; font-size: 13px; margin-bottom: 4px; }
.teaching-card p { color: #78350f; font-size: 12px; line-height: 1.6; margin: 0; }
.formula-panel { margin-top: 10px; border-radius: 8px; padding: 12px; display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.formula-train { background: #0f172a; }
.formula-stars { background: #4a044e; }
.fcard { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12); border-radius: 6px; padding: 8px 10px; }
.flabel { font-size: 11px; color: #94a3b8; margin-bottom: 4px; }
.formula-stars .flabel { color: #f9a8d4; }
.fval { font-size: 13px; font-family: ui-monospace, monospace; font-weight: 700; word-break: break-all; }
.fval.amber { color: #fcd34d; }
.fval.green { color: #6ee7b7; }
.milestone-row { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 10px; }
.milestone-label { font-size: 11px; color: #94a3b8; }
.milestone-btn { font-size: 11px; padding: 3px 8px; background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 4px; color: #475569; cursor: pointer; transition: all 0.15s; }
.milestone-btn:hover { background: #eff6ff; color: #2563eb; border-color: #bfdbfe; }
</style>

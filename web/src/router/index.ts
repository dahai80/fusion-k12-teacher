import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { inShell } from '@/shell'

const routes: RouteRecordRaw[] = [
  { path: '/login', name: 'login', component: () => import('@/pages/Login.vue'), meta: { public: true, title: '登录', titleEn: 'Login' } },
  { path: '/materials', name: 'materials', component: () => import('@/pages/MyMaterials.vue'), meta: { title: '我的资源库', titleEn: 'My Materials' } },
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', name: 'dashboard', component: () => import('@/pages/Dashboard.vue'), meta: { title: '工作台', titleEn: 'Dashboard' } },

  { path: '/lesson/plan', name: 'lesson-plan', component: () => import('@/pages/LessonPlan.vue'), meta: { title: '教案', titleEn: 'Lesson Plan' } },
  { path: '/lesson/unit', name: 'lesson-unit', component: () => import('@/pages/UnitPlan.vue'), meta: { title: '单元计划', titleEn: 'Unit Plan' } },
  { path: '/lesson/align', name: 'lesson-align', component: () => import('@/pages/StandardsAlign.vue'), meta: { title: '课标对齐', titleEn: 'Standards Align' } },

  { path: '/assess/quiz', name: 'assess-quiz', component: () => import('@/pages/Quiz.vue'), meta: { title: '测验', titleEn: 'Quiz' } },
  { path: '/assess/exercise', name: 'assess-exercise', component: () => import('@/pages/SubjectExercise.vue'), meta: { title: '练习题', titleEn: 'Exercise' } },
  { path: '/assess/diff', name: 'assess-diff', component: () => import('@/pages/Differentiation.vue'), meta: { title: '一键分层', titleEn: 'Differentiation' } },
  { path: '/assess/rubric', name: 'assess-rubric', component: () => import('@/pages/Rubric.vue'), meta: { title: '评分量表', titleEn: 'Rubric' } },

  { path: '/grade/math', name: 'grade-math', component: () => import('@/pages/GradeMath.vue'), meta: { title: '数学批改', titleEn: 'Math Grading' } },
  { path: '/grade/essay', name: 'grade-essay', component: () => import('@/pages/GradeEssay.vue'), meta: { title: '作文批改', titleEn: 'Essay Grading' } },
  { path: '/grade/report', name: 'grade-report', component: () => import('@/pages/StudentReport.vue'), meta: { title: '学生报告', titleEn: 'Student Report' } },

  { path: '/analytics/upload', name: 'analytics-upload', component: () => import('@/pages/AnalyticsUpload.vue'), meta: { title: '数据上传', titleEn: 'Upload' } },
  { path: '/analytics/class', name: 'analytics-class', component: () => import('@/pages/ClassProfile.vue'), meta: { title: '班级画像', titleEn: 'Class Profile' } },
  { path: '/analytics/student', name: 'analytics-student', component: () => import('@/pages/StudentProfile.vue'), meta: { title: '学生画像', titleEn: 'Student Profile' } },
  { path: '/analytics/error', name: 'analytics-error', component: () => import('@/pages/ErrorAnalysis.vue'), meta: { title: '错因分析', titleEn: 'Error Analysis' } },
  { path: '/analytics/remedial', name: 'analytics-remedial', component: () => import('@/pages/Remedial.vue'), meta: { title: '补救计划', titleEn: 'Remediation' } },
  { path: '/analytics/report', name: 'analytics-report', component: () => import('@/pages/ClassReport.vue'), meta: { title: '班级报告', titleEn: 'Class Report' } },

  { path: '/personalize/path', name: 'personalize-path', component: () => import('@/pages/LearningPath.vue'), meta: { title: '学习路径', titleEn: 'Learning Path' } },
  { path: '/personalize/diagnose', name: 'personalize-diagnose', component: () => import('@/pages/SkillDiagnose.vue'), meta: { title: '技能诊断', titleEn: 'Skill Diagnosis' } },
  { path: '/personalize/recommend', name: 'personalize-recommend', component: () => import('@/pages/ResourceRecommend.vue'), meta: { title: '资源推荐', titleEn: 'Recommendations' } },

  { path: '/content/worksheet', name: 'content-worksheet', component: () => import('@/pages/Worksheet.vue'), meta: { title: '工作纸', titleEn: 'Worksheet' } },
  { path: '/content/flashcards', name: 'content-flashcards', component: () => import('@/pages/Flashcards.vue'), meta: { title: '闪卡', titleEn: 'Flashcards' } },
  { path: '/content/slides', name: 'content-slides', component: () => import('@/pages/Slides.vue'), meta: { title: '课件', titleEn: 'Slides' } },
  { path: '/content/game', name: 'content-game', component: () => import('@/pages/EduGame.vue'), meta: { title: '教育游戏', titleEn: 'Edu Games' } },
  { path: '/content/parent', name: 'content-parent', component: () => import('@/pages/ParentComm.vue'), meta: { title: '家长沟通稿', titleEn: 'Parent Letter' } },

  { path: '/agent', name: 'agent', component: () => import('@/pages/Agent.vue'), meta: { title: '自动化', titleEn: 'Automation' } },
  { path: '/safety', name: 'safety', component: () => import('@/pages/Safety.vue'), meta: { title: '安全中心', titleEn: 'Safety' } },
  { path: '/desensitize', name: 'desensitize', component: () => import('@/pages/Desensitize.vue'), meta: { title: '数据隐私', titleEn: 'Privacy' } },
  { path: '/settings', name: 'settings', component: () => import('@/pages/Settings.vue'), meta: { title: '设置', titleEn: 'Settings' } },

  { path: '/course/math/graph', name: 'course-graph', component: () => import('@/pages/MathGraph.vue'), meta: { title: '知识图谱', titleEn: 'Knowledge Graph' } },
  { path: '/course/math/scene', name: 'course-scene', component: () => import('@/pages/MathScene.vue'), meta: { title: '场景动画', titleEn: 'Scene Animation' } },
  { path: '/course/math/lesson', name: 'course-lesson', component: () => import('@/pages/MathLesson.vue'), meta: { title: '苏格拉底课稿', titleEn: 'Socratic Lesson' } },
  { path: '/course/math/bank', name: 'course-bank', component: () => import('@/pages/ProblemBank.vue'), meta: { title: '题库', titleEn: 'Problem Bank' } },

  { path: '/classroom/teacher', name: 'classroom-teacher', component: () => import('@/pages/ClassroomTeacher.vue'), meta: { title: '课堂备课(师)', titleEn: 'Classroom Prep' } },
  { path: '/classroom/entry', name: 'classroom-entry', component: () => import('@/pages/ClassroomEntry.vue'), meta: { title: '课堂入口(生)', titleEn: 'Classroom Entry' } },
  { path: '/classroom/player', name: 'classroom-player', component: () => import('@/pages/ClassroomPlayer.vue'), meta: { title: '课堂播放', titleEn: 'Player' } },
  { path: '/classroom/report', name: 'classroom-report', component: () => import('@/pages/ClassroomReport.vue'), meta: { title: '课堂报告', titleEn: 'Report' } },

  { path: '/digital-human/self-study', name: 'dh-self-study', component: () => import('@/pages/DigitalHumanSelfStudy.vue'), meta: { title: '自主学习', titleEn: 'Self-Study' } },
  { path: '/digital-human/player', name: 'dh-player', component: () => import('@/pages/DigitalHumanPlayer.vue'), meta: { title: '数字人播放', titleEn: 'DH Player' } },
]

export const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

router.beforeEach((to, _from, next) => {
  const auth = useAuthStore()
  // issue #30: shell 嵌入态登录由宿主持有, 不强制跳转模块自有登录页 —
  // 教师绑定 (资源库自动保存) 仍可经 /login 自愿登录
  if (inShell()) {
    next()
    return
  }
  if (!auth.isLoggedIn && !to.meta.public) {
    // 未登录访问受保护页 → 登录页带 reason=auth, 页面据此显示"请先登录"提示
    // (原静默重定向让用户误以为菜单"点击没反应")
    next({ path: '/login', query: { reason: 'auth', from: to.fullPath } })
  } else if (auth.isLoggedIn && to.path === '/login') {
    next('/dashboard')
  } else {
    next()
  }
})

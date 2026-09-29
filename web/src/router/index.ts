import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes: RouteRecordRaw[] = [
  { path: '/login', name: 'login', component: () => import('@/pages/Login.vue'), meta: { public: true } },
  { path: '/materials', name: 'materials', component: () => import('@/pages/MyMaterials.vue') },
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', name: 'dashboard', component: () => import('@/pages/Dashboard.vue') },

  { path: '/lesson/plan', name: 'lesson-plan', component: () => import('@/pages/LessonPlan.vue') },
  { path: '/lesson/unit', name: 'lesson-unit', component: () => import('@/pages/UnitPlan.vue') },
  { path: '/lesson/align', name: 'lesson-align', component: () => import('@/pages/StandardsAlign.vue') },

  { path: '/assess/quiz', name: 'assess-quiz', component: () => import('@/pages/Quiz.vue') },
  { path: '/assess/exercise', name: 'assess-exercise', component: () => import('@/pages/SubjectExercise.vue') },
  { path: '/assess/diff', name: 'assess-diff', component: () => import('@/pages/Differentiation.vue') },
  { path: '/assess/rubric', name: 'assess-rubric', component: () => import('@/pages/Rubric.vue') },

  { path: '/grade/math', name: 'grade-math', component: () => import('@/pages/GradeMath.vue') },
  { path: '/grade/essay', name: 'grade-essay', component: () => import('@/pages/GradeEssay.vue') },
  { path: '/grade/report', name: 'grade-report', component: () => import('@/pages/StudentReport.vue') },

  { path: '/analytics/upload', name: 'analytics-upload', component: () => import('@/pages/AnalyticsUpload.vue') },
  { path: '/analytics/class', name: 'analytics-class', component: () => import('@/pages/ClassProfile.vue') },
  { path: '/analytics/student', name: 'analytics-student', component: () => import('@/pages/StudentProfile.vue') },
  { path: '/analytics/error', name: 'analytics-error', component: () => import('@/pages/ErrorAnalysis.vue') },
  { path: '/analytics/remedial', name: 'analytics-remedial', component: () => import('@/pages/Remedial.vue') },
  { path: '/analytics/report', name: 'analytics-report', component: () => import('@/pages/ClassReport.vue') },

  { path: '/personalize/path', name: 'personalize-path', component: () => import('@/pages/LearningPath.vue') },
  { path: '/personalize/diagnose', name: 'personalize-diagnose', component: () => import('@/pages/SkillDiagnose.vue') },
  { path: '/personalize/recommend', name: 'personalize-recommend', component: () => import('@/pages/ResourceRecommend.vue') },

  { path: '/content/worksheet', name: 'content-worksheet', component: () => import('@/pages/Worksheet.vue') },
  { path: '/content/flashcards', name: 'content-flashcards', component: () => import('@/pages/Flashcards.vue') },
  { path: '/content/slides', name: 'content-slides', component: () => import('@/pages/Slides.vue') },
  { path: '/content/game', name: 'content-game', component: () => import('@/pages/EduGame.vue') },
  { path: '/content/parent', name: 'content-parent', component: () => import('@/pages/ParentComm.vue') },

  { path: '/agent', name: 'agent', component: () => import('@/pages/Agent.vue') },
  { path: '/safety', name: 'safety', component: () => import('@/pages/Safety.vue') },
  { path: '/desensitize', name: 'desensitize', component: () => import('@/pages/Desensitize.vue') },
  { path: '/settings', name: 'settings', component: () => import('@/pages/Settings.vue') },

  { path: '/course/math/graph', name: 'course-graph', component: () => import('@/pages/MathGraph.vue') },
  { path: '/course/math/scene', name: 'course-scene', component: () => import('@/pages/MathScene.vue') },
  { path: '/course/math/lesson', name: 'course-lesson', component: () => import('@/pages/MathLesson.vue') },
  { path: '/course/math/bank', name: 'course-bank', component: () => import('@/pages/ProblemBank.vue') },

  { path: '/classroom/teacher', name: 'classroom-teacher', component: () => import('@/pages/ClassroomTeacher.vue') },
  { path: '/classroom/entry', name: 'classroom-entry', component: () => import('@/pages/ClassroomEntry.vue') },
  { path: '/classroom/player', name: 'classroom-player', component: () => import('@/pages/ClassroomPlayer.vue') },
  { path: '/classroom/report', name: 'classroom-report', component: () => import('@/pages/ClassroomReport.vue') },

  { path: '/digital-human/self-study', name: 'dh-self-study', component: () => import('@/pages/DigitalHumanSelfStudy.vue') },
  { path: '/digital-human/player', name: 'dh-player', component: () => import('@/pages/DigitalHumanPlayer.vue') },
]

export const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

router.beforeEach((to, _from, next) => {
  const auth = useAuthStore()
  if (!auth.isLoggedIn && !to.meta.public) {
    next('/login')
  } else if (auth.isLoggedIn && to.path === '/login') {
    next('/dashboard')
  } else {
    next()
  }
})

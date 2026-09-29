import { api } from './client'

export const healthApi = {
  health: () => api.get<{ status: string; model: string; ready: boolean }>('/api/health'),
  ready: () => api.get<{ ready: boolean }>('/api/ready'),
}

export const authApi = {
  register: (body: any) => api.post('/api/auth/register', body),
  login: (body: any) => api.post('/api/auth/login', body),
  me: () => api.get('/api/auth/me'),
  logout: () => api.post('/api/auth/logout'),
}

export const textbookApi = {
  editions: () => api.get('/api/textbook/editions'),
  grades: (edition: string, subject: string) => api.get(`/api/textbook/${edition}/${subject}/grades`),
  units: (edition: string, subject: string, grade: string) => api.get(`/api/textbook/${edition}/${subject}/${grade}/units`),
  lesson: (edition: string, subject: string, grade: string, lessonId: string) =>
    api.get(`/api/textbook/${edition}/${subject}/${grade}/lesson/${lessonId}`),
}

export const materialsApi = {
  list: (query?: any) => api.get('/api/materials', query),
  get: (id: string) => api.get(`/api/materials/${id}`),
  delete: (id: string) => api.del(`/api/materials/${id}`),
}

export const curriculumApi = {
  plan: (body: any) => api.post('/api/curriculum/plan', body),
  quiz: (body: any) => api.post('/api/curriculum/quiz', body),
  unitPlan: (body: any) => api.post('/api/curriculum/unit-plan', body),
  planDiff: (body: any) => api.post('/api/curriculum/plan-diff', body),
  quizDiff: (body: any) => api.post('/api/curriculum/quiz-diff', body),
}

export const assessmentApi = {
  grade: (body: any) => api.post('/api/assessment/grade', body),
  essay: (body: any) => api.post('/api/assessment/essay', body),
  report: (body: any) => api.post('/api/assessment/report', body),
  rubric: (body: any) => api.post('/api/assessment/rubric', body),
}

export const subjectApi = {
  explain: (body: any) => api.post('/api/subject/explain', body),
  exercise: (body: any) => api.post('/api/subject/exercise', body),
  stemProject: (body: any) => api.post('/api/subject/stem-project', body),
  languageActivity: (body: any) => api.post('/api/subject/language-activity', body),
}

export const personalizationApi = {
  path: (body: any) => api.post('/api/personalize/path', body),
  diagnose: (body: any) => api.post('/api/personalize/diagnose', body),
  recommend: (body: any) => api.post('/api/personalize/recommend', body),
}

export const contentApi = {
  generate: (body: any) => api.post('/api/content/generate', body),
  parentCommunication: (body: any) => api.post('/api/content/parent-communication', body),
  worksheetDiff: (body: any) => api.post('/api/content/worksheet-diff', body),
}

export const analyticsApi = {
  upload: (file: File) => api.upload('/api/analytics/upload', file),
  template: (fmt: 'json' | 'csv') => api.blob(`/api/analytics/template/${fmt}`),
  classProfile: (body: any) => api.post('/api/analytics/class-profile', body),
  studentProfile: (body: any) => api.post('/api/analytics/student-profile', body),
  errorAnalysis: (body: any) => api.post('/api/analytics/error-analysis', body),
  remedial: (body: any) => api.post('/api/analytics/remedial', body),
  classReport: (body: any) => api.post('/api/analytics/class-report', body),
}

export const agentApi = {
  tasks: () => api.get('/api/agent/tasks'),
  run: (body: any) => api.post('/api/agent/run', body),
  history: () => api.get('/api/agent/history'),
}

export const safetyApi = {
  checkText: (body: any) => api.post('/api/safety/check', body),
  filterLevel: () => api.get('/api/safety/filter-level'),
  sensitiveWords: () => api.get('/api/safety/sensitive-words'),
  addWord: (body: any) => api.post('/api/safety/sensitive-words', body),
  removeWord: (word: string) => api.del('/api/safety/sensitive-words/' + encodeURIComponent(word)),
}

export const desensitizeApi = {
  anonymize: (body: any) => api.post('/api/desensitize/anonymize', body),
  deanonymize: (body: any) => api.post('/api/desensitize/deanonymize', body),
  export: (body: any) => api.post('/api/desensitize/export', body),
}

export const standardsApi = {
  align: (body: any) => api.post('/api/standards/align', body),
  coverage: (body: any) => api.post('/api/standards/coverage', body),
  remediate: (body: any) => api.post('/api/standards/remediate', body),
  knowledgePoints: (query: any) => api.get('/api/standards/knowledge-points', query),
}

export const courseApi = {
  subjects: () => api.get('/api/course/subjects'),
  graphNodes: (subject: string, query: any) => api.get(`/api/course/${subject}/graph/nodes`, query),
  graphNode: (subject: string, id: string) => api.get(`/api/course/${subject}/graph/node/${id}`),
  lessonScript: (subject: string, body: any) => api.post(`/api/course/${subject}/lesson-script`, body),
  checkpoint: (subject: string, body: any) => api.post(`/api/course/${subject}/checkpoint`, body),
  sceneCompile: (subject: string, body: any) => api.post(`/api/course/${subject}/scene-compile`, body),
  errorAttribution: (subject: string, body: any) => api.post(`/api/course/${subject}/error-attribution`, body),
  mastery: (subject: string, studentId: string) => api.get(`/api/course/${subject}/mastery/${studentId}`),
  problemBank: (subject: string, query?: any) => api.get(`/api/course/${subject}/problem-bank`, query),
  problemDetail: (subject: string, id: string) => api.get(`/api/course/${subject}/problem-bank/${id}`),
}

export const classroomApi = {
  script: (body: any) => api.post('/api/classroom/script', body),
  pack: (body: any) => api.post('/api/classroom/pack', body),
  getPack: (code: string) => api.get(`/api/classroom/pack/${code}`),
  listPacks: () => api.get('/api/classroom/packs'),
  createSession: (body: any) => api.post('/api/classroom/session', body),
  finishSession: (sid: string, abandoned = false) => api.patch(`/api/classroom/session/${sid}/finish?abandoned=${abandoned}`),
  answer: (body: any) => api.post('/api/classroom/answer', body),
  viewPage: (sid: string, idx: number) => api.get(`/api/classroom/session/${sid}/page/${idx}`),
  report: (sid: string) => api.get(`/api/classroom/report/${sid}`),
  listSessions: (classId: string) => api.get(`/api/classroom/sessions/${classId}`),
}

export const metricsApi = {
  metrics: () => api.get('/api/metrics'),
  audit: () => api.get('/api/audit/export'),
}

export const digitalHumanApi = {
  createSession: (body: any) => api.post('/api/digital-human/session', body),
  token: (body: any) => api.post('/api/digital-human/token', body),
  narrate: (body: any) => api.post('/api/digital-human/narrate', body),
  raiseHand: (body: any) => api.post('/api/digital-human/raise-hand', body),
  finish: (body: any) => api.post('/api/digital-human/finish', body),
}

export function digitalHumanWsUrl(sessionId: string): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}/ws/digital-human/${sessionId}`
}

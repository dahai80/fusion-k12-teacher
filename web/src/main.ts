import { createApp } from 'vue'
import { createPinia } from 'pinia'
import '@fusion/design-tokens/tokens.css'
import './style.css'
import App from './App.vue'
import { router } from './router'
import { initTheme } from './shellTheme'
import { initI18n } from './i18n'

// issue #38: 主题/语言通道先于挂载初始化 — 嵌入态首帧即随宿主主题/语言
initTheme()
initI18n()

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')

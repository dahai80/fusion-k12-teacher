// 主题通道 (issue #38, spec §3.1): 暗色默认, 模块经 SDK theme API 感知,
// 禁止自行检测 — 嵌入态以宿主推送为准; 独立态走 localStorage →
// prefers-color-scheme → dark 兜底链 (cowork theme.ts 同款约定)。
// 应用方式: html 根元素 light/dark class (design-tokens: dark 为默认,
// html.light 翻转 --fs-* 调色板) + naive-ui darkTheme (App.vue)。
import { ref, type Ref } from 'vue'
import { sdk } from './sdk'
import { inShell } from './shell'

export type ThemeMode = 'dark' | 'light'

const STORAGE_KEY = 'fusion.shell.theme'

const mode = ref<ThemeMode>('dark')

export function applyTheme(m: ThemeMode): void {
    mode.value = m
    const root = document.documentElement
    root.classList.toggle('light', m === 'light')
    root.classList.toggle('dark', m === 'dark')
}

function initialStandalone(): ThemeMode {
    try {
        const stored = localStorage.getItem(STORAGE_KEY)
        if (stored === 'light' || stored === 'dark') return stored
    } catch {
        // 隐私模式 storage 不可用 — 走后续链
    }
    if (typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: light)').matches) {
        return 'light'
    }
    return 'dark'
}

let started = false

export function initTheme(): void {
    if (started) return
    started = true
    applyTheme(inShell() ? (sdk.theme.get() === 'light' ? 'light' : 'dark') : initialStandalone())
    sdk.theme.subscribe((m) => {
        applyTheme(m === 'light' ? 'light' : 'dark')
        try {
            localStorage.setItem(STORAGE_KEY, m)
        } catch {
            // storage 不可用时主题本次会话仍生效
        }
    })
}

export function useShellTheme(): Ref<ThemeMode> {
    return mode
}

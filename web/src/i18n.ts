// 语言通道 (issue #38, spec §177): 界面文案跟随 Shell 语言 —
// 嵌入态由宿主推送 lang 事件 (sdk.i18n), 独立态跟随 <html lang>。
// 首版覆盖: 菜单/页头/按钮/四态 (spec 允许的 v1 范围)。
import { ref, type Ref } from 'vue'
import { sdk } from './sdk'

export type Lang = 'zh' | 'en'

const lang = ref<Lang>(sdk.i18n.lang() === 'en' ? 'en' : 'zh')

let started = false

export function initI18n(): void {
    if (started) return
    started = true
    sdk.i18n.subscribe((next) => {
        lang.value = next === 'en' ? 'en' : 'zh'
        document.documentElement.lang = next === 'en' ? 'en' : 'zh-CN'
    })
}

export function useLang(): Ref<Lang> {
    return lang
}

export function t(zh: string, en: string): string {
    return lang.value === 'en' ? en : zh
}

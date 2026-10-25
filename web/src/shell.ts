// Union Web shell 嵌入模式检测 (issue #30, PRD R-3)
// Embedded (union-web shell iframe): shell 拥有外层 chrome 与登录态,
// 模块经网关同源代理 /shell/fusion-k12-teacher/ 访问后端 — 网关注入
// module api_key, UI 不持有 key; 教师身份登录可选 (仅资源库/教材
// 自动保存等教师绑定功能需要)。
// Standalone (pnpm dev / serve 静态托管): 自有登录页 + 自管 key, 行为不变。

export const isEmbedded = (): boolean =>
  typeof window !== 'undefined' && window.parent !== window

// ?embedded=1 由 shell 加载 iframe 时追加 — iframe 直开 (非 shell 宿主) 不算
export const embeddedParam = (): boolean => {
  try {
    return new URLSearchParams(window.location.search).get('embedded') === '1'
  } catch (e) {
    return false
  }
}

// 嵌入态 = 在 iframe 内 (对齐 cowork sdk.ts 约定: shell 生产 iframe 不带
// ?embedded=1, 该参数仅 dev 覆盖时追加; 父窗口存在即视为宿主托管)
export const inShell = (): boolean => isEmbedded()

// Union Web shell SDK 单例 (issue #38)。
// 嵌入态: postMessage 桥接宿主 (theme/lang/http 代理); 独立态: SDK 内部
// 自动降级 standalone 模式 (浏览器主题/直连 fetch), 行为与旧版一致。
import { createShellSdk, type FusionShellSdk } from '@fusion/web-sdk'

export const sdk: FusionShellSdk = createShellSdk()

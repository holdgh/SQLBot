import Prompt from '@/views/system/prompt/index.vue'
import { i18n } from '@/i18n'

const t = i18n.global.t

// ========= 【改造标记 CUSTOM-PROMPT】↓ 自定义提示词路由定义（index.ts 挂载 / watch.ts 在 xpack removeRoute 后恢复，共用同一份） =========
export const promptRoute = {
  path: '/set/prompt',
  name: 'prompt',
  component: Prompt,
  meta: { title: t('prompt.customize_prompt_words') },
}
// ========= 【改造标记 CUSTOM-PROMPT】↑ 路由定义结束 =========

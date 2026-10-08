import { ElMessage } from 'element-plus-secondary'
import { useCache } from '@/utils/useCache'
import { useAppearanceStoreWithOut } from '@/stores/appearance'
import { useUserStore } from '@/stores/user'
import { request } from '@/utils/request'
import type { Router } from 'vue-router'
import { generateDynamicRouters } from './dynamic'
// ========= 【改造标记 CUSTOM-PROMPT】↓ 自定义提示词路由定义，用于 xpack removeRoute 后恢复 =========
import { promptRoute } from './promptRoute'
// ========= 【改造标记 CUSTOM-PROMPT】↑ 导入结束 =========
import { toLoginPage } from '@/utils/utils'

const appearanceStore = useAppearanceStoreWithOut()
const userStore = useUserStore()
const { wsCache } = useCache()
const whiteList = ['/login', '/admin-login']
const assistantWhiteList = ['/assistant', '/embeddedPage', '/embeddedCommon', '/401']

const wsAdminRouterList = ['/ds/index', '/as/index']
export const watchRouter = (router: Router) => {
  router.beforeEach(async (to: any, from: any, next: any) => {
    await loadXpackStatic()
    await appearanceStore.setAppearance()
    LicenseGenerator.generateRouters(router)
    // ========= 【改造标记 CUSTOM-PROMPT】↓ 方案A：License 无效时 xpack generateRouters 会 removeRoute 掉 prompt
    // （appearance/audit 等一并被删），导致自定义提示词菜单与页面消失；
    // 此处每次导航后把 prompt 路由重新挂回 /set（xpack 每次都会再删，故需逐次补挂）。
    // addRoute 只恢复路由匹配（页面可进）；xpack 还会直接把 set 记录的 children 数组里的
    // prompt 项 splice 掉（Menu.vue 菜单就是渲染这个数组），故需按 generateDynamicRouters
    // 的既有写法把子路由再 push 回父记录 children，菜单项才恢复 =========
    if (router.hasRoute('set') && !router.hasRoute(promptRoute.name)) {
      router.addRoute('set', promptRoute)
    }
    const setMenuRecord = router.getRoutes().find((r: any) => r.name === 'set') as any
    if (
      setMenuRecord?.children &&
      !setMenuRecord.children.some((c: any) => c.name === promptRoute.name)
    ) {
      setMenuRecord.children.push(promptRoute)
    }
    // ========= 【改造标记 CUSTOM-PROMPT】↑ 路由恢复结束 =========
    if (to.path.startsWith('/login') && userStore.getUid) {
      next(to?.query?.redirect || '/')
      return
    }
    if (assistantWhiteList.includes(to.path)) {
      next()
      return
    }
    const token = wsCache.get('user.token')
    if (whiteList.includes(to.path)) {
      next()
      return
    }
    if (!token) {
      // ElMessage.error('Please login first')
      next(toLoginPage(to.fullPath))
      return
    }
    if (!userStore.getUid) {
      await userStore.info()
      generateDynamicRouters(router)
      const isFirstDynamicPath = to?.path && ['/ds/index', '/as/index'].includes(to.path)
      if (isFirstDynamicPath) {
        if (userStore.isSpaceAdmin) {
          next({ ...to, replace: true })
          return
        }
      }
    }
    if (to.path === '/docs') {
      location.href = to.fullPath
      return
    }
    if (to.path === '/' || accessCrossPermission(to)) {
      next('/chat')
      return
    }
    if (to.path === '/login' || to.path === '/admin-login') {
      console.info(from)
      next('/chat')
    } else {
      next()
    }
  })
}

const accessCrossPermission = (to: any) => {
  if (!to?.path) return false
  return (
    (to.path.startsWith('/system') && !userStore.isAdmin) ||
    (to.path.startsWith('/set') && !userStore.isSpaceAdmin) ||
    (isWsAdminRouter(to) && !userStore.isSpaceAdmin)
  )
}

const isWsAdminRouter = (to?: any) => {
  return wsAdminRouterList.some((item: string) => to?.path?.startsWith(item))
}
const loadXpackStatic = () => {
  if (document.getElementById('sqlbot_xpack_static')) {
    return Promise.resolve()
  }
  const url = `/xpack_static/license-generator.umd.js?t=${Date.now()}`
  return new Promise((resolve, reject) => {
    request
      .loadRemoteScript(url, 'sqlbot_xpack_static', () => {
        LicenseGenerator?.init(import.meta.env.VITE_API_BASE_URL).then(() => {
          resolve(true)
        })
      })
      .catch((error) => {
        console.error('Failed to load xpack_static script:', error)
        ElMessage.error('Failed to load license generator script')
        reject(error)
      })
  })
}

import type { Directive } from 'vue'
import { useUserStore } from '@/stores/user'

/**
 * v-permission：按权限码控制元素显隐。
 *
 * 用法：
 *   <el-button v-permission="'device:manage'">新建</el-button>
 *   <el-button v-permission="['device:manage', 'device:approve']">操作</el-button>
 *
 * 当前用户权限码（userStore.permissions）与传入码无交集时，元素在 mounted 时
 * 从 DOM 移除。注意：这是创建期裁剪，非响应式（权限变更需重渲染路由/组件）。
 */
export const vPermission: Directive<HTMLElement, string | string[]> = {
  mounted(el, binding) {
    const u = useUserStore()
    const codes = Array.isArray(binding.value) ? binding.value : [binding.value]
    if (!codes.some((c) => u.permissions.includes(c))) {
      el.parentNode?.removeChild(el)
    }
  },
}

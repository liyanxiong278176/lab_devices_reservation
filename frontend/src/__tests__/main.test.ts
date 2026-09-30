import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'

const mocks = vi.hoisted(() => {
  const app = {
    component: vi.fn(),
    directive: vi.fn(),
    use: vi.fn(),
    mount: vi.fn(),
  }
  const pinia = { use: vi.fn() }
  app.use.mockImplementation(() => app)
  return {
    app,
    createApp: vi.fn(() => app),
    pinia,
    createPinia: vi.fn(() => pinia),
    persistedPlugin: vi.fn(),
    initialize: vi.fn(),
    themeInit: vi.fn(),
  }
})

vi.mock('vue', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue')>()
  return { ...actual, createApp: mocks.createApp }
})
vi.mock('pinia', () => ({ createPinia: mocks.createPinia }))
vi.mock('pinia-plugin-persistedstate', () => ({ default: mocks.persistedPlugin }))
vi.mock('@/router', () => ({ default: { name: 'router' } }))
vi.mock('@/directives/permission', () => ({ vPermission: { mounted: vi.fn() } }))
vi.mock('@/stores/user', () => ({ useUserStore: () => ({ initialize: mocks.initialize }) }))
vi.mock('@/stores/theme', () => ({ useThemeStore: () => ({ init: mocks.themeInit }) }))
vi.mock('@/App.vue', () => ({ default: { name: 'AppRoot' } }))

vi.mock('@element-plus/icons-vue', () => {
  return Object.fromEntries(
    [
      'Bell',
      'Calendar',
      'Checked',
      'Connection',
      'Cpu',
      'DataAnalysis',
      'MagicStick',
      'Lock',
      'OfficeBuilding',
      'Odometer',
      'SetUp',
      'Setting',
      'Tools',
      'UserFilled',
      'Warning',
    ].map((name) => [name, { name }]),
  )
})

vi.mock('element-plus/es/components/alert/index', () => ({ ElAlert: { name: 'ElAlert' } }))
vi.mock('element-plus/es/components/badge/index', () => ({ ElBadge: { name: 'ElBadge' } }))
vi.mock('element-plus/es/components/button/index', () => ({ ElButton: { name: 'ElButton' } }))
vi.mock('element-plus/es/components/checkbox/index', () => ({
  ElCheckbox: { name: 'ElCheckbox' },
  ElCheckboxGroup: { name: 'ElCheckboxGroup' },
}))
vi.mock('element-plus/es/components/col/index', () => ({ ElCol: { name: 'ElCol' } }))
vi.mock('element-plus/es/components/container/index', () => ({ ElContainer: { name: 'ElContainer' } }))
vi.mock('element-plus/es/components/date-picker/index', () => ({ ElDatePicker: { name: 'ElDatePicker' } }))
vi.mock('element-plus/es/components/dialog/index', () => ({ ElDialog: { name: 'ElDialog' } }))
vi.mock('element-plus/es/components/drawer/index', () => ({ ElDrawer: { name: 'ElDrawer' } }))
vi.mock('element-plus/es/components/dropdown/index', () => ({ ElDropdown: { name: 'ElDropdown' } }))
vi.mock('element-plus/es/components/form/index', () => ({ ElForm: { name: 'ElForm' } }))
vi.mock('element-plus/es/components/icon/index', () => ({ ElIcon: { name: 'ElIcon' } }))
vi.mock('element-plus/es/components/input/index', () => ({ ElInput: { name: 'ElInput' } }))
vi.mock('element-plus/es/components/input-number/index', () => ({ ElInputNumber: { name: 'ElInputNumber' } }))
vi.mock('element-plus/es/components/loading/index', () => ({ ElLoading: { name: 'ElLoading' } }))
vi.mock('element-plus/es/components/menu/index', () => ({ ElMenu: { name: 'ElMenu' } }))
vi.mock('element-plus/es/components/message/index', () => ({ ElMessage: { name: 'ElMessage' } }))
vi.mock('element-plus/es/components/message-box/index', () => ({ ElMessageBox: { name: 'ElMessageBox' } }))
vi.mock('element-plus/es/components/notification/index', () => ({ ElNotification: { name: 'ElNotification' } }))
vi.mock('element-plus/es/components/pagination/index', () => ({ ElPagination: { name: 'ElPagination' } }))
vi.mock('element-plus/es/components/progress/index', () => ({ ElProgress: { name: 'ElProgress' } }))
vi.mock('element-plus/es/components/radio/index', () => ({ ElRadio: { name: 'ElRadio' } }))
vi.mock('element-plus/es/components/rate/index', () => ({ ElRate: { name: 'ElRate' } }))
vi.mock('element-plus/es/components/row/index', () => ({ ElRow: { name: 'ElRow' } }))
vi.mock('element-plus/es/components/select/index', () => ({ ElSelect: { name: 'ElSelect' } }))
vi.mock('element-plus/es/components/switch/index', () => ({ ElSwitch: { name: 'ElSwitch' } }))
vi.mock('element-plus/es/components/table/index', () => ({ ElTable: { name: 'ElTable' } }))
vi.mock('element-plus/es/components/tabs/index', () => ({ ElTabs: { name: 'ElTabs' } }))
vi.mock('element-plus/es/components/tag/index', () => ({ ElTag: { name: 'ElTag' } }))
vi.mock('element-plus/es/components/tree-select/index', () => ({ ElTreeSelect: { name: 'ElTreeSelect' } }))

vi.mock('element-plus/dist/index.css', () => ({}))
vi.mock('element-plus/theme-chalk/dark/css-vars.css', () => ({}))
vi.mock('vue-echarts/style.css', () => ({}))
vi.mock('@fontsource/jetbrains-mono/400.css', () => ({}))
vi.mock('@fontsource-variable/plus-jakarta-sans/wght.css', () => ({}))
vi.mock('../styles/theme.scss', () => ({}))
vi.mock('../styles/_motion.scss', () => ({}))

describe('application bootstrap', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.clearAllMocks()
    mocks.app.use.mockImplementation(() => mocks.app)
    mocks.initialize.mockResolvedValue(undefined)
  })

  it('registers the app shell, plugins, permissions, icons, theme, and mounts after identity hydration', async () => {
    await import('../main')
    await flushPromises()

    expect(mocks.createApp).toHaveBeenCalledWith({ name: 'AppRoot' })
    expect(mocks.createPinia).toHaveBeenCalledOnce()
    expect(mocks.pinia.use).toHaveBeenCalledWith(mocks.persistedPlugin)
    expect(mocks.app.directive).toHaveBeenCalledWith('permission', expect.any(Object))
    expect(mocks.app.component).toHaveBeenCalledTimes(15)
    expect(mocks.app.use).toHaveBeenCalledTimes(33)
    expect(mocks.themeInit).toHaveBeenCalledOnce()
    expect(mocks.initialize).toHaveBeenCalledOnce()
    expect(mocks.app.mount).toHaveBeenCalledWith('#app')
    expect(document.documentElement.classList.contains('js')).toBe(true)
  })

})

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { useUserStore } from '@/stores/user'
import { useStagger } from '@/composables/useStagger'
import GradientButton from '@/components/ui/GradientButton.vue'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const formRef = ref<FormInstance>()
const loading = ref(false)
const form = reactive({
  username: 'admin',
  password: 'admin123',
})

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function onSubmit() {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    loading.value = true
    try {
      await userStore.login({ username: form.username, password: form.password })
      await userStore.fetchMe()
      ElMessage.success('登录成功')
      const redirect = (route.query.redirect as string) || '/dashboard'
      router.push(redirect)
    } catch {
      // 错误信息已由 request.ts 拦截器通过 ElMessage 提示
    } finally {
      loading.value = false
    }
  })
}

// 入场错峰容器(spec §6.2 stagger 机制;reduced-motion 由 useStagger 内部短路)
const rootRef = ref<HTMLElement | null>(null)
useStagger(rootRef, { delay: 80 })
</script>

<template>
  <main class="login-page" ref="rootRef">
    <!-- ===================== 左:品牌 hero ===================== -->
    <section class="login-hero" aria-hidden="true">
      <!-- 流动 aurora 渐变层(青/蓝系;无紫) -->
      <div class="login-hero__aura login-hero__aura--cyan"></div>
      <div class="login-hero__aura login-hero__aura--blue"></div>
      <div class="login-hero__aura login-hero__aura--haze"></div>

      <!-- 极弱网格底纹(科技质感) -->
      <div class="login-hero__grid"></div>

      <!-- 品牌标题 -->
      <div class="login-hero__brand" data-stagger>
        <div class="login-hero__logo-mark">
          <span class="login-hero__logo-dot"></span>
          LabFlow
        </div>
        <h1 class="login-hero__title">实验室设备<br />智能预约平台</h1>
        <p class="login-hero__tagline">
          高校实验室设备 · 一站式预约、审批与全生命周期管控
        </p>
      </div>

      <!-- 漂浮设备卡碎片(产品 UI 碎片,致敬 Cal "产品 UI 嵌卡"理念) -->
      <div class="login-hero__chip login-hero__chip--1" data-stagger>
        <span class="chip-status chip-status--free"></span>
        <div class="chip-body">
          <p class="chip-name">奥林巴斯 BX53</p>
          <p class="chip-meta">显微镜 · 空闲</p>
        </div>
      </div>
      <div class="login-hero__chip login-hero__chip--2" data-stagger>
        <span class="chip-status chip-status--busy"></span>
        <div class="chip-body">
          <p class="chip-name">赛默飞 Trace 1310</p>
          <p class="chip-meta">气相色谱 · 使用中</p>
        </div>
      </div>
      <div class="login-hero__chip login-hero__chip--3" data-stagger>
        <span class="chip-status chip-status--free"></span>
        <div class="chip-body">
          <p class="chip-name">键元 UHPLC-3000</p>
          <p class="chip-meta">液相色谱 · 空闲</p>
        </div>
      </div>
    </section>

    <!-- ===================== 右:毛玻璃登录卡 ===================== -->
    <section class="login-form-wrap">
      <div class="login-card" data-stagger>
        <header class="login-card__head">
          <h2 class="login-card__title">欢迎回来</h2>
          <p class="login-card__subtitle">登录以继续</p>
        </header>

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          label-position="top"
          size="large"
          @keyup.enter="onSubmit"
        >
          <el-form-item label="用户名" prop="username">
            <el-input v-model="form.username" placeholder="请输入用户名" clearable />
          </el-form-item>
          <el-form-item label="密码" prop="password">
            <el-input
              v-model="form.password"
              type="password"
              placeholder="请输入密码"
              show-password
              clearable
            />
          </el-form-item>

          <GradientButton
            class="login-card__submit"
            :loading="loading"
            @click="onSubmit"
          >
            登录
          </GradientButton>
        </el-form>

        <footer class="login-card__hint">
          <span>演示账号</span>
          <code>admin / admin123</code>
        </footer>
      </div>
    </section>
  </main>
</template>

<style scoped lang="scss">
// =====================================================================
// Login 分屏 hero —— spec §7
// 左:品牌 hero(流动 aurora + 漂浮设备碎片 + 渐变标题)
// 右:毛玻璃登录卡(backdrop-filter 捕获 hero aura)
// 走 token + rgba 派生;reduced-motion 由 _motion.scss 全局守卫 + 本页局部守卫双覆盖。
// =====================================================================

.login-page {
  display: grid;
  grid-template-columns: 1fr 1fr;
  min-height: 100vh;
  // 透明:让全局 .aurora-bg(z0)与 hero 自身 aura 共同构成底色氛围
  background: transparent;
}

// =====================================================================
// 左:hero
// =====================================================================
.login-hero {
  position: relative;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 64px;
  color: var(--text-primary);
  // hero 区独立底色渐变(青/蓝调,深色基底)
  background: linear-gradient(135deg, rgba(10, 14, 20, 0.4), color-mix(in srgb, var(--bg-surface) 75%, transparent));
  // 隔离堆叠上下文:防止 backdrop-filter 跨层失效
  isolation: isolate;

  // ---- aura blob 层(青/蓝系;无紫;仅 transform+opacity,GPU)----
  &__aura {
    position: absolute;
    border-radius: 50%;
    filter: blur(60px);
    pointer-events: none;
    z-index: 0;
    will-change: transform, opacity;

    &--cyan {
      width: 520px;
      height: 520px;
      top: -120px;
      left: -100px;
      background: radial-gradient(circle, color-mix(in srgb, var(--accent) 28%, transparent), transparent 65%);
      animation: login-aura 18s var(--ease-out-expo) infinite;
    }

    &--blue {
      width: 480px;
      height: 480px;
      bottom: -120px;
      right: -80px;
      background: radial-gradient(circle, color-mix(in srgb, var(--accent-blue) 22%, transparent), transparent 65%);
      animation: login-aura 22s var(--ease-out-expo) infinite reverse;
    }

    &--haze {
      width: 380px;
      height: 380px;
      top: 40%;
      left: 35%;
      background: radial-gradient(circle, rgba(103, 232, 249, 0.14), transparent 60%);
      animation: login-aura 26s var(--ease-out-expo) infinite;
      animation-delay: -8s;
    }
  }

  // ---- 极弱网格底纹(科技质感;subtle 不抢戏)----
  &__grid {
    position: absolute;
    inset: 0;
    z-index: 0;
    pointer-events: none;
    background-image:
      linear-gradient(rgba(255, 255, 255, 0.025) 1px, transparent 1px),
      linear-gradient(90deg, rgba(255, 255, 255, 0.025) 1px, transparent 1px);
    background-size: 40px 40px;
    mask-image: radial-gradient(ellipse at 30% 40%, #000 30%, transparent 75%);
    -webkit-mask-image: radial-gradient(ellipse at 30% 40%, #000 30%, transparent 75%);
  }

  // ---- 品牌标题区 ----
  &__brand {
    position: relative;
    z-index: 2;
    max-width: 520px;
  }

  &__logo-mark {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    padding: 6px 14px 6px 12px;
    border-radius: var(--radius-pill);
    background: color-mix(in srgb, var(--accent) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent) 25%, transparent);
    color: var(--accent-bright);
    font-family: var(--font-display);
    font-size: 14px;
    font-weight: 600;
    letter-spacing: 0.04em;
  }

  &__logo-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--accent);
    box-shadow: 0 0 12px color-mix(in srgb, var(--accent) 70%, transparent);
  }

  &__title {
    margin: 24px 0 16px;
    font-family: var(--font-display);
    font-size: 56px;
    font-weight: 600;
    line-height: 1.05;
    letter-spacing: -0.02em;
    // 渐变文字:hero 标题更"signature"(青→蓝,无紫)
    background: linear-gradient(135deg, #e6edf3 0%, #67e8f9 55%, #3b82f6 100%);
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
    color: transparent;
  }

  &__tagline {
    margin: 0;
    font-size: 17px;
    line-height: 1.6;
    color: var(--text-secondary);
    max-width: 460px;
  }

  // ---- 漂浮设备卡碎片 ----
  &__chip {
    position: absolute;
    z-index: 1;
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 14px 18px;
    min-width: 220px;
    // 毛玻璃小卡(登录卡同款材质,弱化版)
    background: color-mix(in srgb, var(--bg-surface) 55%, transparent);
    backdrop-filter: blur(14px) saturate(140%);
    -webkit-backdrop-filter: blur(14px) saturate(140%);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-card);
    box-shadow: var(--shadow-soft-light);
    color: var(--text-primary);
    will-change: transform;

    &--1 {
      top: 16%;
      right: 10%;
      animation: login-float 7s var(--ease-out-expo) infinite;
    }

    &--2 {
      bottom: 16%;
      right: 22%;
      animation: login-float 9s var(--ease-out-expo) infinite;
      animation-delay: -2s;
    }

    &--3 {
      bottom: 32%;
      left: 6%;
      animation: login-float 8s var(--ease-out-expo) infinite;
      animation-delay: -4s;
    }
  }

  .chip-status {
    flex: none;
    width: 10px;
    height: 10px;
    border-radius: 50%;

    &--free {
      background: var(--status-success);
      box-shadow: 0 0 10px color-mix(in srgb, var(--status-success) 60%, transparent);
    }

    &--busy {
      background: var(--status-warning);
      box-shadow: 0 0 10px color-mix(in srgb, var(--status-warning) 50%, transparent);
    }
  }

  .chip-name {
    margin: 0;
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
  }

  .chip-meta {
    margin: 2px 0 0;
    font-size: 12px;
    color: var(--text-tertiary);
    font-family: var(--font-mono);
  }
}

// =====================================================================
// hero aura 漂移 keyframes(仅 transform + opacity,GPU 合成层)
// =====================================================================
@keyframes login-aura {
  0% {
    transform: translate3d(-6%, -4%, 0) scale(1);
    opacity: 0.55;
  }
  50% {
    transform: translate3d(8%, 6%, 0) scale(1.18);
    opacity: 0.9;
  }
  100% {
    transform: translate3d(-6%, -4%, 0) scale(1);
    opacity: 0.55;
  }
}

// =====================================================================
// 漂浮碎片 float(translateY 缓慢循环,GPU)
// =====================================================================
@keyframes login-float {
  0%,
  100% {
    transform: translate3d(0, 0, 0);
  }
  50% {
    transform: translate3d(0, -14px, 0);
  }
}

// =====================================================================
// 右:毛玻璃登录卡
// =====================================================================
.login-form-wrap {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px;
  background: transparent; // 透明:让左侧 aura 透过来被毛玻璃捕获
}

.login-card {
  width: 100%;
  max-width: 420px;
  padding: 40px 36px;
  // 毛玻璃(spec §7:blur(20px) saturate(140%) + 半透明底)
  background: color-mix(in srgb, var(--bg-surface) 60%, transparent);
  backdrop-filter: blur(20px) saturate(140%);
  -webkit-backdrop-filter: blur(20px) saturate(140%);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-card);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.05),
    0 20px 50px rgba(0, 0, 0, 0.45);

  &__head {
    margin-bottom: 28px;
  }

  &__title {
    margin: 0;
    font-family: var(--font-display);
    font-size: 28px;
    font-weight: 600;
    line-height: 1.2;
    letter-spacing: -0.01em;
    color: var(--text-primary);
  }

  &__subtitle {
    margin: 8px 0 0;
    font-size: 14px;
    color: var(--text-secondary);
  }

  &__submit {
    width: 100%;
    margin-top: 8px;
    height: 44px;
    font-size: 15px;
  }

  &__hint {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    margin-top: 24px;
    padding-top: 20px;
    border-top: 1px solid var(--border-subtle);
    font-size: 12px;
    color: var(--text-tertiary);

    code {
      padding: 2px 8px;
      border-radius: var(--radius-control);
      background: var(--bg-sunken);
      border: 1px solid var(--border-subtle);
      font-family: var(--font-mono);
      font-size: 12px;
      color: var(--accent-bright);
    }
  }
}

// =====================================================================
// 响应式:窄屏(<768px)只显示右卡片(hero 隐藏;补弱底色避免毛玻璃浮空)
// =====================================================================
@media (max-width: 768px) {
  .login-page {
    grid-template-columns: 1fr;
  }

  .login-hero {
    display: none;
  }

  .login-form-wrap {
    min-height: 100vh;
    background:
      radial-gradient(circle at 50% 25%, color-mix(in srgb, var(--accent) 8%, transparent), transparent 60%),
      var(--bg-base);
  }
}

// =====================================================================
// reduced-motion 局部守卫:禁用 hero 专属动效(login-aura / login-float)
// 注:_motion.scss 已全局兜底 [data-stagger]/.aurora-bg/.shimmer,
//     本块补本页独立的 login-aura / login-float。
// =====================================================================
@media (prefers-reduced-motion: reduce) {
  .login-hero__aura,
  .login-hero__chip {
    animation: none !important;
  }
}
</style>

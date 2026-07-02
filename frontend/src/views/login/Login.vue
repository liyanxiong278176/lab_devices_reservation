<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { useUserStore } from '@/stores/user'

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
</script>

<template>
  <main class="login-page">
    <div class="lab-card login-card">
      <div class="login-card__head">
        <h1 class="login-card__title">实验室预约系统</h1>
        <p class="login-card__subtitle">登录以继续</p>
      </div>

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

        <el-button
          type="primary"
          class="login-card__submit"
          :loading="loading"
          @click="onSubmit"
        >
          登录
        </el-button>
      </el-form>
    </div>
  </main>
</template>

<style scoped lang="scss">
.login-page {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  padding: 24px;
  background: var(--el-bg-color-page); // surface-soft #f8f9fa
}

.login-card {
  width: 100%;
  max-width: 400px;
  padding: 40px;

  &__head {
    margin-bottom: 24px;
  }

  &__title {
    margin: 0;
    font-size: 28px; // display-sm
    font-weight: 600;
    line-height: 1.2;
    letter-spacing: -0.5px;
    color: var(--el-text-color-primary); // #111111
  }

  &__subtitle {
    margin: 8px 0 0;
    font-size: 14px;
    color: var(--el-text-color-secondary); // #6b7280
  }

  &__submit {
    width: 100%;
    margin-top: 8px;
  }
}
</style>

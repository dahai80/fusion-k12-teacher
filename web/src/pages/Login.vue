<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NCard, NTabs, NTabPane, NForm, NFormItem, NInput, NButton, NSpace, useMessage } from 'naive-ui'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()
const message = useMessage()
const tab = ref('login')
const loginForm = reactive({ username: '', password: '' })
const regForm = reactive({
  username: '', password: '', password2: '',
  name: '', school: '', region: '', default_edition: 'renjiao',
})
const loading = ref(false)

const editions = [
  { label: '人教版', value: 'renjiao' },
]

async function doLogin() {
  if (!loginForm.username || !loginForm.password) {
    message.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    await auth.login(loginForm.username, loginForm.password)
    message.success('登录成功')
    router.push('/dashboard')
  } catch (e: any) {
    message.error('登录失败: ' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

async function doRegister() {
  if (!regForm.username || !regForm.password) {
    message.warning('请输入用户名和密码')
    return
  }
  if (regForm.password !== regForm.password2) {
    message.warning('两次密码不一致')
    return
  }
  loading.value = true
  try {
    await auth.register({
      username: regForm.username, password: regForm.password,
      name: regForm.name, school: regForm.school, region: regForm.region,
      default_edition: regForm.default_edition,
    })
    message.success('注册成功, 已自动登录')
    router.push('/dashboard')
  } catch (e: any) {
    message.error('注册失败: ' + (e?.message || e))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div style="display: flex; justify-content: center; align-items: center; min-height: 80vh; padding: 20px">
    <n-card style="width: 420px" size="medium">
      <div style="text-align: center; font-weight: 700; font-size: 18px; margin-bottom: 16px">
        Fusion K12 教师助手
      </div>
      <n-tabs v-model:value="tab" type="line">
        <n-tab-pane name="login" tab="登录">
          <n-form label-placement="top" :show-feedback="false" size="medium">
            <n-form-item label="用户名"><n-input v-model:value="loginForm.username" placeholder="用户名" /></n-form-item>
            <n-form-item label="密码" style="margin-top: 12px"><n-input v-model:value="loginForm.password" type="password" show-password-on="click" placeholder="密码" @keyup.enter="doLogin" /></n-form-item>
            <n-button type="primary" block :loading="loading" style="margin-top: 16px" @click="doLogin">登录</n-button>
          </n-form>
        </n-tab-pane>
        <n-tab-pane name="register" tab="注册">
          <n-form label-placement="top" :show-feedback="false" size="medium">
            <n-form-item label="用户名"><n-input v-model:value="regForm.username" placeholder="用户名 (≥2位)" /></n-form-item>
            <n-form-item label="密码" style="margin-top: 8px"><n-input v-model:value="regForm.password" type="password" show-password-on="click" placeholder="密码 (≥6位)" /></n-form-item>
            <n-form-item label="确认密码" style="margin-top: 8px"><n-input v-model:value="regForm.password2" type="password" show-password-on="click" placeholder="再次输入密码" /></n-form-item>
            <n-form-item label="姓名" style="margin-top: 8px"><n-input v-model:value="regForm.name" placeholder="如: 王老师" /></n-form-item>
            <n-form-item label="学校" style="margin-top: 8px"><n-input v-model:value="regForm.school" placeholder="如: 深圳实验学校" /></n-form-item>
            <n-form-item label="地区" style="margin-top: 8px"><n-input v-model:value="regForm.region" placeholder="如: 深圳" /></n-form-item>
            <n-form-item label="默认教材版本" style="margin-top: 8px">
              <n-select v-model:value="regForm.default_edition" :options="editions" />
            </n-form-item>
            <n-button type="primary" block :loading="loading" style="margin-top: 16px" @click="doRegister">注册</n-button>
          </n-form>
        </n-tab-pane>
      </n-tabs>
    </n-card>
  </div>
</template>

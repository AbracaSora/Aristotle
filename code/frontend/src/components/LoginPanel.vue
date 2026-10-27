<script setup lang="ts">
import { ref } from "vue";
import { NButton, NInput } from "naive-ui";
import { Layers, ArrowRight } from "lucide-vue-next";
defineProps<{ loading: boolean }>();
const emit = defineEmits<{ login: [username: string, password: string] }>();
const username = ref("student1"),
  password = ref("demo-password");
</script>

<template>
  <main class="login-layout">
    <section class="login-intro">
      <div class="brand">
        <span class="brand-icon"><Layers :size="23" /></span
        ><span>Aristotle<small>408 · LEARNING STUDIO</small></span>
      </div>
      <span class="eyebrow">ONE STEP AT A TIME</span>
      <h1>让每一步学习，<br />都有方向。</h1>
      <p>从已有的知识出发，通过作答了解薄弱点，再找到下一步练习。</p>
      <p class="muted">
        当前为数据结构学习原型。演示题库尚未完成正式审核，诊断采用可解释规则基线。
      </p>
    </section>
    <section class="panel login-card">
      <span class="eyebrow">YOUR LEARNING SPACE</span>
      <h2>进入学习空间</h2>
      <p class="muted">
        使用分配的账号登录，作答、资料和进度将保存在学习服务中。
      </p>
      <form @submit.prevent="emit('login', username.trim(), password)">
        <label class="field"
          >账号<NInput
            v-model:value="username"
            name="username"
            autocomplete="username"
            :disabled="loading"
            placeholder="请输入账号"
        /></label>
        <label class="field"
          >密码<NInput
            v-model:value="password"
            name="password"
            type="password"
            autocomplete="current-password"
            show-password-on="click"
            :disabled="loading"
            placeholder="请输入密码"
        /></label>
        <NButton
          attr-type="submit"
          type="primary"
          size="large"
          block
          :loading="loading"
          :disabled="!username.trim() || !password"
          >进入学习空间<template #icon><ArrowRight :size="17" /></template
        ></NButton>
      </form>
      <div class="login-demo">
        <p class="muted">本地演示账号 · 密码 demo-password</p>
        <div class="actions">
          <NButton
            size="small"
            secondary
            :disabled="loading"
            @click="username = 'student1'"
            >学生一</NButton
          ><NButton
            size="small"
            secondary
            :disabled="loading"
            @click="username = 'student2'"
            >学生二</NButton
          ><NButton
            size="small"
            quaternary
            :disabled="loading"
            @click="username = 'editor'"
            >内容维护者</NButton
          >
        </div>
      </div>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { NConfigProvider, NButton, NTag, NProgress, NModal, NRadioGroup, NRadio, NAlert, NInput, NEmpty, NPopconfirm, zhCN } from 'naive-ui'
import { Layers, LayoutDashboard, Network, Library, History, ArrowRight, ArrowUpRight, Check, Sparkles, Clock3, BookOpen } from 'lucide-vue-next'
const theme = { common: { primaryColor: '#208064', primaryColorHover: '#176b53', primaryColorPressed: '#125640', successColor: '#208064', borderRadius: '9px' } }
const nav = [{ name: '学习概览', icon: LayoutDashboard }, { name: '知识地图', icon: Network }, { name: '我的资料', icon: Library }, { name: '学习记录', icon: History }]
const page = ref('学习概览')
const questions = [
  { id: 's1', text: '依次将 1、2、3 入栈，连续出栈两次。第二次出栈的元素是？', options: ['1', '2', '3'], answer: '2', explanation: '栈遵循后进先出，第一次弹出 3，第二次弹出 2。' },
  { id: 's2', text: '执行 push(A)、push(B)、pop()、push(C) 后，栈顶元素是？', options: ['A', 'B', 'C'], answer: 'C', explanation: 'B 被弹出后，C 入栈成为新的栈顶，A 仍在栈底。' },
  { id: 's3', text: '空栈执行 push(4)、pop()、push(6)、push(8)、pop() 后，剩下哪个元素？', options: ['4', '6', '8'], answer: '6', explanation: '4 和 8 先后被弹出，栈中只剩下 6。' },
]
type Attempt = { id: string; correct: boolean; at: string }
type Material = { id: number; title: string; text: string; confirmed: boolean }
function load<T>(key: string, fallback: T): T { try { const raw = localStorage.getItem(key); const value = raw ? JSON.parse(raw) : fallback; return Array.isArray(value) ? value as T : fallback } catch { return fallback } }
const attempts = ref<Attempt[]>(load('aristotle-demo-attempts', []))
const materials = ref<Material[]>(load('aristotle-demo-materials', []))
const warning = ref('')
function save() { try { localStorage.setItem('aristotle-demo-attempts', JSON.stringify(attempts.value)); localStorage.setItem('aristotle-demo-materials', JSON.stringify(materials.value)) } catch { warning.value = '本地存储不可用，本次记录仅保留到页面关闭。' } }
const evidence = computed(() => new Set(attempts.value.map(a => a.id)).size)
const quizOpen = ref(false), index = ref(0), selected = ref<string | null>(null), submitted = ref(false), finished = ref(false), score = ref(0)
const question = computed(() => questions[index.value]!)
function start() { index.value = 0; selected.value = null; submitted.value = false; finished.value = false; score.value = 0; quizOpen.value = true }
function submit() { if (!selected.value || submitted.value) return; const correct = selected.value === question.value.answer; attempts.value.unshift({ id: question.value.id, correct, at: new Date().toISOString() }); if (correct) score.value++; submitted.value = true; save() }
function next() { if (index.value === questions.length - 1) { finished.value = true; return } index.value++; selected.value = null; submitted.value = false }
const materialOpen = ref(false), title = ref(''), content = ref('')
function add() { if (!title.value.trim() || !content.value.trim()) return; materials.value.unshift({ id: Date.now(), title: title.value.trim(), text: content.value.trim(), confirmed: false }); save(); title.value = ''; content.value = ''; materialOpen.value = false }
function remove(id: number) { materials.value = materials.value.filter(m => m.id !== id); save() }
const date = new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' }).format(new Date())
</script>

<template>
  <NConfigProvider :theme-overrides="theme" :locale="zhCN">
    <div class="shell">
      <aside class="sidebar">
        <a href="#" class="brand" @click.prevent="page = '学习概览'"><span class="brand-icon"><Layers :size="23" /></span><span>Aristotle<small>408 · LEARNING STUDIO</small></span></a>
        <p class="nav-label">我的学习空间</p>
        <nav aria-label="主导航"><button v-for="item in nav" :key="item.name" :class="['nav-link', { active: page === item.name }]" @click="page = item.name"><component :is="item.icon" :size="19" /><span>{{ item.name }}</span></button></nav>
        <div class="sidebar-note"><span class="eyebrow">ONE STEP AT A TIME</span><p>每一次理解，<br />都让知识更进一步。</p><span>从数据结构开始。</span></div>
        <div class="profile"><span class="avatar">A</span><div><strong>访客学习空间</strong><small>本地演示 · 无需登录</small></div></div>
      </aside>
      <div class="workspace">
        <header class="topbar"><span>学习空间 <span class="separator">/</span> {{ page }}</span><span>● &nbsp; 数据结构 · 首版探索</span></header>
        <main>
          <NAlert v-if="warning" type="warning" class="notice">{{ warning }}</NAlert>
          <div class="heading"><div><p class="eyebrow">{{ date }} <span> / YOUR LEARNING JOURNEY</span></p><h1>{{ page === '学习概览' ? '让每一步学习，都有方向。' : page }}</h1><p class="subtitle">发现知识缺口，完成一小关，再向前一步。</p></div><NTag :bordered="false" size="large">当前范围：栈与队列</NTag></div>
          <template v-if="page === '学习概览'">
            <div class="overview">
              <section class="hero"><div class="hero-copy"><span class="pill"><Sparkles :size="14" /> 今日学习建议</span><h2>理解栈的规则，<br />再试着推演一次。</h2><p>{{ evidence < 3 ? '目前作答证据还不足。先完成 3 道应用题，了解自己在哪些步骤需要巩固。' : '已经完成一轮样例练习。回顾操作步骤，之后通过新的独立题目检验理解。' }}</p><div class="actions"><NButton type="primary" size="large" @click="start">开始短关卡 <template #icon><ArrowRight :size="17" /></template></NButton><span>3 道题 · 约 5 分钟</span></div></div><div class="art" aria-hidden="true"><div class="orbit"></div><span class="art-label">INPUT → UNDERSTAND</span><div class="slab one">03 <span>应用</span></div><div class="slab two">02 <span>理解</span></div><div class="slab three">01 <span>记忆</span></div><span class="star">✳</span><span class="art-caption">BUILD YOUR KNOWLEDGE</span></div></section>
              <section class="panel progress-panel"><h3>本轮学习证据</h3><NProgress type="circle" :percentage="Math.round(evidence / 3 * 100)" :stroke-width="7" color="#49ba94" rail-color="#e6f6ee"><div class="ring"><strong>{{ evidence }}<small>/ 3</small></strong><span>不同题目</span></div></NProgress><p>{{ evidence < 3 ? '再积累一些作答证据' : '已完成本轮样例题' }}</p><span class="muted">练习完成度不等于知识掌握度</span><div class="progress-footer"><span>目标认知活动</span><NTag type="success" size="small" :bordered="false">应用</NTag></div></section>
            </div>
            <div class="stats"><div><BookOpen :size="21"/><span>累计作答<strong>{{ attempts.length }} <small>次</small></strong></span></div><div><Check :size="21"/><span>正确作答<strong>{{ attempts.filter(a => a.correct).length }} <small>次</small></strong></span></div><div><Library :size="21"/><span>已确认资料<strong>{{ materials.filter(m => m.confirmed).length }} <small>份</small></strong></span></div></div>
            <div class="lower"><section><div class="section-heading"><div><span class="eyebrow">NEXT STEPS</span><h2>接下来，学一点什么？</h2></div><NButton text @click="page = '知识地图'">知识地图 <template #icon><ArrowUpRight :size="16"/></template></NButton></div><article class="task"><span class="task-icon"><Layers :size="24"/></span><div><div class="tags"><NTag size="small" type="success" :bordered="false">应用</NTag><span>公共样例题 · 无需上传资料</span></div><h3>栈与队列 · 操作推演</h3><p>在给定情境中执行规则，观察每一步状态变化。</p><span class="task-meta"><Clock3 :size="13"/>约 5 分钟 · 3 道客观题</span></div><NButton circle aria-label="开始操作推演" @click="start"><template #icon><ArrowRight :size="18"/></template></NButton></article><article class="material-callout"><BookOpen :size="24"/><div><h3>让自己的讲义也参与学习</h3><p>粘贴一段笔记，确认对应的知识点。</p></div><NButton secondary @click="page = '我的资料'">整理资料</NButton></article></section><section class="panel cognitive"><span class="eyebrow">LEARN WITH INTENTION</span><h3>不只知道答案，<br/>也知道在练什么。</h3><div v-for="(label, i) in ['记忆：识别概念与事实', '理解：解释知识的含义', '应用：在情境中执行方法', '分析：辨别结构与关系']" :key="label" :class="['cognitive-row', { highlighted: i === 2 }]"><span>0{{ i + 1 }}</span>{{ label }}</div><p>标签描述题目要求的认知活动，<br/>不代表你的总体能力等级。</p></section></div>
          </template>
          <template v-else-if="page === '知识地图'"><NAlert type="info" class="notice">以下为先修路径示例，正式诊断与推荐尚未接入后端。</NAlert><div class="cards"><article v-for="(name, i) in ['线性结构基础', '线性表', '栈与队列']" :key="name" class="panel"><span class="eyebrow">CHAPTER 0{{ i + 1 }}</span><h2>{{ name }}</h2><NTag :bordered="false">{{ i === 2 ? evidence + ' 道题目证据' : '证据不足' }}</NTag><p class="description">{{ i === 0 ? '理解元素间的一对一关系。' : '先修：' + (i === 1 ? '线性结构基础' : '线性表') }}</p><NButton v-if="i === 2" secondary @click="start">开始应用练习</NButton><span v-else class="muted">此章节题库尚未开放</span></article></div></template>
          <template v-else-if="page === '我的资料'"><div class="section-heading"><p class="subtitle">内容仅保存在当前浏览器，不发送到外部模型。</p><NButton type="primary" @click="materialOpen = true">添加文字讲义</NButton></div><NAlert class="notice" type="info">当前支持粘贴文本并手动确认关联。PDF 抽取和智能关联将在接入后端后提供。</NAlert><NEmpty v-if="!materials.length" description="还没有资料，添加一段笔记开始整理" class="empty"/><div class="cards"><article v-for="m in materials" :key="m.id" class="panel"><NTag :type="m.confirmed ? 'success' : 'warning'">{{ m.confirmed ? '已确认关联' : '待确认关联' }}</NTag><h3 class="material-title">{{ m.title }}</h3><p class="material-text">{{ m.text }}</p><p class="muted">知识点：栈与队列 · 来源：粘贴文本第 1 段</p><div class="actions"><NButton size="small" @click="m.confirmed = !m.confirmed; save()">{{ m.confirmed ? '取消关联' : '确认关联' }}</NButton><NPopconfirm @positive-click="remove(m.id)"><template #trigger><NButton quaternary type="error" size="small">删除</NButton></template>删除这份本地讲义？</NPopconfirm></div></article></div></template>
          <template v-else><NAlert type="info" class="notice">同题重复作答保留历史，只计为一道不同题目的证据。本地样例记录不构成正式知识诊断。</NAlert><NEmpty v-if="!attempts.length" description="完成第一道题后，记录会出现在这里" class="empty"/><section v-else class="panel"><article v-for="(a, i) in attempts" :key="i" class="history-row"><span class="task-icon"><History :size="20"/></span><div><h3>栈操作推演 · {{ a.id }}</h3><p>{{ new Date(a.at).toLocaleString('zh-CN') }} · 样例版本 v1</p></div><NTag :type="a.correct ? 'success' : 'warning'" :bordered="false">{{ a.correct ? '回答正确' : '需要巩固' }}</NTag></article></section></template>
          <footer><span>ARISTOTLE 408 <span class="separator">/</span> 学习是一个逐渐清晰的过程。</span><span>前端演示 · 样例题尚非正式审核题库</span></footer>
        </main>
      </div>
    </div>
    <NModal v-model:show="quizOpen" preset="card" title="应用练习 · 短关卡" class="dialog" :mask-closable="false"><template v-if="!finished"><div class="quiz-top"><NTag type="success" :bordered="false">应用 · 按规则执行操作</NTag><span>{{ index + 1 }} / 3</span></div><h2 class="question">{{ question.text }}</h2><NRadioGroup v-model:value="selected" :disabled="submitted" class="answers"><NRadio v-for="option in question.options" :key="option" :value="option">{{ option }}</NRadio></NRadioGroup><NAlert v-if="submitted" class="feedback" :type="selected === question.answer ? 'success' : 'warning'" :title="selected === question.answer ? '回答正确' : '正确答案：' + question.answer">{{ question.explanation }} 单题结果仅作为一条作答证据。</NAlert><div class="dialog-actions"><NButton v-if="!submitted" type="primary" :disabled="!selected" @click="submit">提交答案</NButton><NButton v-else type="primary" @click="next">{{ index === 2 ? '查看反馈' : '下一题' }}</NButton></div></template><div v-else class="completion"><Check :size="38"/><h2>完成了一小步。</h2><p>本轮答对 {{ score }} / 3 道题。</p><p>{{ score === 3 ? '尝试复述每个操作步骤，之后使用新题检验迁移。' : '建议回顾出错步骤，先巩固后进先出的操作规则。' }}</p><NButton type="primary" @click="quizOpen = false; page = '学习记录'">查看学习记录</NButton></div></NModal>
    <NModal v-model:show="materialOpen" preset="card" title="添加文字讲义" class="dialog"><label class="field">标题<NInput v-model:value="title" maxlength="80" placeholder="例如：栈的基本操作"/></label><label class="field">讲义正文<NInput v-model:value="content" type="textarea" :rows="7" :maxlength="20000" show-count placeholder="粘贴与栈和队列有关的笔记…"/></label><p class="muted">保存后请确认是否关联到「栈与队列」。讲义仅存储在本浏览器。</p><NButton type="primary" :disabled="!title.trim() || !content.trim()" @click="add">保存讲义</NButton></NModal>
  </NConfigProvider>
</template>

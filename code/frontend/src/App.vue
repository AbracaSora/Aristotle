<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import {
  NConfigProvider,
  NButton,
  NTag,
  NProgress,
  NAlert,
  NEmpty,
  NPopconfirm,
  NSelect,
  zhCN,
} from "naive-ui";
import {
  Layers,
  LayoutDashboard,
  Network,
  Library,
  History,
  ArrowRight,
  ArrowUpRight,
  Check,
  Sparkles,
  Clock3,
  BookOpen,
  LogOut,
  RefreshCw,
} from "lucide-vue-next";
import LoginPanel from "./components/LoginPanel.vue";
import QuizDialog from "./components/QuizDialog.vue";
import MaterialDialog from "./components/MaterialDialog.vue";
import { useLearning } from "./useLearning";
import { levelLabels, levelDescriptions, stateLabels } from "./types";
import type { Material } from "./types";
const theme = {
  common: {
    primaryColor: "#208064",
    primaryColorHover: "#176b53",
    primaryColorPressed: "#125640",
    successColor: "#208064",
    borderRadius: "9px",
  },
};
const nav = [
  { name: "学习概览", icon: LayoutDashboard },
  { name: "知识地图", icon: Network },
  { name: "我的资料", icon: Library },
  { name: "学习记录", icon: History },
];
const learning = useLearning();
const {
  user,
  graph,
  state,
  history,
  materials,
  task,
  error,
  busy,
  submitting,
  mutating,
  pendingSubmission,
  hasPendingTask,
} = learning;
const page = ref("学习概览"),
  quizOpen = ref(false),
  materialOpen = ref(false);
const focus = computed(
  () =>
    state.value?.states.find(
      (s) => s.knowledge_id === task.value?.knowledge_id,
    ) || state.value?.states[0],
);
const targetLevel = computed(() => task.value?.target_level);
const knowledgeOptions = computed(() =>
  (graph.value?.nodes || []).map((node) => ({
    label: node.name,
    value: node.id,
  })),
);
function knowledgeName(id: string) {
  return graph.value?.nodes.find((node) => node.id === id)?.name || id;
}
async function start(force = false, knowledgeId?: string) {
  if (submitting.value || busy.value) return;
  if (!force && !knowledgeId && hasPendingTask.value) {
    quizOpen.value = true;
    return;
  }
  if (await learning.requestTask(knowledgeId)) quizOpen.value = true;
}
async function add(title: string, text: string, knowledgeId: string) {
  if (await learning.addMaterial(title, text, knowledgeId))
    materialOpen.value = false;
}
function updateAssociation(material: Material, id: string) {
  return learning.updateMaterial(material, id, false);
}
watch(
  () => user.value?.id,
  () => {
    quizOpen.value = false;
    materialOpen.value = false;
    page.value = "学习概览";
  },
);
onMounted(learning.restore);
const date = new Intl.DateTimeFormat("zh-CN", {
  month: "long",
  day: "numeric",
  weekday: "long",
}).format(new Date());
</script>

<template>
  <NConfigProvider :theme-overrides="theme" :locale="zhCN">
    <template v-if="!user">
      <NAlert v-if="error" type="warning" class="login-error" role="alert">{{
        error
      }}</NAlert>
      <LoginPanel :loading="busy" @login="learning.login" />
    </template>
    <div v-else class="shell">
      <aside class="sidebar">
        <a href="#" class="brand" @click.prevent="page = '学习概览'"
          ><span class="brand-icon"><Layers :size="23" /></span
          ><span>Aristotle<small>408 · LEARNING STUDIO</small></span></a
        >
        <p class="nav-label">我的学习空间</p>
        <nav aria-label="主导航">
          <button
            v-for="item in nav"
            :key="item.name"
            :class="['nav-link', { active: page === item.name }]"
            @click="page = item.name"
          >
            <component :is="item.icon" :size="19" /><span>{{ item.name }}</span>
          </button>
        </nav>
        <div class="sidebar-note">
          <span class="eyebrow">ONE STEP AT A TIME</span>
          <p>每一次理解，<br />都让知识更进一步。</p>
          <span>从数据结构开始。</span>
        </div>
        <div class="profile">
          <span class="avatar">{{ user.username[0]?.toUpperCase() }}</span>
          <div>
            <strong>{{ user.username }}</strong
            ><small>{{
              user.role === "student" ? "学习进度已连接" : "内容维护者"
            }}</small>
          </div>
          <NButton
            quaternary
            circle
            aria-label="退出登录"
            :disabled="busy || submitting || mutating"
            @click="learning.logout"
            ><template #icon><LogOut :size="16" /></template
          ></NButton>
        </div>
      </aside>
      <div class="workspace">
        <header class="topbar">
          <span>学习空间 <span class="separator">/</span> {{ page }}</span>
          <div class="actions">
            <span>● &nbsp; 数据结构 · 演示范围</span
            ><NButton
              text
              size="small"
              :disabled="busy || submitting || mutating"
              @click="learning.logout"
              >退出 / 切换账号</NButton
            >
          </div>
        </header>
        <main>
          <NAlert v-if="error" type="warning" class="notice" role="alert">{{
            error
          }}</NAlert>
          <template v-if="user.role === 'maintainer'"
            ><section class="panel">
              <h1>内容维护者空间</h1>
              <p class="subtitle">
                此账号用于管理公共题目。学习页面需要学生账号，私人资料与作答保持账号隔离。
              </p>
              <div class="actions" style="margin-top: 24px">
                <NButton
                  tag="a"
                  href="/backend-demo"
                  target="_blank"
                  type="primary"
                  >打开内容管理工作台</NButton
                ><NButton :disabled="busy" @click="learning.logout"
                  >切换学生账号</NButton
                >
              </div>
            </section></template
          >
          <template v-else>
            <div class="heading">
              <div>
                <p class="eyebrow">
                  {{ date }} <span> / YOUR LEARNING JOURNEY</span>
                </p>
                <h1>
                  {{ page === "学习概览" ? "让每一步学习，都有方向。" : page }}
                </h1>
                <p class="subtitle">发现知识缺口，完成一小关，再向前一步。</p>
              </div>
              <NButton secondary :loading="busy" @click="learning.refresh"
                ><template #icon><RefreshCw :size="15" /></template
                >刷新学习状态</NButton
              >
            </div>
            <NAlert v-if="!state" type="info" class="notice">{{
              busy
                ? "正在读取学习数据…"
                : "尚未取得学习数据，请确认服务可用后刷新。"
            }}</NAlert>
            <template v-if="page === '学习概览'">
              <div class="overview">
                <section class="hero">
                  <div class="hero-copy">
                    <span class="pill"
                      ><Sparkles :size="14" />
                      {{ hasPendingTask ? "继续上次学习" : "找到下一步" }}</span
                    >
                    <h2>
                      {{ hasPendingTask ? "继续这一小关，" : "从你的起点，"
                      }}<br />{{
                        hasPendingTask ? "再积累一点证据。" : "找到下一步学习。"
                      }}
                    </h2>
                    <p>
                      {{
                        hasPendingTask && task
                          ? task.reason
                          : "根据当前知识状态、先修关系与认知维度证据，为你安排下一次学习任务。"
                      }}
                    </p>
                    <div class="actions">
                      <NButton
                        type="primary"
                        size="large"
                        :disabled="!state"
                        :loading="busy"
                        @click="start()"
                        >{{ hasPendingTask ? "继续短关卡" : "获取学习任务"
                        }}<template #icon
                          ><ArrowRight :size="17" /></template></NButton
                      ><span>{{
                        task ? knowledgeName(task.knowledge_id) : "无需上传资料"
                      }}</span>
                    </div>
                  </div>
                  <div class="art" aria-hidden="true">
                    <div class="orbit"></div>
                    <span class="art-label">INPUT → UNDERSTAND</span>
                    <div class="slab one">03 <span>应用</span></div>
                    <div class="slab two">02 <span>理解</span></div>
                    <div class="slab three">01 <span>记忆</span></div>
                    <span class="star">✳</span
                    ><span class="art-caption">BUILD YOUR KNOWLEDGE</span>
                  </div>
                </section>
                <section class="panel progress-panel">
                  <h3>{{ focus?.name || "学习证据" }}</h3>
                  <NProgress
                    type="circle"
                    :percentage="
                      Math.min(
                        Math.round(((focus?.evidence_count || 0) / 3) * 100),
                        100,
                      )
                    "
                    :stroke-width="7"
                    color="#49ba94"
                    rail-color="#e6f6ee"
                    ><div class="ring">
                      <strong>{{ focus?.evidence_count || 0 }}</strong
                      ><span>近期不同题目</span>
                    </div></NProgress
                  >
                  <p>
                    {{ focus ? stateLabels[focus.status] : "等待学习数据" }}
                  </p>
                  <span class="muted"
                    >至少 3 题是最低证据条件，题量不等于掌握度</span
                  >
                  <div class="progress-footer">
                    <span>任务认知活动</span
                    ><NTag type="success" size="small" :bordered="false">{{
                      targetLevel ? levelLabels[targetLevel] : "等待推荐"
                    }}</NTag>
                  </div>
                </section>
              </div>
              <div class="stats">
                <div>
                  <BookOpen :size="21" /><span
                    >累计作答<strong
                      >{{ history.total }} <small>次</small></strong
                    ></span
                  >
                </div>
                <div>
                  <Check :size="21" /><span
                    >正确作答<strong
                      >{{ history.correct_total }} <small>次</small></strong
                    ></span
                  >
                </div>
                <div>
                  <Library :size="21" /><span
                    >已确认资料<strong
                      >{{ materials.filter((m) => m.confirmed).length }}
                      <small>份</small></strong
                    ></span
                  >
                </div>
              </div>
              <div class="lower">
                <section>
                  <div class="section-heading">
                    <div>
                      <span class="eyebrow">NEXT STEPS</span>
                      <h2>接下来，学一点什么？</h2>
                    </div>
                    <NButton text @click="page = '知识地图'"
                      >知识地图<template #icon
                        ><ArrowUpRight :size="16" /></template
                    ></NButton>
                  </div>
                  <article class="task">
                    <span class="task-icon"><Layers :size="24" /></span>
                    <div>
                      <div class="tags">
                        <NTag size="small" type="success" :bordered="false">{{
                          targetLevel ? levelLabels[targetLevel] : "规则推荐"
                        }}</NTag
                        ><span>公共演示题 · 无需上传资料</span>
                      </div>
                      <h3>
                        {{
                          task
                            ? knowledgeName(task.knowledge_id)
                            : "获取下一次学习任务"
                        }}
                      </h3>
                      <p>
                        {{
                          targetLevel
                            ? levelDescriptions[targetLevel]
                            : "从已发布内容中，选择当前适合学习的任务。"
                        }}
                      </p>
                      <span class="task-meta"
                        ><Clock3 :size="13" />{{
                          task
                            ? task.questions.length + " 道客观题"
                            : "短关卡 · 明确认知目标"
                        }}</span
                      >
                    </div>
                    <NButton
                      circle
                      aria-label="开始学习任务"
                      :loading="busy"
                      :disabled="!state"
                      @click="start()"
                      ><template #icon><ArrowRight :size="18" /></template
                    ></NButton>
                  </article>
                  <article class="material-callout">
                    <BookOpen :size="24" />
                    <div>
                      <h3>让自己的讲义也参与学习</h3>
                      <p>粘贴一段笔记，确认对应的知识点。</p>
                    </div>
                    <NButton secondary @click="page = '我的资料'"
                      >整理资料</NButton
                    >
                  </article>
                </section>
                <section class="panel cognitive">
                  <span class="eyebrow">LEARN WITH INTENTION</span>
                  <h3>不只知道答案，<br />也知道在练什么。</h3>
                  <div
                    v-for="(level, i) in [
                      'remember',
                      'understand',
                      'apply',
                      'analyze',
                    ] as const"
                    :key="level"
                    :class="[
                      'cognitive-row',
                      { highlighted: targetLevel === level },
                    ]"
                  >
                    <span>0{{ i + 1 }}</span
                    >{{ levelLabels[level] }}：{{ levelDescriptions[level] }}
                  </div>
                  <p>
                    标签描述题目要求的认知活动，<br />不代表你的总体能力等级。
                  </p>
                </section>
              </div>
            </template>
            <template v-else-if="page === '知识地图'">
              <NAlert type="info" class="notice"
                >状态来自最近
                {{
                  state?.window_days || 14
                }}
                天的有效作答。先修满足且证据充分后，才能标记初步掌握；当前使用规则基线。</NAlert
              >
              <div class="cards">
                <article
                  v-for="(node, i) in graph?.nodes || []"
                  :key="node.id"
                  class="panel"
                >
                  <span class="eyebrow">KNOWLEDGE 0{{ i + 1 }}</span>
                  <h2>{{ node.name }}</h2>
                  <template
                    v-for="item in state?.states.filter(
                      (s) => s.knowledge_id === node.id,
                    ) || []"
                    :key="item.knowledge_id"
                    ><NTag
                      :type="
                        item.status === 'provisional' ? 'success' : 'warning'
                      "
                      :bordered="false"
                      >{{ stateLabels[item.status] }}</NTag
                    >
                    <p class="description">
                      先修：{{
                        node.prerequisites.length
                          ? node.prerequisites.map(knowledgeName).join("、")
                          : "无"
                      }}<br />{{ item.evidence_count }} 道有效题 · 正确率
                      {{
                        item.correct_rate === null
                          ? "暂无"
                          : Math.round(item.correct_rate * 100) + "%"
                      }}
                    </p>
                    <div class="evidence-list">
                      <div v-for="c in item.cognitive" :key="c.level">
                        <span>{{ levelLabels[c.level] }}</span
                        ><span
                          >{{ c.count }} 题 ·
                          {{
                            c.evidence_status === "insufficient"
                              ? "证据不足"
                              : Math.round((c.correct_rate || 0) * 100) + "%"
                          }}</span
                        >
                      </div>
                    </div>
                    <p v-if="item.unmet_prerequisites.length" class="muted">
                      待补先修：{{
                        item.unmet_prerequisites.map(knowledgeName).join("、")
                      }}
                    </p>
                    <NButton
                      secondary
                      :disabled="busy || !!item.unmet_prerequisites.length"
                      @click="start(true, node.id)"
                      >获取此知识点任务</NButton
                    ></template
                  >
                </article>
              </div>
            </template>
            <template v-else-if="page === '我的资料'">
              <div class="section-heading">
                <p class="subtitle">资料保存在学习服务中，仅当前账号可访问。</p>
                <NButton
                  type="primary"
                  :disabled="!graph || mutating"
                  @click="materialOpen = true"
                  >添加文字讲义</NButton
                >
              </div>
              <NAlert class="notice" type="info"
                >当前支持粘贴文字并手动确认关联，内容不会发送给外部模型。PDF
                抽取与自动关联尚未实现。</NAlert
              >
              <NEmpty
                v-if="!materials.length"
                description="还没有资料，添加一段笔记开始整理"
                class="empty"
              />
              <div class="cards">
                <article v-for="m in materials" :key="m.id" class="panel">
                  <NTag :type="m.confirmed ? 'success' : 'warning'">{{
                    m.confirmed ? "已确认关联" : "待确认关联"
                  }}</NTag>
                  <h3 class="material-title">{{ m.title }}</h3>
                  <p class="material-text">{{ m.text }}</p>
                  <label class="field"
                    >关联知识点<NSelect
                      :value="m.knowledge_id"
                      :options="knowledgeOptions"
                      :disabled="mutating"
                      @update:value="(id) => updateAssociation(m, String(id))"
                  /></label>
                  <p class="muted">
                    来源：{{ m.source_location
                    }}<br />改变知识点后需要重新确认关联。
                  </p>
                  <div class="actions">
                    <NButton
                      size="small"
                      :disabled="mutating"
                      @click="
                        learning.updateMaterial(m, m.knowledge_id, !m.confirmed)
                      "
                      >{{ m.confirmed ? "取消关联" : "确认关联" }}</NButton
                    ><NPopconfirm
                      @positive-click="learning.removeMaterial(m.id)"
                      ><template #trigger
                        ><NButton
                          quaternary
                          type="error"
                          size="small"
                          :disabled="mutating"
                          >删除</NButton
                        ></template
                      >删除这份讲义及后续引用？</NPopconfirm
                    >
                  </div>
                </article>
              </div>
            </template>
            <template v-else>
              <NAlert type="info" class="notice"
                >同题重复练习保留历史；最近窗口内只取首次有效作答计入诊断。以下已显示
                {{ history.items.length }} /
                {{ history.total }} 条记录。</NAlert
              >
              <NEmpty
                v-if="!history.items.length"
                description="完成第一道题后，记录会出现在这里"
                class="empty"
              />
              <section v-else class="panel">
                <article
                  v-for="a in history.items"
                  :key="a.id"
                  class="history-row"
                >
                  <span class="task-icon"><History :size="20" /></span>
                  <div>
                    <h3>{{ a.question_key }} · {{ levelLabels[a.level] }}</h3>
                    <p>
                      {{
                        new Date(a.created_at * 1000).toLocaleString("zh-CN")
                      }}
                      · 题目版本 v{{ a.question_version
                      }}{{
                        a.content_status === "retired"
                          ? " · 已停用，不计入当前诊断"
                          : ""
                      }}
                    </p>
                    <details class="history-details">
                      <summary>查看本次作答</summary>
                      <p>
                        你的选项：{{ a.selected }}<br />正确答案：{{ a.answer
                        }}<br />{{ a.explanation }}
                      </p>
                    </details>
                  </div>
                  <NTag
                    :type="a.correct ? 'success' : 'warning'"
                    :bordered="false"
                    >{{ a.correct ? "回答正确" : "需要巩固" }}</NTag
                  >
                </article>
                <NButton
                  v-if="history.items.length < history.total"
                  block
                  secondary
                  :loading="busy"
                  @click="learning.loadMore"
                  >加载更多记录</NButton
                >
              </section>
            </template>
            <footer>
              <span
                >ARISTOTLE 408
                <span class="separator">/</span>
                学习是一个逐渐清晰的过程。</span
              ><span>联调原型 · 演示题尚非正式审核题库</span>
            </footer>
          </template>
          <NButton
            class="mobile-logout"
            secondary
            :disabled="busy || submitting || mutating"
            @click="learning.logout"
            >退出 / 切换账号</NButton
          >
        </main>
      </div>
    </div>
    <QuizDialog
      v-model:show="quizOpen"
      :task="task"
      :submitting="submitting"
      :loading="busy"
      :error="error"
      :pending="pendingSubmission"
      @submit="learning.submit"
      @history="page = '学习记录'"
      @next-task="start(true)"
    />
    <MaterialDialog
      v-model:show="materialOpen"
      :nodes="graph?.nodes || []"
      :loading="mutating"
      :error="error"
      @save="add"
    />
  </NConfigProvider>
</template>

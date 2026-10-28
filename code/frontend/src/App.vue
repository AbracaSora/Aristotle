<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, ref, watch } from "vue";
import {
  NConfigProvider,
  NButton,
  NTag,
  NAlert,
  NEmpty,
  NPopconfirm,
  NSelect,
  NInput,
  zhCN,
} from "naive-ui";
import {
  Layers,
  LayoutDashboard,
  Network,
  Library,
  History,
  Check,
  BookOpen,
  LogOut,
  RefreshCw,
} from "lucide-vue-next";
import LoginPanel from "./components/LoginPanel.vue";
import QuizDialog from "./components/QuizDialog.vue";
import MaterialDialog from "./components/MaterialDialog.vue";
import { useLearning } from "./useLearning";
import { useWorkflow } from "./useWorkflow";
import WorkflowWorkspace from "./components/WorkflowWorkspace.vue";
import MaterialImportPanel from "./components/MaterialImportPanel.vue";
const ManagementConsole = defineAsyncComponent(
  () => import("./components/ManagementConsole.vue"),
);
import { levelLabels, stateLabels } from "./types";
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
const workflow = useWorkflow(learning);
const { scopes, context, timeline, reports, loading: flowLoading } = workflow;
const reportKey = ref(""),
  reportCategory = ref("answer"),
  reportText = ref("");
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
} = learning;
const page = ref("学习概览"),
  quizOpen = ref(false),
  materialOpen = ref(false);
const knowledgeOptions = computed(() =>
  (graph.value?.nodes || []).map((node) => ({
    label: node.name,
    value: node.id,
  })),
);
function knowledgeName(id: string) {
  return graph.value?.nodes.find((node) => node.id === id)?.name || id;
}
async function start(_force = false, knowledgeId?: string) {
  if (submitting.value || busy.value || flowLoading.value) return;
  if (!context.value?.selected_scope) {
    page.value = "学习概览";
    error.value = "请先选择学习范围。";
    return;
  }
  if (
    !context.value.diagnostic ||
    context.value.diagnostic.status === "active"
  ) {
    page.value = "学习概览";
    if (!context.value.diagnostic) await workflow.begin();
    const segment = context.value.diagnostic?.segments.find(
      (s) => s.status !== "completed",
    );
    if (segment) await openTask(segment.task_id);
    return;
  }
  await workflow.recommend(knowledgeId);
  page.value = "学习概览";
}
async function openTask(id: string) {
  if (await workflow.open(id)) quizOpen.value = true;
}
async function nextStep() {
  quizOpen.value = false;
  if (await workflow.next()) quizOpen.value = true;
}
async function refreshAll() {
  await learning.refresh();
  await workflow.run(async () => {
    await workflow.reload();
    if (
      task.value?.scope_id === context.value?.selected_scope?.id &&
      task.value
    )
      learning.task.value = await learning.call(`/tasks/${task.value.id}`);
  });
}
async function chooseScope(id: string) {
  if (await workflow.choose(id)) quizOpen.value = false;
}
async function reportContent() {
  await workflow.run(async () => {
    await learning.call("/content-reports", "POST", {
      question_key: reportKey.value,
      category: reportCategory.value,
      message: reportText.value,
    });
    reportKey.value = "";
    reportText.value = "";
    await workflow.reload();
  });
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
            v-for="item in user.role === 'student'
              ? nav
              : [
                  {
                    name: user.role === 'admin' ? '系统管理' : '内容工作台',
                    icon: Layers,
                  },
                ]"
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
              user.role === "student"
                ? "学习进度已连接"
                : user.role === "admin"
                  ? "系统管理员"
                  : "内容维护者"
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
            <span
              >● &nbsp;
              {{ context?.selected_scope?.title || "尚未选择范围" }}</span
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
          <template v-if="user.role !== 'student'"
            ><ManagementConsole
              :key="user.id"
              :user="user"
              :call="learning.call"
          /></template>
          <template v-else>
            <div class="heading">
              <div>
                <p class="eyebrow">
                  {{ date }} <span> / YOUR LEARNING JOURNEY</span>
                </p>
                <h1>
                  {{ page === "学习概览" ? "让每一步学习，都有方向。" : page }}
                </h1>
                <p class="subtitle">诊断起点，安排学习，再通过复测检验。</p>
              </div>
              <NButton secondary :loading="busy" @click="refreshAll"
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
              <WorkflowWorkspace
                :scopes="scopes"
                :context="context"
                :timeline="timeline"
                :loading="flowLoading || busy"
                @choose="chooseScope"
                @diagnose="workflow.begin()"
                @recommend="workflow.recommend()"
                @open="openTask"
                @action="(action, id) => workflow.act(action, id)"
                @next="nextStep"
                @materials="page = '我的资料'"
              />
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
              <section class="panel">
                <h3>用知识地图查看证据，用自己的讲义辅助学习</h3>
                <p class="muted">
                  记忆、理解、应用、分析分别呈现；“证据不足”与“待巩固”有不同含义。阅读和重复答对同一道题不会直接成为新的掌握证据。
                </p>
                <div class="actions">
                  <NButton secondary @click="page = '知识地图'"
                    >查看知识地图</NButton
                  ><NButton secondary @click="page = '我的资料'"
                    >整理资料</NButton
                  ><NButton text @click="page = '学习记录'"
                    >查看学习记录与纠错</NButton
                  >
                </div>
              </section>
            </template>
            <template v-else-if="page === '知识地图'">
              <NAlert type="info" class="notice"
                >状态来自最近
                {{ state?.window_days || 14 }}
                天的有效作答；独立复测涉及的维度从本轮重新收集证据。先修满足且证据充分后，才能标记初步掌握；当前使用规则基线。</NAlert
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
              <MaterialImportPanel
                :call="learning.call"
                :nodes="graph?.nodes || []"
                :materials="materials"
                :disabled="!context?.selected_scope"
                @refresh="refreshAll"
              />
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
                  <template v-if="!m.chunks?.length"
                    ><label class="field"
                      >关联知识点<NSelect
                        :value="m.knowledge_id"
                        :options="knowledgeOptions"
                        :disabled="mutating"
                        @update:value="
                          (id) => updateAssociation(m, String(id))
                        "
                    /></label>
                    <p class="muted">
                      来源：{{ m.source_location
                      }}<br />改变知识点后需要重新确认关联。
                    </p>
                  </template>
                  <div class="actions">
                    <NButton
                      v-if="!m.chunks?.length"
                      size="small"
                      :disabled="mutating"
                      @click="
                        learning.updateMaterial(m, m.knowledge_id, !m.confirmed)
                      "
                      >{{ m.confirmed ? "取消关联" : "确认关联" }}</NButton
                    ><NPopconfirm
                      @positive-click="
                        async () => {
                          await learning.removeMaterial(m.id);
                          await refreshAll();
                        }
                      "
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
                >历史作答完整保留；当前诊断按最近 14
                天及独立诊断边界取有效记录，同一稳定题目在窗口内只取首次作答。以下已显示
                {{ history.items.length }} /
                {{ history.total }} 条记录。</NAlert
              >
              <section v-if="reportKey" class="panel">
                <h3>报告题目问题 · {{ reportKey }}</h3>
                <NSelect
                  v-model:value="reportCategory"
                  :options="[
                    { label: '答案问题', value: 'answer' },
                    { label: '解析问题', value: 'explanation' },
                    { label: '认知标签问题', value: 'label' },
                  ]"
                /><NInput
                  v-model:value="reportText"
                  type="textarea"
                  placeholder="说明你发现的问题"
                  aria-label="问题说明"
                />
                <div class="actions">
                  <NButton
                    type="primary"
                    :disabled="!reportText.trim() || flowLoading"
                    @click="reportContent"
                    >提交报告</NButton
                  ><NButton @click="reportKey = ''">取消</NButton>
                </div>
              </section>
              <details v-if="reports.length" class="panel">
                <summary>我的问题报告 · {{ reports.length }} 项</summary>
                <p v-for="r in reports" :key="r.id">
                  {{ r.question_key }} · {{ r.status }} · {{ r.message
                  }}<br />处理结论：{{ r.resolution || "等待维护者复核" }}
                </p>
              </details>
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
                    <p v-if="a.retirement_reason">
                      停用原因：{{ a.retirement_reason }}
                    </p>
                    <NButton
                      text
                      size="tiny"
                      @click="reportKey = a.question_key"
                      >报告答案 / 解析 / 标签问题</NButton
                    >
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
      :loading="busy || flowLoading"
      :error="error"
      :pending="pendingSubmission"
      @submit="learning.submit"
      @history="page = '学习记录'"
      @next-task="nextStep"
      @complete="workflow.act('complete')"
      @rebuild="
        async () => {
          quizOpen = false;
          if (await workflow.rebuild()) quizOpen = true;
        }
      "
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

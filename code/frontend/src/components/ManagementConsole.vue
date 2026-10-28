<script setup lang="ts">
import { onMounted, ref } from "vue";
import {
  NButton,
  NInput,
  NSelect,
  NCheckbox,
  NAlert,
  NTag,
  NInputNumber,
} from "naive-ui";
import type { User, Job } from "../types";
import { levelLabels } from "../types";
const props = defineProps<{
  user: User;
  call: <T>(path: string, method?: string, body?: unknown) => Promise<T>;
}>();
const questions = ref<any[]>([]),
  candidates = ref<any[]>([]),
  reports = ref<any[]>([]),
  jobs = ref<Job[]>([]),
  audit = ref<any[]>([]),
  users = ref<User[]>([]),
  settings = ref<any>(null),
  busy = ref(false),
  selected = ref(""),
  scenario = ref("normal"),
  level = ref("understand"),
  reason = ref(""),
  verified = ref(false),
  result = ref<Job | null>(null),
  notice = ref("");
const draft = ref(
  JSON.stringify(
    {
      question_id: "example_stack",
      version: 1,
      knowledge_id: "stack",
      prompt: "入栈 A、B 后弹出一次，栈顶是什么？",
      options: ["A", "B"],
      answer: "A",
      explanation: "B 后进入先弹出，留下 A。",
      source: "人工编写样例，审核前不得用于学习",
    },
    null,
    2,
  ),
);
const graphJSON = ref("");
const levels = Object.entries(levelLabels)
  .filter(([v]) => !["evaluate", "create"].includes(v))
  .map(([value, label]) => ({ value, label }));
async function reload() {
  const [j, a] = await Promise.all([
    props.call<{ items: Job[] }>("/admin/jobs"),
    props.call<{ items: any[] }>("/admin/audit"),
  ]);
  jobs.value = j.items;
  audit.value = a.items;
  if (props.user.role === "maintainer") {
    const [q, c, r] = await Promise.all([
      props.call<{ items: any[] }>("/admin/questions"),
      props.call<{ items: any[] }>("/admin/candidates"),
      props.call<{ items: any[] }>("/admin/content-reports"),
    ]);
    questions.value = q.items;
    candidates.value = c.items;
    reports.value = r.items;
  } else {
    const [s, u] = await Promise.all([
      props.call<any>("/admin/provider-settings"),
      props.call<{ items: User[] }>("/admin/users"),
    ]);
    settings.value = s.settings;
    users.value = u.items;
  }
}
async function run(fn: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true;
  notice.value = "";
  try {
    await fn();
    await reload();
  } catch (e) {
    notice.value = e instanceof Error ? e.message : "操作失败";
  } finally {
    busy.value = false;
  }
}
function revision(q: any) {
  draft.value = JSON.stringify(
    {
      question_id: q.question_id,
      version: q.version + 1,
      knowledge_id: q.knowledge_id,
      prompt: q.prompt,
      options: q.options,
      answer: q.answer,
      explanation: q.explanation,
      source: q.source,
    },
    null,
    2,
  );
  notice.value =
    "已载入修订草稿，请修改正文后建立新版本。旧版本及历史作答保留。";
}
async function create() {
  await run(async () => {
    const q = await props.call<any>(
      "/admin/questions",
      "POST",
      JSON.parse(draft.value),
    );
    selected.value = q.key;
    notice.value = "草稿已建立，尚不可分配给学生。";
  });
}
async function annotate() {
  await run(async () => {
    result.value = await props.call<Job>(
      `/admin/questions/${selected.value}/annotation-jobs`,
      "POST",
      { scenario: scenario.value, suggested_level: level.value },
    );
  });
}
async function review(c: any, decision: string) {
  await run(async () => {
    await props.call(`/admin/candidates/${c.id}/review`, "POST", {
      decision,
      reason: reason.value,
      final_level: decision === "approve" ? level.value : null,
      content_verified: verified.value,
    });
    verified.value = false;
    notice.value =
      decision === "approve"
        ? "已发布审核通过的新版本。"
        : "已驳回，可修订后重新提交。";
  });
}
async function resolve(r: any, action: string) {
  await run(async () => {
    await props.call(`/admin/content-reports/${r.id}/resolve`, "POST", {
      action,
      reason: reason.value,
    });
  });
}
onMounted(() => run(reload));
</script>
<template>
  <div class="section-heading">
    <div>
      <span class="eyebrow">CONTENT & OPERATIONS</span>
      <h1>{{ user.role === "admin" ? "系统管理" : "内容维护与审核" }}</h1>
    </div>
    <NButton :loading="busy" @click="run(reload)">刷新工作台</NButton>
  </div>
  <NAlert type="info" class="notice"
    >模型和 PDF 处理使用 mock。草稿 → 候选标注 → 人工核验答案、解析和标签 →
    发布，发布后才进入学习。管理员配置与内容审核使用独立权限。</NAlert
  >
  <NAlert v-if="notice" type="info" class="notice">{{ notice }}</NAlert>
  <template v-if="user.role === 'maintainer'">
    <section class="panel">
      <h2>1. 建立题目版本</h2>
      <p class="muted">
        完整题干、选项、答案、解析和来源一起送审。已发布版本不能原地修改。
      </p>
      <NInput
        v-model:value="draft"
        type="textarea"
        :rows="10"
        aria-label="题目草稿 JSON"
      /><NButton type="primary" :loading="busy" @click="create"
        >建立草稿版本</NButton
      >
      <details class="history-details">
        <summary>题目版本 · {{ questions.length }} 项</summary>
        <article v-for="q in questions" :key="q.key" class="source-chunk">
          <NTag>{{ q.status }}</NTag> {{ q.key }} · {{ q.prompt }}
          <p>答案 {{ q.answer }} · {{ q.explanation }}</p>
          <NButton size="small" :disabled="busy" @click="revision(q)"
            >以此建立修订草稿</NButton
          >
        </article>
      </details>
    </section>
    <section class="panel">
      <h2>2. 候选标注（mock）</h2>
      <div class="scope-bar">
        <NSelect
          aria-label="待标注题目"
          v-model:value="selected"
          placeholder="选择草稿/待审核版本"
          :options="
            questions
              .filter((q) => ['draft', 'pending_review'].includes(q.status))
              .map((q) => ({ label: q.key + ' · ' + q.prompt, value: q.key }))
          "
        /><NSelect
          aria-label="标注模拟情形"
          v-model:value="scenario"
          :options="[
            { label: '正常（低置信度候选）', value: 'normal' },
            { label: '超时', value: 'timeout' },
            { label: '限流', value: 'rate_limited' },
            { label: '输出结构错误', value: 'invalid_output' },
            { label: '题目版本过期', value: 'stale_version' },
          ]"
        />
      </div>
      <NButton :loading="busy" :disabled="!selected" @click="annotate"
        >建立标注任务</NButton
      >
      <div v-if="result" class="flow-focus">
        <NTag>{{ result.status }}</NTag>
        <p>{{ result.result.error || result.notice }}</p>
        <NButton
          v-if="result.status === 'queued'"
          :loading="busy"
          @click="
            run(async () => {
              result = await call<Job>(`/jobs/${result!.id}/run`, 'POST');
            })
          "
          >运行 mock 标注</NButton
        ><NButton
          v-if="result.result.retryable"
          :loading="busy"
          @click="
            run(async () => {
              result = await call<Job>(`/jobs/${result!.id}/retry`, 'POST');
            })
          "
          >重试（计入配额）</NButton
        >
        <pre>{{ JSON.stringify(result.result, null, 2) }}</pre>
      </div>
    </section>
    <section class="panel">
      <h2>3. 人工审核与问题处理</h2>
      <label class="field"
        >最终认知活动<NSelect v-model:value="level" :options="levels" /></label
      ><label class="field"
        >审核 / 处理理由<NInput
          v-model:value="reason"
          type="textarea"
          placeholder="结合解题步骤说明判断、修正和停用原因" /></label
      ><NCheckbox v-model:checked="verified"
        >已核验完整题干、标准答案和解析的正确性</NCheckbox
      >
      <article
        v-for="c in candidates.filter((c) => c.decision === 'pending')"
        :key="c.id"
        class="source-chunk"
      >
        <NAlert v-if="c.needs_attention" type="warning"
          >重点复核：低置信度或存在歧义</NAlert
        >
        <h3>{{ c.question_key }} · {{ c.candidate.primary_level }}</h3>
        <p>{{ questions.find((q) => q.key === c.question_key)?.prompt }}</p>
        <p>
          标准答案：{{ questions.find((q) => q.key === c.question_key)?.answer
          }}<br />解析：{{
            questions.find((q) => q.key === c.question_key)?.explanation
          }}
        </p>
        <p>
          {{ c.candidate.rationale }} · 置信度 {{ c.candidate.confidence
          }}<br />{{ c.candidate.ambiguity_note }}
        </p>
        <p class="muted">
          {{ c.provider }} · {{ c.rule_version }} · 题目 v{{
            c.candidate.question_version
          }}
        </p>
        <div class="actions">
          <NButton
            type="primary"
            :disabled="busy || !verified || !reason.trim()"
            @click="review(c, 'approve')"
            >确认标签并发布</NButton
          ><NButton
            :disabled="busy || !reason.trim()"
            @click="review(c, 'reject')"
            >驳回候选</NButton
          >
        </div>
      </article>
      <details class="history-details">
        <summary>已审核标注与修订记录</summary>
        <article
          v-for="c in candidates.filter((c) => c.decision !== 'pending')"
          :key="c.id"
          class="source-chunk"
        >
          <strong
            >{{ c.question_key }} ·
            {{ c.decision === "approve" ? "批准" : "驳回" }}</strong
          >
          <p>
            候选：{{ c.candidate.primary_level }}；最终：{{
              c.review?.final_level || "无"
            }}
            · {{ c.provider }} · {{ c.rule_version }}
          </p>
          <p>{{ c.review?.reason }}</p>
        </article>
      </details>
      <h3>学习者上报</h3>
      <p v-if="!reports.length" class="muted">暂无问题报告。</p>
      <article v-for="r in reports" :key="r.id" class="source-chunk">
        <NTag>{{ r.status }}</NTag>
        <p>{{ r.question_key }} · {{ r.category }} · {{ r.message }}</p>
        <p>{{ r.resolution }}</p>
        <div v-if="r.status === 'open'" class="actions">
          <NButton
            :disabled="busy || !reason.trim()"
            @click="resolve(r, 'retire')"
            >停用版本并记录原因</NButton
          ><NButton
            :disabled="busy || !reason.trim()"
            @click="resolve(r, 'resolve')"
            >记录处理结论</NButton
          ><NButton
            text
            :disabled="busy || !reason.trim()"
            @click="resolve(r, 'dismiss')"
            >驳回报告</NButton
          >
        </div>
      </article>
    </section>
    <details class="panel">
      <summary>维护知识图（现有 API）</summary>
      <p class="muted">
        提交 version 和
        nodes（id/name/prerequisites）。先修成环、引用不存在及删除仍被内容引用的知识点均会被拒绝。
      </p>
      <NInput
        v-model:value="graphJSON"
        type="textarea"
        :rows="6"
        placeholder='{"version":"graph-v2","nodes":[...]}'
      /><NButton
        :disabled="busy || !graphJSON.trim()"
        @click="
          run(async () => {
            await call('/admin/graphs', 'POST', JSON.parse(graphJSON));
            notice = '知识图已发布';
          })
        "
        >发布知识图版本</NButton
      >
    </details>
  </template>
  <template v-else-if="settings">
    <section class="panel">
      <h2>模型服务配置 · mock 适配器</h2>
      <NSelect
        v-model:value="settings.mode"
        :options="[
          { label: '启用 mock', value: 'mock' },
          { label: '禁用模型（学习继续使用已发布内容）', value: 'disabled' },
        ]"
      />
      <div class="settings-grid">
        <label
          >单次超时（秒，模拟）<NInputNumber
            v-model:value="settings.timeout_seconds"
            :min="1"
            :max="30" /></label
        ><label
          >重试次数<NInputNumber
            v-model:value="settings.retries"
            :min="0"
            :max="1" /></label
        ><label
          >总预算（秒，模拟）<NInputNumber
            v-model:value="settings.total_budget_seconds"
            :min="1"
            :max="65" /></label
        ><label
          >每日调用上限（北京时间）<NInputNumber
            v-model:value="settings.daily_annotation_limit"
            :min="1"
            :max="200"
        /></label>
      </div>
      <p class="muted">
        真实外部调用 0；已记录样例任务 {{ jobs.length }} 项，预留调用单位
        {{ jobs.reduce((s, j) => s + (j.result.quota_reserved || 0), 0) }}（最近
        100 项）。token 使用量暂无实测。超时和重试通过情形模拟。
      </p>
      <div class="actions">
        <NButton
          type="primary"
          :loading="busy"
          @click="
            run(async () => {
              const { revision, ...body } = settings;
              await call('/admin/provider-settings', 'PATCH', body);
              notice = '配置版本已保存并记录审计';
            })
          "
          >保存配置</NButton
        ><NButton
          @click="
            run(async () => {
              await call('/admin/providers/live', 'POST');
            })
          "
          >真实模型适配器：接口占位</NButton
        >
      </div>
    </section>
    <section class="panel">
      <h2>角色分配</h2>
      <p class="muted">
        角色变更后立即撤销该用户旧会话。内容审核使用 editor，系统配置使用
        admin。
      </p>
      <div v-for="u in users" :key="u.id" class="scope-bar">
        <span>{{ u.username }}</span
        ><NSelect
          :value="u.role"
          :disabled="busy || u.id === user.id"
          :options="[
            { label: '学生', value: 'student' },
            { label: '内容维护者', value: 'maintainer' },
            { label: '系统管理员', value: 'admin' },
          ]"
          @update:value="
            (role) =>
              run(async () => {
                await call(`/admin/users/${u.id}/role`, 'PATCH', { role });
              })
          "
        />
      </div>
    </section>
  </template>
  <section class="panel">
    <h2>标注任务与失败记录</h2>
    <p v-if="!jobs.length" class="muted">暂无任务。</p>
    <article v-for="j in jobs.slice(0, 20)" :key="j.id" class="source-chunk">
      <NTag :type="j.status === 'failed' ? 'warning' : 'default'">{{
        j.status
      }}</NTag>
      {{ j.id }}
      <NButton
        v-if="
          user.role === 'maintainer' &&
          j.can_run &&
          ['queued', 'failed'].includes(j.status)
        "
        text
        @click="result = j"
        >查看 / 继续任务（上方标注区）</NButton
      >
      <p>
        {{
          j.result.error ||
          (j.result.requires_review
            ? "候选已生成；审核结论见候选及题目记录"
            : "等待运行")
        }}
      </p>
      <p class="muted">
        {{ j.result.model || "mock" }} · {{ j.result.prompt_version }} ·
        {{ j.result.rule_version }} · 真实调用
        {{ j.result.real_external_calls || 0 }}
      </p>
    </article>
  </section>
  <details class="panel">
    <summary>配置、角色与内容审计 · 最近 {{ audit.length }} 条</summary>
    <p v-for="a in audit" :key="a.id" class="muted">
      {{ new Date(a.at * 1000).toLocaleString("zh-CN") }} · {{ a.actor_id }} ·
      {{ a.action }} · {{ a.target }}
    </p>
  </details>
</template>

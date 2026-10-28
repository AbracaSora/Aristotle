<script setup lang="ts">
import { computed, ref } from "vue";
import { NButton, NTag, NAlert, NSelect } from "naive-ui";
import type { Scope, LearningContext, TimelineItem } from "../types";
import { levelLabels, stateLabels } from "../types";
const props = defineProps<{
  scopes: Scope[];
  context: LearningContext | null;
  timeline: TimelineItem[];
  loading: boolean;
}>();
const emit = defineEmits<{
  choose: [id: string];
  diagnose: [];
  recommend: [];
  open: [id: string];
  action: [action: string, id: string];
  next: [];
  materials: [];
}>();
const picked = ref<string | null>(null);
const current = computed(() => props.context?.current_task);
const segment = computed(() =>
  props.context?.diagnostic?.segments.find((s) => s.status !== "completed"),
);
const labels: Record<string, string> = {
  recommended: "等待接受",
  accepted: "已接受",
  active: "进行中",
  completed: "已完成",
  skipped: "已跳过",
  superseded: "已更换",
};
</script>
<template>
  <section class="panel workflow-panel">
    <div class="section-heading">
      <div>
        <span class="eyebrow">YOUR LEARNING PATH</span>
        <h2>从诊断到学习，再用证据检验</h2>
      </div>
      <NTag type="success">规则编排 · 演示内容</NTag>
    </div>
    <ol class="journey">
      <li :class="{ current: !context?.selected_scope }">01 选择范围</li>
      <li :class="{ current: context?.stage === 'diagnosis' }">02 初始诊断</li>
      <li :class="{ current: context?.stage === 'recommendation' }">
        03 学习安排
      </li>
      <li :class="{ current: context?.stage === 'activity' }">04 学习与练习</li>
      <li>05 反馈与复测</li>
    </ol>
    <div class="scope-bar">
      <label>学习范围</label
      ><NSelect
        aria-label="学习范围"
        :value="picked || context?.selected_scope?.id"
        :options="
          scopes.map((s) => ({
            label: s.title + (s.published ? '' : '（尚未开放）'),
            value: s.id,
            disabled: !s.published,
          }))
        "
        @update:value="picked = $event"
      /><NButton
        :disabled="loading || !picked || picked === context?.selected_scope?.id"
        @click="picked && emit('choose', picked)"
        >确认范围</NButton
      >
    </div>
    <p class="muted">
      {{
        context?.selected_scope?.description ||
        "请选择已开放范围开始。切换范围保留已有作答和私人资料。"
      }}
    </p>
    <template v-if="context?.selected_scope">
      <div v-if="!context.diagnostic" class="flow-focus">
        <h3>先了解起点</h3>
        <p>
          按知识点和认知维度分段收集证据。诊断阶段可以探测先修尚未满足的知识点，之后的学习安排会遵循先修关系。
        </p>
        <NButton type="primary" :loading="loading" @click="emit('diagnose')"
          >开始初始诊断</NButton
        ><NButton text @click="emit('materials')">先整理自己的讲义</NButton>
      </div>
      <div
        v-else-if="context.diagnostic.status === 'active'"
        class="flow-focus"
      >
        <h3>
          继续本轮诊断 · {{ context.diagnostic.completed_segments }} /
          {{ context.diagnostic.segments.length }} 段
        </h3>
        <div class="tags">
          <NTag
            v-for="(s, i) in context.diagnostic.segments"
            :key="s.task_id"
            :type="s.status === 'completed' ? 'success' : 'default'"
            >{{ i + 1 }} · {{ levelLabels[s.level] }} · {{ s.answered }}/{{
              s.question_count
            }}</NTag
          >
        </div>
        <p class="muted">{{ context.diagnostic.notice }}</p>
        <NButton
          v-if="segment"
          type="primary"
          :loading="loading"
          @click="emit('open', segment.task_id)"
          >继续诊断 · {{ levelLabels[segment.level] }}</NButton
        >
      </div>
      <template v-else>
        <NAlert v-if="context.last_feedback" type="info" class="notice"
          ><strong>上次反馈</strong> · {{ context.last_feedback.message }}
          <p v-if="context.last_feedback.state">
            {{ context.last_feedback.state.name }}：{{
              stateLabels[context.last_feedback.state.status]
            }}
            · {{ context.last_feedback.state.evidence_count }} 道有效题
          </p></NAlert
        >
        <div v-if="current" class="flow-focus">
          <div class="tags">
            <NTag type="success">{{
              current.activity === "material_review" ? "资料复习" : "短关卡练习"
            }}</NTag
            ><NTag>{{ labels[current.lifecycle || ""] }}</NTag>
          </div>
          <h3>
            {{ current.goal?.title }} ·
            {{ levelLabels[current.target_level] }}：{{
              current.goal?.description
            }}
          </h3>
          <p>{{ current.reason }}</p>
          <ul class="evidence-facts">
            <li v-for="fact in current.evidence_facts" :key="fact">
              {{ fact }}
            </li>
          </ul>
          <ol class="task-plan">
            <li v-for="step in current.plan" :key="step.kind">
              {{ step.title }}{{ step.required ? "" : "（可选）" }}
            </li>
          </ol>
          <NAlert
            v-for="warning in current.warnings"
            :key="warning"
            type="warning"
            class="notice"
            >{{ warning }}</NAlert
          >
          <p v-if="current.status === 'content_unavailable'" class="muted">
            当前内容不足，无法开始。可以跳过并等待维护者补充。
          </p>
          <div class="actions">
            <NButton
              type="primary"
              :disabled="current.status === 'content_unavailable'"
              :loading="loading"
              @click="emit('open', current.id)"
              >{{
                current.lifecycle === "recommended"
                  ? "接受安排并开始"
                  : "继续本次学习"
              }}</NButton
            ><NButton
              :disabled="loading"
              @click="emit('action', 'replace', current.id)"
              >换一项</NButton
            ><NButton
              text
              :disabled="loading"
              @click="emit('action', 'skip', current.id)"
              >暂时跳过</NButton
            >
          </div>
        </div>
        <div v-else class="flow-focus">
          <h3>
            {{
              context.last_feedback?.next_action === "retest"
                ? "复习之后，用作答证据检验"
                : "看看下一步适合学什么"
            }}
          </h3>
          <p>
            依据薄弱知识、证据缺口、认知活动和先修关系，给出可解释的安排。推荐后由你选择接受、更换或跳过。
          </p>
          <NButton
            type="primary"
            :loading="loading"
            @click="
              context.last_feedback?.next_action === 'retest'
                ? emit('next')
                : emit('recommend')
            "
            >{{
              context.last_feedback?.next_action === "retest"
                ? "开始复测"
                : "生成学习安排"
            }}</NButton
          >
        </div>
      </template>
    </template>
    <details v-if="timeline.length" class="history-details">
      <summary>任务轨迹 · 最近 {{ timeline.length }} 项</summary>
      <p v-for="item in timeline.slice(0, 12)" :key="item.id">
        {{ item.goal.title }} · {{ levelLabels[item.goal.level] }} ·
        {{
          item.activity === "material_review"
            ? "资料复习"
            : item.activity === "diagnostic"
              ? "诊断"
              : "练习"
        }}
        · {{ labels[item.status] }}
        <span class="muted">{{
          new Date(item.created_at * 1000).toLocaleString("zh-CN")
        }}</span>
      </p>
    </details>
  </section>
</template>

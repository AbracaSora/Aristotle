<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { NButton, NTag, NAlert, NRadio, NRadioGroup } from "naive-ui";
import { Check } from "lucide-vue-next";
import { levelDescriptions, levelLabels } from "../../types";
import type { PendingSubmission, Task } from "../../types";
import SourceExplorer from "../../components/SourceExplorer.vue";
const props = defineProps<{
  show: boolean;
  task: Task | null;
  submitting: boolean;
  loading: boolean;
  error: string;
  pending: PendingSubmission | null;
  call?: <T>(path: string, method?: string, body?: unknown) => Promise<T>;
}>();
const emit = defineEmits<{
  "update:show": [show: boolean];
  submit: [key: string, answer: string];
  history: [];
  nextTask: [];
  complete: [];
  rebuild: [];
  materials: [];
}>();
const index = ref(0),
  selected = ref<string | null>(null),
  finished = ref(false);
const explanationOpen = ref(false);
const drafts = new Map<string, string>();
const question = computed(() => props.task?.questions[index.value]);
const feedback = computed(() =>
  props.task?.attempts.find((a) => a.question_key === question.value?.key),
);
const uncertain = computed(
  () =>
    props.pending?.taskId === props.task?.id &&
    props.pending?.questionKey === question.value?.key,
);
const score = computed(
  () => props.task?.attempts.filter((a) => a.correct).length || 0,
);
function initialize() {
  const first =
    props.task?.questions.findIndex(
      (q) => !props.task?.attempts.some((a) => a.question_key === q.key),
    ) ?? -1;
  finished.value = first < 0 && !!props.task?.questions.length;
  index.value = first < 0 ? 0 : first;
  selected.value =
    feedback.value?.selected || drafts.get(question.value?.key || "") ||
    (uncertain.value ? props.pending?.selected || null : null);
}
watch(
  () => props.show,
  (open) => {
    if (open) initialize();
  },
);
watch(
  () => props.task?.id,
  () => {
    if (props.show) initialize();
  },
);
watch(
  () => question.value?.key,
  (_, previous) => {
    if (previous && selected.value) drafts.set(previous, selected.value);
    explanationOpen.value = false;
    selected.value =
      feedback.value?.selected || drafts.get(question.value?.key || "") ||
      (uncertain.value ? props.pending?.selected || null : null);
  },
);
function next() {
  if (index.value >= (props.task?.questions.length || 0) - 1)
    finished.value = true;
  else index.value++;
}
</script>

<template>
  <section v-if="show" class="practice-page" aria-label="独立答题页面">
    <header class="section-heading"><div class="practice-heading"><span class="eyebrow">专注练习</span><h1>{{ task?.goal?.title || '答题练习' }}</h1></div><NButton size="small" quaternary :disabled="submitting" @click="emit('update:show', false)">返回学习空间</NButton></header>
    <template v-if="task">
      <NAlert v-if="error" type="warning" class="notice" role="alert">{{
        error
      }}</NAlert>
      <NAlert v-for="warning in task.warnings" :key="warning" type="info" class="notice">{{ warning }}</NAlert>
      <details v-if="task.resources?.length && task.questions.length" class="history-details task-resources">
        <summary>回看任务资料（可选）</summary>
        <article v-for="r in task.resources" :key="r.id" class="task-material">
          <p v-if="r.unavailable">{{ r.reason }}</p>
          <template v-else>
            <h3>{{ r.title }}</h3>
            <p class="material-text">{{ r.text }}</p>
            <p class="muted">
              {{ r.location }} · {{ r.implementation }}
            </p>
          </template>
        </article>
      </details>
      <template v-if="task.lifecycle === 'completed' && task.feedback">
        <div class="completion">
          <Check :size="38" />
          <h2>
            {{
              task.activity === "diagnostic"
                ? "本段诊断已完成"
                : task.activity === "material_review"
                  ? "复习已记录"
                  : "本次学习已完成"
            }}
          </h2>
          <p>{{ task.feedback.message }}</p>
          <p v-if="task.feedback.answered">
            本段答对 {{ task.feedback.correct }} /
            {{ task.feedback.answered }} 题。
          </p>
          <p v-if="task.feedback.state">
            {{ task.feedback.state.name }} ·
            {{ task.feedback.state.evidence_count }} 道不同题目证据
          </p>
          <div class="actions completion-actions">
            <NButton type="primary" :loading="loading" @click="emit('nextTask')">{{
              task.feedback.next_action === "diagnostic_next"
                ? "继续下一段诊断"
                : task.feedback.next_action === "retest"
                  ? "开始复测"
                  : "查看下一步安排"
            }}</NButton>
            <NButton @click="
              emit('update:show', false);
            emit('history');
            ">学习记录</NButton>
          </div>
        </div>
      </template>
      <template v-else-if="!task.questions.length">
        <NAlert type="info" class="notice">{{ task.reason }}</NAlert>
        <article v-for="r in task.resources" :key="r.id" class="task-material">
          <p v-if="r.unavailable">{{ r.reason }}</p>
          <template v-else>
            <h3>{{ r.title }}</h3>
            <p class="material-text">{{ r.text }}</p>
            <p class="muted">
              {{ r.location }} · {{ r.implementation }}
            </p>
          </template>
        </article>
        <p class="muted">阅读不会增加掌握分数；完成后需要通过作答检验。</p>
        <NButton v-if="task.status === 'material_review'" type="primary" :loading="loading" @click="emit('complete')">
          已完成复习，查看反馈
        </NButton>
      </template>
      <template v-else-if="finished">
        <div class="completion">
          <Check :size="38" />
          <h2>作答已保存</h2>
          <p>
            答对 {{ score }} /
            {{ task.questions.length }} 题。完成本段后查看证据反馈与下一步安排。
          </p>
          <NButton type="primary" :loading="loading" @click="emit('complete')">完成本段并查看反馈</NButton>
        </div>
      </template>
      <template v-else-if="question">
        <div class="quiz-top">
          <NTag type="success" :bordered="false">{{ levelLabels[question.level] }} ·
            {{ levelDescriptions[question.level] }}</NTag><span>{{ index + 1 }} / {{ task.questions.length }}</span>
        </div>
        <div class="actions"><NButton v-for="(item, i) in task.questions" :key="item.key" :type="i === index ? 'primary' : 'default'" :disabled="submitting" @click="index = i">{{ i + 1 }}</NButton></div><h2 class="question">{{ question.prompt }}</h2>
        <NAlert v-if="question.status !== 'published' && !feedback" type="warning" class="notice">
          此版本已停用，请重建诊断或更换任务，原作答保留。<NButton text @click="emit('rebuild')">重建 / 更换任务</NButton>
        </NAlert>
        <NRadioGroup v-model:value="selected" :disabled="!!feedback ||
          submitting ||
          uncertain ||
          question.status !== 'published'
          " class="answers" aria-label="选择答案">
          <NRadio v-for="option in question.options" :key="option" :value="option">{{ option }}</NRadio>
        </NRadioGroup>
        <NAlert v-if="feedback" class="feedback" :type="feedback.correct ? 'success' : 'warning'" :title="feedback.correct ? '回答正确' : '正确答案：' + feedback.answer
          ">{{ feedback.explanation }} 单题结果仅作为一条作答证据。</NAlert>
        <p v-if="uncertain && !feedback" class="muted">
          提交结果尚未确认，重试将使用同一个提交编号和原答案。
        </p>
        <p class="muted quiz-source">
          题目 {{ question.key }} ·
          {{
            question.dataset === "demo-seed"
              ? "演示样例，尚非正式审核题库"
              : "内容维护者发布"
          }}
        </p>
        <details v-if="feedback" class="history-details"><summary>查看生成 Prompt</summary><p>{{ question.generation_prompt || "该题未提供生成 Prompt（真题不适用）。" }}</p></details><div class="dialog-actions">
          <NButton v-if="!feedback" type="primary" :disabled="!selected || question.status !== 'published'"
            :loading="submitting" @click="selected && emit('submit', question.key, selected)">{{ uncertain ? "重试保存" :
              "提交答案" }}</NButton>
          <NButton v-else type="primary" @click="next">{{
            index === task.questions.length - 1 ? "查看反馈" : "下一题"
          }}</NButton>
        </div>
        <details v-if="feedback && call" :open="explanationOpen" class="history-details"
          @toggle="explanationOpen = ($event.target as HTMLDetailsElement).open">
          <summary>查阅资料与 AI 辅助解释（可选）</summary>
          <SourceExplorer v-if="explanationOpen" :key="feedback.id" :knowledge-id="question.knowledge_id"
            :knowledge-name="task.goal?.title || question.knowledge_id" :attempt-id="feedback.id" :call="call"
            @materials="emit('update:show', false); emit('materials')" />
        </details>
      </template>
    </template>
  </section>
</template>

<style scoped>
.practice-page { max-width: 1000px; margin: 0 auto; padding: 16px 0 32px; }
.section-heading { margin-bottom: 18px; gap: 12px; }
.practice-heading { display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; }
.practice-heading h1 { font-size: 22px; line-height: 1.4; margin: 0; }
.practice-heading .eyebrow { font-size: 11px; margin: 0; white-space: nowrap; }
.task-resources { margin: 10px 0 16px; font-size: 13px; }
.practice-page > p { margin: 24px 0; }
.history-details:not(.task-resources) { margin: 28px 0; }
.quiz-top { margin: 16px 0 12px; font-size: 13px; }
.actions { flex-wrap: wrap; gap: 14px; margin: 12px 0 24px; }
.question { margin: 28px 0 36px; line-height: 1.85; }
.answers { gap: 22px; }
.answers :deep(.n-radio) { padding: 20px 18px; }
.quiz-source { margin-top: 32px; }
.feedback { margin-top: 32px; }
.dialog-actions { margin-top: 44px; }
@media (max-width: 600px) {
  .section-heading { margin-bottom: 16px; align-items: center; }
  .practice-heading { gap: 6px; }
  .practice-heading h1 { font-size: 19px; }
  .question { margin: 30px 0; }
  .answers { gap: 18px; }
}
</style>

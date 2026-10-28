<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { NModal, NButton, NTag, NAlert, NRadio, NRadioGroup } from "naive-ui";
import { Check } from "lucide-vue-next";
import { levelDescriptions, levelLabels } from "../types";
import type { PendingSubmission, Task } from "../types";
const props = defineProps<{
  show: boolean;
  task: Task | null;
  submitting: boolean;
  loading: boolean;
  error: string;
  pending: PendingSubmission | null;
}>();
const emit = defineEmits<{
  "update:show": [show: boolean];
  submit: [key: string, answer: string];
  history: [];
  nextTask: [];
  complete: [];
  rebuild: [];
}>();
const index = ref(0),
  selected = ref<string | null>(null),
  finished = ref(false);
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
    feedback.value?.selected ||
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
  () => {
    selected.value =
      feedback.value?.selected ||
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
  <NModal
    :show="show"
    preset="card"
    :title="
      task?.activity === 'diagnostic'
        ? '诊断 · 收集认知证据'
        : task?.activity === 'material_review'
          ? '资料复习 · 准备复测'
          : '学习任务 · 短关卡'
    "
    class="dialog"
    :mask-closable="false"
    :closable="!submitting"
    :close-on-esc="!submitting"
    @update:show="emit('update:show', $event)"
  >
    <template v-if="task">
      <NAlert v-if="error" type="warning" class="notice" role="alert">{{
        error
      }}</NAlert>
      <NAlert
        v-for="warning in task.warnings"
        :key="warning"
        type="info"
        class="notice"
        >{{ warning }}</NAlert
      >
      <p v-if="task.goal">
        <strong
          >{{ task.goal.title }} · {{ levelLabels[task.target_level] }}</strong
        >
        — {{ task.goal.description }}
      </p>
      <details
        v-if="task.resources?.length && task.questions.length"
        class="history-details"
      >
        <summary>回看任务资料（可选）</summary>
        <article v-for="r in task.resources" :key="r.id" class="task-material">
          <p v-if="r.unavailable">{{ r.reason }}</p>
          <template v-else
            ><h3>{{ r.title }}</h3>
            <p class="material-text">{{ r.text }}</p>
            <p class="muted">
              {{ r.location }} · {{ r.implementation }}
            </p></template
          >
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
            <NButton
              type="primary"
              :loading="loading"
              @click="emit('nextTask')"
              >{{
                task.feedback.next_action === "diagnostic_next"
                  ? "继续下一段诊断"
                  : task.feedback.next_action === "retest"
                    ? "开始复测"
                    : "查看下一步安排"
              }}</NButton
            ><NButton
              @click="
                emit('update:show', false);
                emit('history');
              "
              >学习记录</NButton
            >
          </div>
        </div>
      </template>
      <template v-else-if="!task.questions.length">
        <NAlert type="info" class="notice">{{ task.reason }}</NAlert>
        <article v-for="r in task.resources" :key="r.id" class="task-material">
          <p v-if="r.unavailable">{{ r.reason }}</p>
          <template v-else
            ><h3>{{ r.title }}</h3>
            <p class="material-text">{{ r.text }}</p>
            <p class="muted">
              {{ r.location }} · {{ r.implementation }}
            </p></template
          >
        </article>
        <p class="muted">阅读不会增加掌握分数；完成后需要通过作答检验。</p>
        <NButton
          v-if="task.status === 'material_review'"
          type="primary"
          :loading="loading"
          @click="emit('complete')"
          >已完成复习，查看反馈</NButton
        >
      </template>
      <template v-else-if="finished">
        <div class="completion">
          <Check :size="38" />
          <h2>作答已保存</h2>
          <p>
            答对 {{ score }} /
            {{ task.questions.length }} 题。完成本段后查看证据反馈与下一步安排。
          </p>
          <NButton type="primary" :loading="loading" @click="emit('complete')"
            >完成本段并查看反馈</NButton
          >
        </div>
      </template>
      <template v-else-if="question">
        <div class="quiz-top">
          <NTag type="success" :bordered="false"
            >{{ levelLabels[question.level] }} ·
            {{ levelDescriptions[question.level] }}</NTag
          ><span>{{ index + 1 }} / {{ task.questions.length }}</span>
        </div>
        <h2 class="question">{{ question.prompt }}</h2>
        <NAlert
          v-if="question.status !== 'published' && !feedback"
          type="warning"
          class="notice"
          >此版本已停用，请重建诊断或更换任务，原作答保留。<NButton
            text
            @click="emit('rebuild')"
            >重建 / 更换任务</NButton
          ></NAlert
        >
        <NRadioGroup
          v-model:value="selected"
          :disabled="
            !!feedback ||
            submitting ||
            uncertain ||
            question.status !== 'published'
          "
          class="answers"
          aria-label="选择答案"
          ><NRadio
            v-for="option in question.options"
            :key="option"
            :value="option"
            >{{ option }}</NRadio
          ></NRadioGroup
        >
        <NAlert
          v-if="feedback"
          class="feedback"
          :type="feedback.correct ? 'success' : 'warning'"
          :title="
            feedback.correct ? '回答正确' : '正确答案：' + feedback.answer
          "
          >{{ feedback.explanation }} 单题结果仅作为一条作答证据。</NAlert
        >
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
        <div class="dialog-actions">
          <NButton
            v-if="!feedback"
            type="primary"
            :disabled="!selected || question.status !== 'published'"
            :loading="submitting"
            @click="selected && emit('submit', question.key, selected)"
            >{{ uncertain ? "重试保存" : "提交答案" }}</NButton
          ><NButton v-else type="primary" @click="next">{{
            index === task.questions.length - 1 ? "查看反馈" : "下一题"
          }}</NButton>
        </div>
      </template>
    </template>
  </NModal>
</template>

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
    title="学习任务 · 短关卡"
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
      <template v-if="!task.questions.length">
        <NAlert
          :type="task.status === 'material_review' ? 'info' : 'warning'"
          class="notice"
          >{{
            task.status === "material_review"
              ? "该目标暂时没有可用题目，先复习已确认资料。"
              : "该目标暂无已发布题目或已确认资料，请联系内容维护者补充。"
          }}</NAlert
        >
        <p class="muted">{{ task.reason }}</p>
        <article
          v-for="material in task.materials"
          :key="material.id"
          class="task-material"
        >
          <template v-if="'unavailable' in material"
            ><p class="muted">{{ material.reason }}</p></template
          ><template v-else
            ><h3>{{ material.title }}</h3>
            <p class="material-text">{{ material.text }}</p>
            <span class="muted">{{ material.source_location }}</span></template
          >
        </article>
      </template>
      <template v-else-if="finished">
        <div class="completion">
          <Check :size="38" />
          <h2>完成了一小步。</h2>
          <p>
            本轮答对 {{ score }} /
            {{ task.questions.length }} 道题，作答已保存在服务端。
          </p>
          <p>继续获取下一任务，系统会结合最新证据和先修关系安排练习。</p>
          <div class="actions completion-actions">
            <NButton type="primary" :loading="loading" @click="emit('nextTask')"
              >获取下一任务</NButton
            ><NButton
              secondary
              @click="
                emit('update:show', false);
                emit('history');
              "
              >查看学习记录</NButton
            >
          </div>
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
          >此版本已停用，请获取新任务。<NButton text @click="emit('nextTask')"
            >重新推荐</NButton
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

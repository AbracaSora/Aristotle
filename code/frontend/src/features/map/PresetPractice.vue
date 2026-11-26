<script setup lang="ts">
import SourceExplorer from "../../components/SourceExplorer.vue";
import { computed, ref } from "vue";
import { NButton, NAlert } from "naive-ui";
import type { CourseCall, CourseQuestion, CourseFeedback } from "./course";

interface PresetTask {
  id: string; questions: CourseQuestion[]; attempts: CourseFeedback[]; next_question_key: string | null;
}
const props = defineProps<{knowledgeId: string; call: CourseCall}>();
const emit = defineEmits<{changed: []; materials:[]}>();
const task = ref<PresetTask>();
const selected = ref("");
const pendingId = ref("");
const busy = ref(false);
const error = ref("");
const question = computed(() => task.value?.questions.find(q => q.key === task.value?.next_question_key));
const feedback = ref<CourseFeedback & {attempt_id:string}>();
const showSources=ref(false);

async function run(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try { await action(); } catch (e) { error.value = e instanceof Error ? e.message : "练习读取失败，请重试"; }
  finally { busy.value = false; }
}
async function open(repeat: boolean) {
  await run(async () => {
    task.value = repeat && task.value ? await props.call<PresetTask>(
      '/tasks/' + task.value.id + '/retry-preset', 'POST',
    ) : await props.call<PresetTask>('/tasks', 'POST', {mode:'practice', knowledge_id:props.knowledgeId});
    selected.value = ""; pendingId.value = ""; feedback.value = undefined;
  });
}
async function submit() {
  const current = question.value;
  const active = task.value;
  if (!current || !active || !selected.value) return;
  await run(async () => {
    pendingId.value ||= crypto.randomUUID();
    const result = await props.call<CourseFeedback & {attempt_id:string}>('/tasks/' + active.id + '/attempts','POST',{
      question_key:current.key, selected_option_id:selected.value, submission_id:pendingId.value,
    });
    active.attempts.push(result);
    const done = new Set(active.attempts.map(a => a.question_key));
    active.next_question_key = active.questions.find(q => !done.has(q.key))?.key ?? null;
    feedback.value = result; showSources.value=false;
    selected.value = ""; pendingId.value = ""; emit("changed");
  });
}
</script>
<template>
  <section aria-label="课程预设练习">
    <NAlert v-if="error" type="warning">{{ error }}</NAlert>
    <NButton v-if="!task" :loading="busy" @click="open(false)">进入预设练习</NButton>
    <template v-else>
      <p>本轮已答 {{task.attempts.length}} / {{task.questions.length}} 题</p>
      <p v-if="feedback" role="status">{{feedback.correct ? '答对了' : '答错了'}} · 正确选项 {{feedback.answer.option_id}}。{{feedback.explanation}}</p>
      <NButton v-if="feedback" text @click="showSources=!showSources">查看本题资料与解释</NButton>
      <SourceExplorer v-if="feedback && showSources" :key="feedback.attempt_id" :knowledge-id="knowledgeId"
        :knowledge-name="task.questions.find(q=>q.key===feedback?.question_key)?.stem || knowledgeId"
        :attempt-id="feedback.attempt_id" :call="call" @materials="$emit('materials')"/>
      <form v-if="question" @submit.prevent="submit">
        <fieldset :disabled="busy || !!pendingId"><legend>{{question.stem}}</legend>
          <label v-for="o in question.options" :key="o.id"><input v-model="selected" type="radio" name="preset-option" :value="o.id"/> {{o.text}}</label>
        </fieldset>
        <NButton attr-type="submit" :disabled="!selected" :loading="busy">{{pendingId ? '重试提交' : '提交本题'}}</NButton>
      </form>
      <NButton v-else :loading="busy" @click="open(true)">重新练习并更新各题结果</NButton>
    </template>
  </section>
</template>
<style scoped>
fieldset{border:0;margin:0;padding:0}legend{font-weight:600;margin:8px 0}label{display:block;padding:6px 0}
</style>

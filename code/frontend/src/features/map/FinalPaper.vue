<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from "vue";
import { NButton, NAlert } from "naive-ui";
import type { CourseCall, CourseQuestion, CourseFeedback } from "./course";
interface PaperRef {test_id:string; version:number; status:string}
interface Paper extends PaperRef {
  questions:CourseQuestion[]; error:{message:string}|null;
  result:{score:number; passed:boolean; feedback:CourseFeedback[]; events:{event_id:string;type:"ai_test_submitted"|"knowledge_mastered";occurred_at:string}[]; learning_feedback:{summary:string;suggestions:string[];source:"ai"|"rule"}}|null;
}
const props = defineProps<{knowledgeId:string; eligible:boolean; call:CourseCall}>();
const emit = defineEmits<{changed:[]}>();
const sheets=ref<PaperRef[]>([]), paper=ref<Paper>(), choices=ref<Record<string,string>>({});
const events=computed(()=>Array.from(new Map((paper.value?.result?.events ?? []).map(e=>[e.event_id,e])).values()));
const busy=ref(false), error=ref(""), submission=ref(""), createId=ref("");
let timer: ReturnType<typeof setTimeout> | undefined;
let alive=true;
const path='/knowledge-points/'+encodeURIComponent(props.knowledgeId)+'/ai-tests';
async function run(action:()=>Promise<void>) {
  if (busy.value) return;
  busy.value=true; error.value="";
  try { await action(); } catch(e) { if(alive) error.value=e instanceof Error?e.message:"小测读取失败"; }
  finally { busy.value=false; }
}
async function read(id:string) {
  clearTimeout(timer);
  const result=await props.call<Paper>('/ai-tests/'+id);
  if (!alive) return;
  if (paper.value?.test_id !== id) { choices.value={}; submission.value=""; }
  paper.value=result;
  sheets.value=[result,...sheets.value.filter(x=>x.test_id!==id)].sort((a,b)=>b.version-a.version);
  if (result.status==='generating') timer=setTimeout(()=>run(()=>read(id)),1500);
}
async function load() {
  const rows=await props.call<{items:PaperRef[]}>(path);
  sheets.value=rows.items;
  if(rows.items.length) await read(rows.items[0].test_id);
}
async function create() {
  await run(async()=>{
    createId.value ||=crypto.randomUUID();
    const row=await props.call<PaperRef>(path,'POST',{request_id:createId.value,rules:{question_count:5,pass_score:0.8}});
    await read(row.test_id); createId.value="";
  });
}
async function submit() {
  const current=paper.value;
  if(!current || current.questions.some(q=>!choices.value[q.key])) return;
  await run(async()=>{
    submission.value ||= crypto.randomUUID();
    const result=await props.call<NonNullable<Paper['result']>>('/ai-tests/'+current.test_id+'/submit','POST',{
      submission_id:submission.value,answers:current.questions.map(q=>({question_key:q.key,selected_option_id:choices.value[q.key]})),
    });
    current.result=result; current.status='submitted'; submission.value=""; emit("changed"); await read(current.test_id);
  });
}
onMounted(()=>run(load));
onBeforeUnmount(()=>{alive=false;clearTimeout(timer);});
</script>
<template><section aria-label="最终小测">
  <h4>最终小测</h4>
  <NAlert v-if="error" type="warning">{{error}} <NButton text :disabled="busy" @click="run(load)">刷新试卷</NButton></NAlert>
  <p v-if="paper?.status==='generating'" role="status">正在生成小测…</p>
  <p v-if="paper?.error">{{paper.error.message}}</p>
  <form v-if="paper?.status==='ready'" @submit.prevent="submit">
    <fieldset v-for="q in paper.questions" :key="q.key" :disabled="busy || !!submission">
      <legend>{{q.stem}}</legend><label v-for="o in q.options" :key="o.id">
        <input v-model="choices[q.key]" type="radio" :name="q.key" :value="o.id"> {{o.text}}</label>
    </fieldset>
    <NButton attr-type="submit" :loading="busy" :disabled="paper.questions.some(q=>!choices[q.key])">{{submission?'重试提交':'提交整卷'}}</NButton>
  </form>
  <template v-if="paper?.result"><p role="status">{{paper.result.passed?'小测通过':'小测未通过'}} · {{Math.round(paper.result.score*100)}}%</p>
    <p>{{paper.result.learning_feedback.source==="ai"?"模型反馈":"规则反馈"}} · {{paper.result.learning_feedback.summary}}</p>
    <ul v-if="events.length" aria-label="本次学习记录"><li v-for="event in events" :key="event.event_id">
      {{event.type==="knowledge_mastered"?"已记录知识点掌握":"已保存整卷作答"}} ·
      <time :datetime="event.occurred_at">{{new Date(event.occurred_at).toLocaleString("zh-CN")}}</time>
    </li></ul><ul><li v-for="s in paper.result.learning_feedback.suggestions" :key="s">{{s}}</li></ul>
    <details v-for="(f,i) in paper.result.feedback" :key="f.question_key"><summary>第 {{i+1}} 题 · {{f.correct?'正确':'错误'}}</summary><p>{{paper.questions[i]?.stem}} · 正确选项 {{f.answer.option_id}}。{{f.explanation}}</p></details>
  </template>
  <NButton v-if="eligible && !sheets.some(s=>['generating','ready'].includes(s.status))" :loading="busy" @click="create">生成最终小测（5 题，80% 通过）</NButton>
  <nav v-if="sheets.length>1" aria-label="历史试卷"><NButton v-for="s in sheets" :key="s.test_id" :disabled="busy" @click="run(()=>read(s.test_id))">第 {{s.version}} 卷</NButton></nav>
</section></template>
<style scoped>fieldset{border:0;padding:0;margin:12px 0}label{display:block;padding:5px 0}</style>

<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { NAlert, NButton, NCheckbox, NInput, NSelect } from "naive-ui";
import { BookOpen, Search, Sparkles, ArrowUpRight } from "lucide-vue-next";
import type { Job } from "../types";

interface SourceHit { id:string; title:string; text:string; location:string; source_type:"public"|"personal"; material_id:string|null; external_processing_allowed:boolean; score?:number }
interface ModelStatus { enabled:boolean; generation:{configured:boolean;model:string}; embedding:{configured:boolean;model:string} }
const props = defineProps<{knowledgeId:string; knowledgeName:string; revision?:number; attemptId?:string; call:<T>(path:string,method?:string,body?:unknown)=>Promise<T>}>();
const emit = defineEmits<{materials:[]}>();
const status = ref<ModelStatus|null>(null), hits = ref<SourceHit[]>([]), selected = ref<string[]>([]);
const query = ref(props.attemptId ? "请基于来源解释本题的知识与解题思路。" : props.knowledgeName);
const mode = ref("keyword"), consent = ref(false), busy = ref(false), error = ref(""), notice = ref("");
const job = ref<Job|null>(null);
let generation = 0, timer:ReturnType<typeof setTimeout>|undefined;
function stop() { if(timer) clearTimeout(timer); timer=undefined; }
function selectDefaults() { selected.value=hits.value.filter(h=>h.external_processing_allowed).slice(0,3).map(h=>h.id); }
async function load() {
  const ticket=++generation; stop(); job.value=null; error.value=""; busy.value=false;
  try {
    const [sources,config,jobs]=await Promise.all([props.call<{items:SourceHit[]}>(`/retrieval/sources?knowledge_id=${encodeURIComponent(props.knowledgeId)}`), props.call<ModelStatus>("/model-status"), props.call<{items:Job[]}>("/jobs")]);
    if(ticket!==generation)return;
    hits.value=sources.items; status.value=config; selectDefaults();
    const previous=jobs.items.find(j=>j.kind==='live_explanation' && j.knowledge_id===props.knowledgeId && (j.attempt_id || undefined)===(props.attemptId || undefined));
    if(previous){job.value=previous;if(['queued','running'].includes(previous.status))void poll(previous.id,ticket);}
  } catch(e) {if(ticket===generation)error.value=e instanceof Error?e.message:"资料暂时无法读取";}
}
async function operation(fn:(ticket:number)=>Promise<void>) {
  if(busy.value)return; const ticket=generation; busy.value=true; error.value=""; notice.value="";
  try {await fn(ticket);} catch(e){if(ticket===generation)error.value=e instanceof Error?e.message:"请求失败，请重试";}
  finally {if(ticket===generation)busy.value=false;}
}
async function search() {await operation(async ticket=>{
  const result=await props.call<{items:SourceHit[];notice?:string;mode:string;missing_index:number}>("/retrieval/search","POST",{query:query.value, knowledge_id:props.knowledgeId, mode:mode.value, allow_external_query:consent.value});
  if(ticket!==generation)return; hits.value=result.items; selectDefaults();notice.value=result.notice || (result.items.length?"":"没有找到相关的有效来源。");
  if(result.missing_index)notice.value+=` 尚有 ${result.missing_index} 个片段没有当前模型的索引。`;
});}
async function poll(id:string,ticket=generation,count=0) {
  try {
    const result=await props.call<Job>(`/jobs/${id}`);
    if(ticket!==generation || job.value?.id!==id)return;
    job.value=result;
    if(["queued","running"].includes(result.status) && count<120)timer=setTimeout(()=>void poll(id,ticket,count+1),1000);
    else if(result.status==="succeeded" && result.kind==="live_index")notice.value=`已建立 ${result.result.indexed} 个片段索引，复用 ${result.result.reused} 个；未授权的私人资料跳过 ${result.result.skipped_private} 个。`;
  }catch(e){if(ticket===generation)error.value=e instanceof Error?e.message:"暂时无法查询处理结果";}
}
function track(result:Job) {stop();job.value=result;void poll(result.id);}
async function index() {await operation(async ticket=>{
  const result=await props.call<Job>("/retrieval/index","POST",{knowledge_id:props.knowledgeId,allow_external:consent.value});
  if(ticket===generation)track(result);
});}
async function explain() {await operation(async ticket=>{
  const result=await props.call<Job>("/explanations","POST",{knowledge_id:props.knowledgeId,query:query.value,source_keys:selected.value,allow_external:consent.value,attempt_id:props.attemptId});
  if(ticket===generation)track(result);
});}
async function dispatch() {if(!job.value)return;await operation(async ticket=>{
  const result=await props.call<Job>(`/model-jobs/${job.value!.id}/dispatch`,"POST");if(ticket===generation)track(result);
});}
function toggle(id:string,value:boolean) {selected.value=value?[...selected.value,id].slice(0,6):selected.value.filter(k=>k!==id);}
watch(()=>[props.knowledgeId,props.revision],load,{immediate:true});
onBeforeUnmount(()=>{generation++;stop();});
</script>

<template>
  <section class="source-explorer" aria-label="相关资料与模型解释">
    <header><BookOpen :size="15"/><h3>带着问题，回到资料</h3></header>
    <p class="source-description">检索当前知识点的公共资料和本人已确认讲义。引用保留原位置。</p>
    <NAlert v-if="error" type="warning" role="alert">{{error}}</NAlert>
    <div class="source-search"><NInput v-model:value="query" aria-label="资料检索问题" placeholder="想查找什么？" :maxlength="500"/><div><NSelect v-model:value="mode" aria-label="检索方式" :options="[{value:'keyword',label:'关键词'},{value:'semantic',label:'语义',disabled:!status?.embedding.configured || !status?.enabled},{value:'hybrid',label:'混合',disabled:!status?.embedding.configured || !status?.enabled}]"/><NButton :loading="busy" :disabled="busy || (!consent && mode!=='keyword')" @click="search"><template #icon><Search :size="14"/></template>查找</NButton></div></div>
    <p v-if="notice" class="source-notice" role="status">{{notice}}</p>
    <p v-if="!hits.length && !error" class="source-empty">还没有相关的已确认资料。可以添加讲义，或先完成基础诊断。</p>
    <details v-for="(hit,i) in hits" :key="hit.id" class="source-hit">
      <summary><NCheckbox :checked="selected.includes(hit.id)" :disabled="!hit.external_processing_allowed || (!selected.includes(hit.id) && selected.length>=6)" :aria-label="`选择来源：${hit.title} ${i+1}`" @click.stop @update:checked="value=>toggle(hit.id,value)"/><span><strong>{{hit.title}}</strong><small>{{hit.source_type==='public'?'公共资料':'仅本人可见'}} · {{hit.location}}</small></span><ArrowUpRight :size="13"/></summary>
      <p class="source-quote">{{hit.text}}</p><p v-if="!hit.external_processing_allowed" class="source-notice">此私人资料未授权发往模型，仍可在这里阅读和关键词检索。<button @click="emit('materials')">管理资料授权</button></p>
    </details>
    <div class="source-model-controls">
      <NCheckbox v-model:checked="consent" aria-label="允许本次模型处理"><span class="model-consent">允许将本次问题、公共资料及已单独授权的私人片段发送到配置的模型服务。私人讲义需另外逐份授权。</span></NCheckbox>
      <div class="source-buttons"><NButton size="small" :disabled="busy || !consent || !status?.embedding.configured || !status?.enabled" @click="index">建立语义索引</NButton><NButton size="small" type="primary" :disabled="busy || !consent || !selected.length || !status?.generation.configured || !status?.enabled" @click="explain"><template #icon><Sparkles :size="13"/></template>基于所选来源解释</NButton></div>
      <p v-if="!status?.embedding.configured || !status?.generation.configured" class="source-setup">{{!status?.embedding.configured?'Embedding 尚未配置。 ':''}}{{!status?.generation.configured?'生成模型尚未配置。':''}}关键词检索与规则学习可以继续。</p>
    </div>
    <div v-if="job" class="model-result" aria-live="polite">
      <p v-if="job.status==='queued' || job.status==='running'">{{job.status==='queued'?'模型任务已排队':'正在处理，学习进度不会因此改变'}}…<NButton v-if="job.status==='queued'" text size="tiny" @click="dispatch">启动处理</NButton><NButton text size="tiny" @click="poll(job.id)">刷新结果</NButton></p>
      <NAlert v-else-if="job.status==='failed'" type="warning">{{job.result.error || '处理失败，请稍后重试。'}}</NAlert>
      <template v-else-if="job.status==='succeeded' && job.kind==='live_explanation'"><span class="ai-label"><Sparkles :size="12"/>AI 辅助解释</span><p v-if="job.result.insufficient_evidence" class="source-notice">现有资料不足以支持完整结论。</p><p class="grounded-answer">{{job.result.answer}}</p><details v-for="(source,i) in job.result.sources" :key="source.id" class="answer-citation"><summary>[{{i+1}}] {{source.title}} · {{source.location}}</summary><p class="source-quote">{{source.text}}</p></details><p class="source-setup">可核对上述引用。解释不会用于判分，也不会增加掌握证据。</p></template>
    </div>
  </section>
</template>

<style scoped>
.source-explorer{padding:22px 26px;border-top:1px solid #edf0e9}.source-explorer header{display:flex;align-items:center;gap:8px;color:#52704c}.source-explorer h3{font-size:13px;font-weight:500;margin:0}.source-description,.source-empty,.source-setup{font-size:11px;line-height:1.8;color:#929b8c;margin:10px 0}.source-search{margin-top:14px}.source-search>div:last-child{display:flex;gap:8px;margin-top:8px}.source-search .n-select{flex:1;min-width:100px}.source-hit{border-bottom:1px solid #edf0e8;padding:12px 0}.source-hit summary{display:flex;align-items:center;gap:9px;cursor:pointer;list-style:none}.source-hit summary>span{flex:1;min-width:0}.source-hit strong{font-size:12px;font-weight:500;display:block;color:#52654c}.source-hit small{font-size:10px;color:#9aA18e;display:block;line-height:1.7}.source-hit summary svg{color:#8c9d83}.source-quote{font-size:12px;line-height:1.9;white-space:pre-wrap;background:#f6f8f2;border-left:2px solid #c8d5bd;padding:12px;margin:12px 0 0;color:#62705a}.source-notice{font-size:11px;line-height:1.8;color:#9a844d}.source-notice button{border:0;background:none;padding:0;color:#386647;font:inherit;text-decoration:underline;cursor:pointer}.source-model-controls{margin-top:16px}.model-consent{font-size:10px;color:#8e9885;line-height:1.8;display:block}.source-buttons{display:flex;gap:7px;flex-wrap:wrap;margin-top:12px}.model-result{margin-top:18px;border-top:1px dashed #d5ddce;padding-top:15px;font-size:12px;color:#62705c}.ai-label{display:flex;gap:5px;align-items:center;color:#6e825a;font-size:11px}.grounded-answer{line-height:1.95;white-space:pre-wrap}.answer-citation{font-size:10px;color:#819371;margin:8px 0}.answer-citation summary{cursor:pointer}.source-explorer :deep(.n-alert){font-size:11px;padding:10px}
</style>

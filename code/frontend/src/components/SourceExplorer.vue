<script setup lang="ts">
import { ref, watch } from "vue";
import { NAlert, NButton, NInput } from "naive-ui";
import { BookOpen } from "lucide-vue-next";

interface SourceHit { id: string; title: string; text: string; location: string }
const props = defineProps<{knowledgeId:string; knowledgeName:string; revision?:number; attemptId?:string; call:<T>(path:string,method?:string,body?:unknown)=>Promise<T>}>();
const emit = defineEmits<{materials:[]}>();
const hits = ref<SourceHit[]>([]);
const query = ref("");
const busy = ref(false);
const error = ref("");
let latestRequest = 0;

async function readSources(search = false) {
  const request = ++latestRequest;
  busy.value = true;
  error.value = "";
  try {
    const result = search
      ? await props.call<{items: SourceHit[]}>("/retrieval/search", "POST", {
          query: query.value.trim(), knowledge_id: props.knowledgeId, mode: "keyword", allow_external_query: false
        })
      : await props.call<{items: SourceHit[]}>(`/retrieval/sources?knowledge_id=${encodeURIComponent(props.knowledgeId)}`);
    if (request === latestRequest) hits.value = result.items;
  } catch (e) {
    if (request === latestRequest) error.value = e instanceof Error ? e.message : "资料读取失败";
  } finally {
    if (request === latestRequest) busy.value = false;
  }
}
watch(() => [props.knowledgeId, props.revision, props.attemptId], () => {
  hits.value = [];
  query.value = props.knowledgeName;
  void readSources();
}, { immediate: true });
</script>

<template>
  <section class="source-explorer" aria-label="相关资料与学习提示">
    <header><BookOpen :size="16"/><h3>相关资料</h3></header>
    <form class="source-search" @submit.prevent="readSources(!!query.trim())">
      <NInput v-model:value="query" aria-label="资料关键词" placeholder="输入资料关键词" :maxlength="500"/>
      <NButton attr-type="submit" :loading="busy">查找</NButton>
    </form>
    <NAlert v-if="error" type="warning">{{error}}</NAlert>
    <p v-else-if="!busy && !hits.length" class="source-empty">未找到相关资料。可以换个关键词，或<button @click="emit('materials')">添加讲义</button>。</p>
    <details v-for="hit in hits" :key="hit.id" class="source-hit">
      <summary><span><strong>{{hit.title}}</strong><small>{{hit.location}}</small></span></summary>
      <p class="source-quote">{{hit.text}}</p>
    </details>
    <details class="source-hit">
      <summary><strong>学习提示（预设）</strong></summary>
      <p class="source-quote">{{attemptId ? "重新圈出题目给出的条件，写下你使用的定义或公式，再与题目解析逐步核对。" : "先用自己的话解释这个知识点，再从讲义中找一个例子，检查定义的每个条件是否成立。"}}</p>
    </details>
  </section>
</template>

<style scoped>
.source-explorer{padding:22px 26px;border-top:1px solid #edf0e9}.source-explorer header{display:flex;align-items:center;gap:8px;color:#52704c}.source-explorer h3{font-size:1rem;font-weight:500;margin:0}.source-description,.source-empty,.source-setup{font-size:0.875rem;line-height:1.8;color:#61725c;margin:10px 0}.source-search{margin-top:14px}.source-search>div:last-child{display:flex;gap:8px;margin-top:8px}.source-search .n-select{flex:1;min-width:100px}.source-hit{border-bottom:1px solid #edf0e8;padding:12px 0}.source-hit summary{display:flex;align-items:center;gap:9px;cursor:pointer;list-style:none}.source-hit summary>span{flex:1;min-width:0}.source-hit strong{font-size:0.9375rem;font-weight:500;display:block;color:#52654c}.source-hit small{font-size:0.8125rem;color:#9aA18e;display:block;line-height:1.7}.source-hit summary svg{color:#8c9d83}.source-quote{font-size:0.9375rem;line-height:1.9;white-space:pre-wrap;background:#f6f8f2;border-left:2px solid #c8d5bd;padding:12px;margin:12px 0 0;color:#62705a}.source-notice{font-size:0.875rem;line-height:1.8;color:#9a844d}.source-notice button{border:0;background:none;padding:0;color:#386647;font:inherit;text-decoration:underline;cursor:pointer}.source-search{display:flex;gap:8px}.source-search .n-input{min-width:0}</style>

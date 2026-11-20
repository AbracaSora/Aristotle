<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue';
import { NButton, NAlert } from 'naive-ui';
import TerrainMap from './TerrainMap.vue';
import DemoPractice from './DemoPractice.vue';
import bank from './demo-questions.json';
import curriculum from './curriculum.json';
const props=defineProps<{call:<T>(path:string,method?:string,body?:unknown)=>Promise<T>}>();
const emit=defineEmits<{start:[id:string]; immersive:[active:boolean]}>();
const progress=ref<Record<string,{total:number;completed:number}>>({});
const error=ref('');
const activeId=ref(curriculum.subjects[0].id);
const activeSubject=computed(()=>curriculum.subjects.find(s=>s.id===activeId.value)!);
const selected=ref('');
const chapter=ref('');
const regions=computed(()=>[...new Set(activeSubject.value.nodes.map(n=>n.chapter))].map((name,index)=>{
 const nodes=activeSubject.value.nodes.filter(n=>n.chapter===name);
 const total=nodes.reduce((sum,n)=>sum+(progress.value[n.id]?.total || 0),0);
 const done=nodes.reduce((sum,n)=>sum+(progress.value[n.id]?.completed || 0),0);
 return {id:`region-${index}`,title:name,type:'章节区域',description:`探索度 ${total?Math.round(done/total*100):0}% · ${nodes.length} 个知识点`};
}));
const visibleNodes=computed(()=>chapter.value?activeSubject.value.nodes.filter(n=>n.chapter===chapter.value):regions.value);
const visibleEdges=computed(()=>{const ids=new Set(visibleNodes.value.map(n=>n.id));return chapter.value?activeSubject.value.edges.filter(([a,b])=>ids.has(a)&&ids.has(b)):[]});
function selectMap(id:string){if(!chapter.value){chapter.value=regions.value.find(n=>n.id===id)?.title || ''}else selected.value=id}

function switchSubject(id:string){activeId.value=id;selected.value='';chapter.value='';}
const practice=ref('');
watch(practice,id=>emit('immersive',!!id));
onBeforeUnmount(()=>emit('immersive',false));
const completed=ref<string[]>([]);
onMounted(()=>{try{const saved=JSON.parse(localStorage.getItem('408-resource-demo-v1') || '[]');if(Array.isArray(saved))completed.value=saved.filter(x=>typeof x==='string')}catch{};updateProgress()});
function updateProgress(){for(const [id,questions] of Object.entries(bank))progress.value[id]={total:questions.length,completed:questions.filter(q=>completed.value.includes(q.id)).length}}
function record(id:string){if(!completed.value.includes(id))completed.value.push(id);try{localStorage.setItem('408-resource-demo-v1',JSON.stringify(completed.value))}catch{error.value='浏览器无法保存进度，本次练习仍可继续。'}updateProgress()}
const practiceTitle=computed(()=>activeSubject.value.nodes.find(n=>n.id===practice.value)?.title || '知识点练习');

function status(id:string){const p=progress.value[id];return !p?.total?'pending':p.completed===p.total?'covered':p.completed?'learning':'new'}
</script>
<template><DemoPractice v-if="practice" :key="practice" :node-id="practice" :title="practiceTitle" @back="practice=''" @answer="record"/><section v-else class="curriculum"><header><p>408 · 科目学习地图</p><h1>每一步练习，都看得见</h1><p>总览展示章节区域，点击区域探索知识点；拖动地图、滚轮缩放。</p><p>资源库演示 · 灰色 未学习 · 蓝色 部分完成 · 绿色 基础已覆盖</p></header><NAlert v-if="error" type="warning">{{error}}</NAlert><div class="subject-tabs" role="tablist" aria-label="408 科目"><button v-for="subject in curriculum.subjects" :id="`tab-${subject.id}`" :key="subject.id" role="tab" :aria-selected="activeId===subject.id" aria-controls="subject-map" :class="{active:activeId===subject.id}" @click="switchSubject(subject.id)">{{subject.title}}</button></div><div id="subject-map" role="tabpanel" :aria-labelledby="`tab-${activeId}`"><div class="map-breadcrumb"><NButton v-if="chapter" @click="chapter='';selected=''">← 返回科目全图</NButton><strong>{{activeSubject.title}} / {{chapter || '章节区域'}}</strong></div><TerrainMap :subject-id="activeId" :regions="regions" :focus-region="regions.find(r=>r.title===chapter)?.id" :nodes="visibleNodes" :edges="visibleEdges" :overview="!chapter" @select="selectMap"/><article class="panel"><h2>{{activeSubject.title}} · {{activeSubject.nodes.length}} 个知识点</h2><p>按 resource 中的章节与先修关系组织；大纲映射及题目仍待正式审核。</p><div v-for="(node,index) in activeSubject.nodes.filter(n=>!chapter || n.chapter===chapter)" :key="node.id" class="curriculum-node" :class="{selected:selected===node.id}" :data-state="status(node.id)"><span class="flag">{{index+1}}</span><div><small>{{node.chapter}}</small><br/><strong>{{node.title}}</strong><p>{{progress[node.id]?.total ? `${progress[node.id].completed} / ${progress[node.id].total} 道预设题已完成` : '题目待补充'}}</p></div><NButton :disabled="!progress[node.id]?.total" @click="practice=node.id">进入练习</NButton></div></article></div></section></template>
<style scoped>.map-breadcrumb{display:flex;align-items:center;gap:20px;margin:12px 0}.subject-tabs{display:flex;gap:8px;overflow:auto;margin:22px 0}.subject-tabs button{padding:12px 20px;border:1px solid #dde4e1;border-radius:12px;background:white;white-space:nowrap;cursor:pointer;font:inherit}.subject-tabs button.active{background:#208064;color:white}.curriculum-node.selected{outline:2px solid #208064;border-radius:8px}.subject-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}.curriculum-node{display:flex;align-items:center;gap:14px;border-left:2px solid #dde4e1;padding:18px 8px}.curriculum-node>div{flex:1}.curriculum-node p{color:#687670;font-size:12px}.flag{border-radius:50%;background:#eef0f2;padding:10px}.curriculum-node[data-state=learning] .flag{background:#dbeafe;color:#1d4ed8}.curriculum-node[data-state=covered] .flag{background:#dcfce7;color:#15803d}@media(max-width:900px){.subject-grid{grid-template-columns:1fr}}</style>

<script setup lang="ts">
import MapLegend from './MapLegend.vue';
import { ref, watch, onMounted, onBeforeUnmount } from 'vue';
const props = defineProps<{ subjectId: string; nodes: {id:string;title:string;type?:string;description?:string;locked?:boolean}[]; edges: string[][]; overview?:boolean; regions: {id:string;title:string;description?:string}[]; focusRegion?:string }>();
const emit = defineEmits<{select:[id:string]}>();
const frame = ref<HTMLIFrameElement | null>(null);
function sync() {
  frame.value?.contentWindow?.postMessage({type:'aristotle-knowledge-map',seed:`408-${props.subjectId}`,overview:props.overview,focusRegion:props.focusRegion,regions:props.regions.map(n=>({id:n.id,label:n.title,type:'章节区域',description:n.description})),graph:{nodes:props.nodes.map(n=>({id:n.id,label:n.title,type:n.type || '知识点',description:n.description || n.title,locked:n.locked === true})),edges:props.edges}},window.location.origin);
}
function receive(event:MessageEvent) {
  if(event.origin!==window.location.origin || event.source!==frame.value?.contentWindow)return;
  if(event.data?.type==='knowledge-map-node-selected' && props.nodes.some(n=>n.id===event.data.id && !n.locked))emit('select',event.data.id);
}
watch(()=>[props.subjectId,props.focusRegion,props.nodes],sync,{deep:true});
onMounted(()=>window.addEventListener('message',receive));
onBeforeUnmount(()=>window.removeEventListener('message',receive));
</script>
<template><div class="atlas-frame"><span class="atlas-compass" aria-hidden="true">N<br/>◇<br/>│</span><iframe ref="frame" src="/knowledge-map-prototype.html?embedded=1" title="科目随机地形知识地图" @load="sync" /><MapLegend :overview="overview"/><span class="atlas-hint">拖动探索 · 滚轮缩放</span></div></template>
<style scoped>.atlas-frame{position:relative;border-radius:18px;overflow:hidden;border:1px solid #d8d0b9;box-shadow:0 8px 30px #173e4b14}.atlas-compass{position:absolute;right:24px;top:22px;color:#eee4c5;text-align:center;font:18px Georgia;pointer-events:none}.atlas-hint{position:absolute;right:18px;bottom:20px;font-size:11px;letter-spacing:.1em;color:#f2ead2;background:#173e4bbd;padding:8px 12px;border-radius:20px;pointer-events:none}iframe{width:100%;height:650px;border:0;border-radius:16px;background:#e6e9dc}@media(max-width:700px){iframe{height:480px}}</style>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { NAlert, NButton, NInput, NSelect } from "naive-ui";
import { ArrowRight, Focus, Minus, Plus, Search, Route, Map as MapIcon, Compass } from "lucide-vue-next";
import { layoutKnowledge, relatedKnowledge } from "../knowledgeLayout";
import { levelLabels, stateLabels } from "../types";
import type { KnowledgeGraph, KnowledgeState, LearningContext, LearningState, Scope } from "../types";
import SourceExplorer from "./SourceExplorer.vue";

interface MapData extends KnowledgeGraph { states: KnowledgeState[]; window_days: number }
const props = defineProps<{
  detailsOnly?: boolean;
  scopes: Scope[]; context: LearningContext | null; state: LearningState | null;
  loading: boolean; call: <T>(path: string, method?: string, body?: unknown) => Promise<T>;
}>();
const emit = defineEmits<{ choose: [id: string]; start: [id: string]; materials: []; details: [] }>();
const data = ref<MapData | null>(null), selected = ref(""), search = ref("");
const mapError = ref(""), picked = ref<string | null>(null), focusPath = ref(true);
const detailTab = ref<"knowledge" | "task">("knowledge");
const zoom = ref(1), pan = ref({ x: 0, y: 0 });
let generation = 0;
let drag: { x: number; y: number; px: number; py: number } | null = null;
const surface = ref<SVGSVGElement | null>(null);
const sourceRevision = ref(0);
const prototypeFrame = ref<HTMLIFrameElement | null>(null);
const viewport = ref({width:860,height:540});
let resizeObserver: ResizeObserver | undefined;
const currentTarget = computed(() => props.context?.current_task?.knowledge_id || "");
const graph = computed(() => {
  try { return layoutKnowledge(data.value?.nodes || []); }
  catch { return { nodes: [], edges: [], width: 860, height: 540 }; }
});
const positions = computed(() => new Map(graph.value.nodes.map((n) => [n.id, n])));
const current = computed(() => data.value?.nodes.find((n) => n.id === selected.value));
const evidence = computed(() => data.value?.states.find((s) => s.knowledge_id === selected.value));
const related = computed(() => relatedKnowledge(data.value?.nodes || [], selected.value));
const stateById = computed(() => new Map(data.value?.states.map((s) => [s.knowledge_id, s]) || []));
const matches = computed(() => data.value?.nodes.filter((n) => n.name.toLowerCase().includes(search.value.toLowerCase())) || []);
const scopeNodes = computed(() => new Set(props.context?.selected_scope?.knowledge_ids || []));
const activeNodes = computed(() => new Set([selected.value, ...related.value.ancestors, ...related.value.descendants]));
function label(id: string) { return data.value?.nodes.find((n) => n.id === id)?.name || id; }
function sendPrototypeData() {
  if (!data.value || !prototypeFrame.value?.contentWindow) return;
  prototypeFrame.value.contentWindow.postMessage({
    type: "aristotle-knowledge-map",
    graph: {
      nodes: data.value.nodes.map((node) => ({ id: node.id, label: node.name, type: "知识点", description: "沿先修关系完成本知识点的学习与练习。" })),
      edges: data.value.nodes.flatMap((node) => node.prerequisites.map((parent) => [parent, node.id])),
    },
  }, "*");
}
function handlePrototypeSelection(event: MessageEvent<{ type?: string; id?: string }>) {
  if (event.data?.type === "knowledge-map-node-selected" && event.data.id && data.value?.nodes.some((node) => node.id === event.data.id)) { select(event.data.id); emit('details'); }
}
function stateLabel(id: string) { const s = stateById.value.get(id); return s ? stateLabels[s.status] : "证据不足"; }
function status(id: string) { return stateById.value.get(id)?.status || "insufficient"; }
function fitAll() {
  const nodes=graph.value.nodes;
  if(!nodes.length)return;
  const xs=nodes.map(n=>n.x),ys=nodes.map(n=>n.y);
  const left=Math.min(...xs),right=Math.max(...xs),top=Math.min(...ys),bottom=Math.max(...ys);
  zoom.value=Math.min(1,(viewport.value.width-35)/(right-left+180),(viewport.value.height-70)/(bottom-top+180));
  pan.value={x:(graph.value.width/2-(left+right)/2)*zoom.value,y:(graph.value.height/2-(top+bottom)/2)*zoom.value};
}
function centerSelected() {
  const node=positions.value.get(selected.value);if(!node){fitAll();return;}
  zoom.value=1;pan.value={x:graph.value.width/2-node.x,y:graph.value.height/2-node.y};
}
function resetView() { if(focusPath.value && (graph.value.nodes.length>8 || viewport.value.width<500))centerSelected();else fitAll(); }
function select(id: string) { selected.value = id; detailTab.value = "knowledge";if(focusPath.value && graph.value.nodes.length>8)centerSelected(); }
function switchView(focus:boolean){focusPath.value=focus;resetView();}
function focusTarget() { select(currentTarget.value || props.context?.selected_scope?.knowledge_ids[0] || data.value?.nodes[0]?.id || ""); resetView(); }
function scale(amount: number) { zoom.value = Math.max(.015, Math.min(3, zoom.value * amount)); }
function wheel(event: WheelEvent) { if (event.ctrlKey || event.metaKey) { event.preventDefault(); scale(event.deltaY > 0 ? .9 : 1.1); } }
function pointerDown(event: PointerEvent) {
  if ((event.target as Element).closest("[data-knowledge-node]")) return;
  drag = { x: event.clientX, y: event.clientY, px: pan.value.x, py: pan.value.y };
  surface.value?.setPointerCapture(event.pointerId);
}
function pointerMove(event: PointerEvent) {
  if (!drag || !surface.value) return;
  const ratio = viewport.value.width / surface.value.getBoundingClientRect().width;
  pan.value = { x: drag.px + (event.clientX - drag.x) * ratio, y: drag.py + (event.clientY - drag.y) * ratio };
}
function edgePath(source: string, target: string) {
  const a = positions.value.get(source)!, b = positions.value.get(target)!;
  return `M${a.x + 29},${a.y} C${a.x + 126},${a.y} ${b.x - 126},${b.y} ${b.x - 34},${b.y}`;
}
async function load() {
  const ticket = ++generation;
  try {
    const result = await props.call<MapData>("/knowledge-map");
    if (ticket !== generation) return;
    layoutKnowledge(result.nodes);
    data.value = result; mapError.value = ""; sourceRevision.value++;
    sendPrototypeData();
    if (!result.nodes.some((n) => n.id === selected.value)) focusTarget();
  } catch (e) { if (ticket === generation) mapError.value = e instanceof Error ? e.message : "地图暂时无法加载"; }
}
watch(() => [props.state, props.context?.selected_scope?.id], load, { immediate: true });
watch(() => props.context?.selected_scope?.id, () => { picked.value = null; focusTarget(); detailTab.value = "task"; });
onMounted(()=>{window.addEventListener("message", handlePrototypeSelection);resizeObserver=new ResizeObserver(entries=>{const box=entries[0]?.contentRect;if(box && box.width>0 && box.height>0){viewport.value={width:box.width,height:box.height};resetView();}});if(surface.value)resizeObserver.observe(surface.value);});
onBeforeUnmount(() => { generation++;window.removeEventListener("message", handlePrototypeSelection);resizeObserver?.disconnect(); });
</script>

<template>
  <section class="learning-map" aria-label="知识地图与学习路径">
    <header class="map-heading">
      <div><span class="eyebrow">YOUR KNOWLEDGE, CONNECTED</span><h1>看见联系，找到下一步。</h1><p>沿着知识的联系学习，用每一次作答检验理解。</p></div>
      <div class="map-scope"><label for="map-scope">学习范围</label><NSelect id="map-scope" aria-label="学习范围" :value="picked || context?.selected_scope?.id" :options="scopes.map(s => ({label:s.title, value:s.id, disabled:!s.published}))" @update:value="picked = $event"/><NButton :disabled="loading || !picked || picked === context?.selected_scope?.id" @click="picked && emit('choose', picked)">确认范围</NButton></div>
    </header>
    <NAlert v-if="mapError" type="warning" role="alert">{{ mapError }} <NButton text @click="load">重新加载地图</NButton></NAlert>
    <div :class="['map-layout', 'separate-map-view', { 'details-only': detailsOnly }]">
      <div v-show="!detailsOnly" class="map-canvas-column knowledge-terrain">
        <div class="map-toolbar">
          <div class="map-view-switch"><button :class="{active: focusPath}" @click="switchView(true)"><Route :size="15"/>当前路径</button><button :class="{active: !focusPath}" @click="switchView(false)"><MapIcon :size="15"/>浏览全图</button></div>
          <div class="map-search"><Search :size="15"/><NInput v-model:value="search" aria-label="查找知识点" placeholder="查找知识点…" clearable/></div>
        </div>
        <div v-if="search" class="map-search-results" aria-live="polite"><button v-for="n in matches" :key="n.id" @click="select(n.id); search = ''; resetView()">{{n.name}}<ArrowRight :size="14"/></button><p v-if="!matches.length">当前知识图中没有匹配的知识点。</p></div>
        <div class="map-surface">
          <iframe ref="prototypeFrame" class="prototype-frame" src="/knowledge-map-prototype.html?embedded=1" title="知识地图" @load="sendPrototypeData"/>
          <svg ref="surface" :viewBox="`0 0 ${viewport.width} ${viewport.height}`" role="group" aria-label="先修关系图。选择知识点查看证据；可拖动，使用缩放按钮或按住 Ctrl 滚轮缩放。" @pointerdown="pointerDown" @pointermove="pointerMove" @pointerup="drag = null" @pointercancel="drag = null" @wheel="wheel">
            <defs><pattern id="map-dots" width="24" height="24" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1" fill="#d9e3db"/></pattern><marker id="map-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="context-stroke"/></marker></defs>
            <rect width="100%" height="100%" fill="url(#map-dots)"/>
            <g :transform="`translate(${pan.x + viewport.width / 2} ${pan.y + viewport.height / 2}) scale(${zoom}) translate(${-graph.width / 2} ${-graph.height / 2})`">
              <path v-for="edge in graph.edges" :key="`${edge.source}-${edge.target}`" :d="edgePath(edge.source,edge.target)" :class="['map-edge', {connected: activeNodes.has(edge.source) && activeNodes.has(edge.target), subdued: focusPath && !(activeNodes.has(edge.source) && activeNodes.has(edge.target))}]" marker-end="url(#map-arrow)"/>
              <g v-for="node in graph.nodes" :key="node.id" data-knowledge-node :transform="`translate(${node.x} ${node.y})`" :class="['map-node', status(node.id), {selected:node.id === selected, target:node.id === currentTarget, subdued:focusPath && !activeNodes.has(node.id), outside:context?.selected_scope && !scopeNodes.has(node.id)}]" role="button" tabindex="0" :aria-label="`${node.name}，${stateLabel(node.id)}${node.id === currentTarget ? '，当前学习目标' : ''}`" :aria-pressed="node.id === selected" @click="select(node.id)" @keydown.enter.prevent="select(node.id)" @keydown.space.prevent="select(node.id)">
                <title>{{node.name}} · {{stateLabel(node.id)}}</title>
                <circle class="map-node-halo" r="42"/><path class="map-node-mountain" d="M-28 17L-8-18L2 2L13-27L30 17Z"/><path class="map-node-snow" d="M-8-18L2 2L13-27L8-7L2-1Z"/><path class="map-node-flag" d="M2-28V-38L15-34L2-30Z"/><circle class="map-node-ring" r="31"/>
                <text class="map-node-name" y="58" text-anchor="middle">{{node.name.length > 13 ? node.name.slice(0,12)+'…' : node.name}}</text>
                <text class="map-node-status" y="79" text-anchor="middle">{{node.id === currentTarget ? '正在这里学习' : stateLabel(node.id)}}</text>
                <g v-if="node.id === currentTarget" transform="translate(22 -29)"><circle r="9" fill="#226c52"/><path d="M-3 0H3M0-3L3 0L0 3" stroke="white" fill="none" stroke-width="1.3"/></g>
              </g>
            </g>
          </svg>
          <div class="map-orientation"><span class="eyebrow">从基础，走向应用</span><p>道路表示知识先修关系 <ArrowRight :size="13"/></p></div>
          <div class="map-controls"><button aria-label="放大地图" @click="scale(1.2)"><Plus :size="17"/></button><span>{{Math.round(zoom*100)}}%</span><button aria-label="缩小地图" @click="scale(1/1.2)"><Minus :size="17"/></button><button aria-label="定位当前学习目标" @click="focusTarget"><Focus :size="17"/></button></div>
          <p v-if="!data && !mapError" class="map-loading" role="status">正在读取知识关系与学习证据…</p>
          <p v-else-if="data && !data.nodes.length" class="map-loading">知识结构尚未发布，请联系内容维护者。</p>
        </div>
        <footer class="map-legend"><span><i class="dot provisional"/>初步掌握</span><span><i class="dot needs_review"/>待巩固</span><span><i class="dot insufficient"/>证据不足</span><small>最近 {{data?.window_days || 14}} 天 · 阅读不会增加掌握证据</small></footer>
        <div class="map-accessible-list"><label>直接定位知识点<NSelect :value="selected || null" :options="data?.nodes.map(n => ({label:n.name, value:n.id})) || []" @update:value="select"/></label></div>
      </div>
      <aside v-show="detailsOnly" class="map-inspector" aria-label="知识点详情与学习安排">
        <div class="inspector-tabs"><button :class="{active:detailTab==='knowledge'}" @click="detailTab='knowledge'"><Compass :size="16"/>知识点</button><button :class="{active:detailTab==='task'}" @click="detailTab='task'"><Route :size="16"/>当前安排<span v-if="context?.current_task" class="task-dot"/></button></div>
        <template v-if="detailTab === 'knowledge' && current">
          <div class="inspector-intro"><span class="eyebrow">KNOWLEDGE / {{String(graph.nodes.findIndex(n => n.id===selected)+1).padStart(2,'0')}}</span><h2>{{current.name}}</h2><span :class="['evidence-badge',evidence?.status || 'insufficient']">{{stateLabel(selected)}}</span><p>{{evidence?.evidence_count || 0}} 道不同题目的有效证据<span v-if="evidence?.correct_rate !== null && evidence?.correct_rate !== undefined"> · {{Math.round(evidence.correct_rate*100)}}% 答对</span></p></div>
          <div class="inspector-section"><h3>从认知活动看证据</h3><p class="inspector-note">标签描述任务要求；各维度分别收集证据。</p><div v-for="c in evidence?.cognitive || []" :key="c.level" class="cognitive-evidence"><div><strong>{{levelLabels[c.level]}}</strong><span>{{c.count}} 题 · {{c.evidence_status === 'insufficient' ? '证据不足' : Math.round((c.correct_rate || 0)*100)+'% 答对'}}</span></div><div class="evidence-track"><i :class="{uncertain:c.evidence_status==='insufficient'}" :style="{width: c.count ? `${Math.max(5,(c.correct_rate || 0)*100)}%` : '0%'}"/></div></div></div>
          <div class="inspector-section relationships"><h3>知识之间的联系</h3><p v-if="!current.prerequisites.length" class="inspector-note">这是当前图中的基础知识点。</p><button v-for="id in current.prerequisites" :key="id" @click="select(id)"><span>先修</span>{{label(id)}}<ArrowRight :size="14"/></button><button v-for="n in data?.nodes.filter(n => n.prerequisites.includes(selected)) || []" :key="n.id" @click="select(n.id)"><span>后续</span>{{n.name}}<ArrowRight :size="14"/></button><p v-if="evidence?.unmet_prerequisites.length" class="prerequisite-note">先修尚未满足：{{evidence.unmet_prerequisites.map(label).join('、')}}。可以补测，后续学习仍遵循先修约束。</p></div>
          <div class="inspector-cta"><NButton type="primary" block :disabled="loading || !context?.selected_scope || !scopeNodes.has(selected)" @click="emit('start',selected); detailTab='task'">{{!context?.diagnostic ? '从诊断了解起点' : context.diagnostic.status === 'active' ? '继续当前诊断' : '安排此知识点的学习'}}<template #icon><ArrowRight :size="15"/></template></NButton><p v-if="!context?.selected_scope">先在上方选择学习范围。</p><p v-else-if="!scopeNodes.has(selected)">该知识点不在当前范围中，请先切换范围。</p></div>
          <SourceExplorer :key="selected" :knowledge-id="selected" :knowledge-name="current.name" :revision="sourceRevision" :call="call" @materials="emit('materials')"/>
        </template>
        <div v-else-if="detailTab==='knowledge'" class="inspector-section"><p>选择地图上的知识点，查看证据与下一步。</p></div>
        <div v-show="detailTab==='task'" class="inspector-workflow"><slot name="task"/></div>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.map-heading{display:flex;justify-content:space-between;align-items:end;gap:25px;margin:8px 0 28px}.map-heading h1{font-size:1.9375rem;font-weight:500;letter-spacing:-1px;margin:10px 0}.map-heading p{color:#738377;font-size:1rem;margin:0}.map-scope{display:flex;gap:10px;align-items:center;max-width:420px;width:43%;font-size:0.9375rem}.map-scope label{white-space:nowrap}.map-scope .n-select{min-width:150px}.map-layout{display:grid;grid-template-columns:minmax(0,1fr) 350px;border:1px solid #dce6de;background:#fcfdf9;border-radius:15px;overflow:hidden;box-shadow:0 8px 35px #28553e06}.map-canvas-column{min-width:0;position:relative}.map-toolbar{padding:20px 22px;display:flex;justify-content:space-between;gap:12px;border-bottom:1px solid #e7ece6}.map-view-switch{display:flex;background:#edf2eb;border-radius:8px;padding:3px;gap:3px}.map-view-switch button,.inspector-tabs button{border:0;display:flex;gap:7px;align-items:center;padding:8px 12px;background:transparent;color:#768176;font:inherit;font-size:0.9375rem;cursor:pointer;border-radius:6px;white-space:nowrap}.map-view-switch button.active{background:white;box-shadow:0 1px 4px #203c2510;color:#31593e}.map-search{display:flex;align-items:center;gap:6px;max-width:200px;color:#8e9b8c}.map-search :deep(.n-input){background:transparent;--n-border:none!important;--n-border-hover:none!important;--n-border-focus:none!important;--n-box-shadow-focus:none!important}.map-search-results{position:absolute;right:20px;top:65px;z-index:3;background:white;box-shadow:0 8px 25px #1c3b2418;max-height:250px;overflow:auto;padding:12px;min-width:200px;border-radius:8px}.map-search-results button{display:flex;justify-content:space-between;gap:20px;width:100%;border:0;background:white;padding:10px;color:#365441;cursor:pointer}.map-surface{position:relative;min-height:500px;overflow:hidden}.map-surface > svg{display:block;width:100%;height:560px;touch-action:none;cursor:grab}.map-surface > svg:active{cursor:grabbing}.map-edge{fill:none;stroke:#c9d7cb;stroke-width:1.8;transition:opacity .2s}.map-edge.connected{stroke:#66937a;stroke-width:2.2}.subdued{opacity:.2}.map-node{cursor:pointer;outline:none;transition:opacity .2s}.map-node-ring{fill:#fcfdf9;stroke:#c2cfc3;stroke-width:1.8}.map-node-core{fill:#c0ccc2}.map-node-halo{fill:transparent;stroke:transparent}.map-node.selected .map-node-halo{fill:#e9f0e5;stroke:#afc4aa;stroke-dasharray:3 5}.map-node:focus-visible .map-node-halo{stroke:#274f37;stroke-width:3}.map-node.selected .map-node-ring{stroke:#568168;stroke-width:2}.map-node.provisional .map-node-ring{fill:#e4efe4;stroke:#6b9b76}.map-node.provisional .map-node-core{fill:#4b865b}.map-node.needs_review .map-node-ring{fill:#fcf4e2;stroke:#bd9b50}.map-node.needs_review .map-node-core{fill:#ba9341}.map-node-name{fill:#334c3b;font-size:1.125rem;font-weight:500;pointer-events:none}.map-node-status{fill:#596c54;font-size:0.875rem;pointer-events:none}.map-node.outside .map-node-ring{stroke-dasharray:4 4}.map-orientation{position:absolute;left:26px;top:26px;pointer-events:none}.map-orientation p{display:flex;align-items:center;gap:6px;font-size:0.875rem;color:#61725c;margin:7px 0}.map-controls{position:absolute;right:20px;bottom:20px;display:flex;gap:5px;align-items:center;background:white;border:1px solid #e2e8de;border-radius:8px;padding:5px;color:#7c8978;font-size:0.875rem}.map-controls button{background:white;border:0;color:#60765d;padding:5px;cursor:pointer;display:flex}.map-legend{padding:20px 24px;border-top:1px solid #e7ece6;display:flex;gap:17px;flex-wrap:wrap;font-size:0.875rem;color:#748070;align-items:center}.map-legend span{display:flex;gap:6px;align-items:center}.map-legend small{margin-left:auto;color:#97a18f}.dot{width:7px;height:7px;border-radius:50%;background:#bdc9bd;display:inline-block}.dot.provisional{background:#5a8f62}.dot.needs_review{background:#bd964a}.map-loading{position:absolute;top:45%;width:100%;text-align:center;color:#8b9787}.map-inspector{border-left:1px solid #dce6de;background:#fff;max-height:850px;overflow-y:auto}.inspector-tabs{display:flex;gap:15px;padding:13px 23px;border-bottom:1px solid #edf0e9;position:sticky;top:0;background:#fffffff5;z-index:2}.inspector-tabs button{border-radius:0;padding:12px 0}.inspector-tabs button.active{color:#305b3f;box-shadow:0 2px #45754f}.task-dot{height:5px;width:5px;border-radius:50%;background:#c3a265}.inspector-intro{padding:27px 27px 18px}.inspector-intro h2{margin:12px 0;font-size:1.4375rem;font-weight:500}.inspector-intro p,.inspector-note{font-size:0.875rem;line-height:1.8;color:#596c54}.evidence-badge{font-size:0.875rem;padding:4px 8px;border-radius:5px;color:#809079;background:#f0f3eb}.evidence-badge.provisional{background:#eaf3e6;color:#5a7f4a}.evidence-badge.needs_review{background:#fbf2df;color:#a28235}.inspector-section{padding:20px 27px;border-top:1px solid #eef0eb}.inspector-section h3{font-size:1rem;font-weight:500;margin:0}.cognitive-evidence{margin:15px 0}.cognitive-evidence>div:first-child{display:flex;justify-content:space-between;font-size:0.875rem;margin-bottom:7px}.cognitive-evidence strong{font-weight:500;color:#5b7056}.cognitive-evidence span{color:#929d8c}.evidence-track{height:4px;border-radius:3px;background:#edf1e8;overflow:hidden}.evidence-track i{height:100%;display:block;background:#88a27a;border-radius:3px}.evidence-track i.uncertain{background:repeating-linear-gradient(90deg,#c2ceba 0 4px,transparent 4px 7px)}.relationships button{display:flex;gap:10px;align-items:center;font:inherit;font-size:0.9375rem;color:#4c6748;padding:10px 0;border:0;background:none;width:100%;text-align:left;cursor:pointer}.relationships button span{font-size:0.8125rem;color:#9ca391}.relationships button svg{margin-left:auto}.prerequisite-note{font-size:0.875rem;line-height:1.8;color:#a0874a;background:#fcf8ed;padding:10px;border-radius:6px}.inspector-cta{padding:0 27px 23px}.inspector-cta p{font-size:0.875rem;color:#929c8c;line-height:1.7}.inspector-workflow{padding:15px}.inspector-workflow :deep(.workflow-panel){padding:10px;border:0;box-shadow:none;background:transparent}.inspector-workflow :deep(.flow-focus){padding:15px}.map-accessible-list{padding:0 23px 18px;max-width:320px}.map-accessible-list label{font-size:0.8125rem;color:#95a18d}.map-accessible-list .n-select{margin-top:5px}@media(min-width:1450px){.map-layout{grid-template-columns:minmax(0,1fr) 375px}.map-surface > svg{height:610px}}@media(max-width:1100px){.map-heading{display:block}.map-scope{margin-top:20px;width:100%;max-width:500px}.map-layout{grid-template-columns:minmax(0,1fr) 310px}.map-toolbar{flex-wrap:wrap}.map-legend small{margin-left:0}}@media(max-width:800px){.map-layout{grid-template-columns:1fr}.map-inspector{border-left:0;border-top:1px solid #dce6de;max-height:none}.map-surface > svg{height:370px}.map-surface{min-height:370px}.map-heading h1{font-size:1.625rem}.map-toolbar{padding:14px}.map-legend{padding:14px;gap:12px}.map-orientation{left:18px;top:18px}}
 .knowledge-terrain .map-surface{background:radial-gradient(ellipse at 52% 54%,#dcecc5 0%,#b6d2bb 42%,#6c9aa0 100%)}
.knowledge-terrain .map-surface:before{content:"";position:absolute;inset:0;opacity:.3;background-image:radial-gradient(circle at 20% 30%,#fff8 0 1px,transparent 2px),radial-gradient(circle at 72% 65%,#284f4a55 0 1px,transparent 2px);background-size:27px 27px,41px 41px;pointer-events:none}
.knowledge-terrain .map-edge{stroke:#557e73;stroke-width:7;stroke-linecap:round;stroke-dasharray:1 10;opacity:.68}.knowledge-terrain .map-edge.connected{stroke:#d39a42;stroke-width:9;opacity:1}.knowledge-terrain .map-node-mountain{fill:#496b62;stroke:#243f3b;stroke-width:1.5}.knowledge-terrain .map-node-snow{fill:#eef3e6;opacity:.92;pointer-events:none}.knowledge-terrain .map-node-flag{fill:#e47e62;stroke:#6a4139;stroke-width:1;pointer-events:none}.knowledge-terrain .map-node-ring{fill:none;stroke:#f1df9a;stroke-width:2}.knowledge-terrain .map-node-core{display:none}.knowledge-terrain .map-node-name{fill:#173d39;font-weight:650;paint-order:stroke;stroke:#eef4e8;stroke-width:4px}.knowledge-terrain .map-node-status{fill:#234f48;paint-order:stroke;stroke:#e2efd8;stroke-width:3px}
 .prototype-frame{position:absolute;inset:0;width:100%;height:100%;min-height:560px;border:0;z-index:1;background:#6c9aa0}.map-surface>svg{visibility:hidden}.map-surface>.map-orientation,.map-surface>.map-controls,.map-surface>.map-loading{z-index:3}.map-surface>.map-orientation{display:none}
.map-layout{grid-template-columns:minmax(0,1fr) clamp(440px,40%,580px)}
.map-inspector{min-width:0}
.map-toolbar{flex-wrap:wrap}
@media(max-width:1100px){
  .map-layout{grid-template-columns:1fr}
  .map-inspector{border-left:0;border-top:1px solid #dce6de;max-height:none}
}
.map-layout.separate-map-view{grid-template-columns:minmax(0,1fr)}
.separate-map-view .map-inspector{border:0;max-height:none;overflow:visible}
</style>

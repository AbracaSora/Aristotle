<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { NButton, NAlert } from 'naive-ui';
import TerrainMap from './TerrainMap.vue';
import { courseLabel, courseState, type CourseCall, type Subject, type CourseProgress } from './course';

const props = defineProps<{call: CourseCall}>();
const emit = defineEmits<{start: [id: string]}>();
const subjects = ref<Subject[]>([]);
const progress = ref<Record<string, CourseProgress>>({});
const subjectId = ref('');
const chapterId = ref('');
const loading = ref(true);
const error = ref('');
const subject = computed(() => subjects.value.find(item => item.id === subjectId.value));
const chapter = computed(() => subject.value?.chapters.find(item => item.id === chapterId.value));
const points = computed(() => chapter.value?.knowledge_points ?? []);
const names = computed(() => new Map(subjects.value.flatMap(s => s.chapters.flatMap(c =>
  c.knowledge_points.map(p => [p.id, p.name] as const)))));
const regions = computed(() => (subject.value?.chapters ?? []).map(c => ({
  id: c.id, title: c.name, description: c.knowledge_points.length + ' 个知识点',
})));
const visibleNodes = computed(() => chapter.value ? points.value.map(p => ({
  id: p.id, title: p.name, description: courseLabel(progress.value[p.id]), locked: !progress.value[p.id]?.unlocked,
  color: courseState(progress.value[p.id]).color,
})) : regions.value);
const edges = computed(() => {
  const visible = new Set(points.value.map(p => p.id));
  return points.value.flatMap(p => p.prerequisite_ids.filter(id => visible.has(id)).map(id => [id, p.id]));
});
async function load() {
  loading.value = true;
  error.value = '';
  try {
    const [catalog, rows] = await Promise.all([
      props.call<Subject[]>('/subjects'), props.call<CourseProgress[]>('/progress'),
    ]);
    subjects.value = catalog;
    progress.value = Object.fromEntries(rows.map(p => [p.knowledge_id, p]));
    if (!catalog.some(s => s.id === subjectId.value)) subjectId.value = (catalog.find(s => s.chapters.length) ?? catalog[0])?.id ?? '';
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '课程读取失败';
  } finally { loading.value = false; }
}
function select(id: string) {
  if (!chapter.value) chapterId.value = id;
  else if (progress.value[id]?.unlocked) emit('start', id);
}
onMounted(load);
</script>

<template>
  <section aria-label="408 课程地图">
    <h1>学习地图</h1>
    <p v-if="loading" role="status">正在读取课程进度…</p>
    <NAlert v-else-if="error" type="warning">{{ error }} <NButton text @click="load">重新加载</NButton></NAlert>
    <p v-else-if="!subject">还没有发布的课程。可到学习中心进行诊断。</p>
    <template v-else>
      <nav class="subject-tabs" aria-label="科目">
        <button v-for="s in subjects" :key="s.id" :class="{active: s.id === subjectId}"
          :aria-pressed="s.id === subjectId" @click="subjectId=s.id; chapterId=''">{{ s.name }}</button>
      </nav>
      <div class="map-breadcrumb">
        <NButton v-if="chapter" @click="chapterId=''">返回章节</NButton>
        <strong>{{ subject.name }} / {{ chapter?.name || '全部章节' }}</strong>
      </div>
      <p v-if="!subject.chapters.length">本科目暂无已发布章节。</p>
      <p v-else-if="chapter && !points.length">本章节暂无已发布知识点。</p>
      <TerrainMap v-else :subject-id="subject.id" :regions="regions" :nodes="visibleNodes" :focus-region="chapterId"
        :edges="edges" :overview="!chapter" @select="select" />
      <nav v-if="!chapter" class="subject-tabs" aria-label="选择章节">
        <button v-for="c in subject.chapters" :key="c.id" @click="select(c.id)">{{ c.name }}</button>
      </nav>
      <article v-else class="panel">
        <div v-for="p in points" :key="p.id" class="curriculum-node">
          <div><strong>{{ p.name }}</strong><p>{{ courseLabel(progress[p.id]) }} ·
            已完成 {{ progress[p.id]?.completed_count ?? 0 }} / {{ progress[p.id]?.total_count ?? 0 }} 题</p>
            <p v-if="progress[p.id]?.unmet_prerequisite_ids.length">待达标先修：
              {{ progress[p.id].unmet_prerequisite_ids.map(id => names.get(id) ?? id).join('、') }}</p>
          </div>
          <NButton :disabled="!progress[p.id]?.unlocked" @click="select(p.id)">进入学习</NButton>
        </div>
      </article>
    </template>
  </section>
</template>
<style scoped>.map-breadcrumb{display:flex;align-items:center;gap:20px;margin:12px 0}.subject-tabs{display:flex;gap:8px;overflow:auto;margin:22px 0}.subject-tabs button{padding:12px 20px;border:1px solid #dde4e1;border-radius:12px;background:white;white-space:nowrap;cursor:pointer;font:inherit}.subject-tabs button.active{background:#208064;color:white}.curriculum-node.selected{outline:2px solid #208064;border-radius:8px}.subject-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}.curriculum-node{display:flex;align-items:center;gap:14px;border-left:2px solid #dde4e1;padding:18px 8px}.curriculum-node>div{flex:1}.curriculum-node p{color:#687670;font-size:12px}.flag{border-radius:50%;background:#eef0f2;padding:10px}.curriculum-node[data-state=learning] .flag{background:#dbeafe;color:#1d4ed8}.curriculum-node[data-state=covered] .flag{background:#dcfce7;color:#15803d}.curriculum-node.locked{opacity:.5;filter:grayscale(1)}.curriculum-node.locked .flag{background:#e5e7eb;color:#6b7280}@media(max-width:900px){.subject-grid{grid-template-columns:1fr}}</style>

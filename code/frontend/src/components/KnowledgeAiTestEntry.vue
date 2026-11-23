<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { NAlert, NButton, NModal } from "naive-ui";

const props = defineProps<{
  knowledgeId: string;
  knowledgeName: string;
  unlocked: boolean;
  revision: number;
  call: <T>(path: string, method?: string, body?: unknown) => Promise<T>;
}>();
const loading = ref(false);
const error = ref("");
const progress = ref<{ total: number; completed: number } | null>(null);
const showIntro = ref(false);
let request = 0;
const eligible = computed(() => props.unlocked && !loading.value && !error.value &&
  !!progress.value && progress.value.total > 0 && progress.value.completed >= progress.value.total);
const hint = computed(() => {
  if (!props.unlocked) return "掌握前驱知识点后解锁。";
  if (loading.value) return "正在检查预设题完成情况…";
  if (error.value) return "暂时无法确认小测资格。";
  if (!progress.value?.total) return "该知识点的预设题尚未准备好。";
  return eligible.value ? "基础练习已完成，可查看 AI 小测说明。" :
    `预设题已完成 ${progress.value.completed} / ${progress.value.total}，全部完成后开放小测。`;
});
async function refresh() {
  const ticket = ++request;
  loading.value = true;
  error.value = "";
  progress.value = null;
  showIntro.value = false;
  try {
    const result = await props.call<Record<string, { total: number; completed: number }>>("/curriculum-progress");
    if (ticket === request) progress.value = result[props.knowledgeId] ?? null;
  } catch {
    if (ticket === request) error.value = "练习进度加载失败，请重试。";
  } finally {
    if (ticket === request) loading.value = false;
  }
}
watch(() => [props.knowledgeId, props.revision], refresh, { immediate: true });
watch(() => props.unlocked, () => { showIntro.value = false; });
</script>

<template>
  <section class="ai-test-entry" aria-label="知识点 AI 小测">
    <h3>AI 小测</h3>
    <p>完成预设题后，通过动态变式题检验掌握程度。</p>
    <NButton block secondary type="primary" :loading="loading" :disabled="!eligible"
      @click="eligible && (showIntro = true)">AI 小测</NButton>
    <p class="entry-hint" aria-live="polite">{{ hint }}</p>
    <NAlert v-if="error" type="warning">{{ error }} <NButton text @click="refresh">重试</NButton></NAlert>
    <NModal v-model:show="showIntro" preset="card" title="AI 小测" class="ai-test-dialog"
      :style="{ width: 'min(480px, calc(100vw - 32px))' }">
      <h3>{{ knowledgeName }}</h3>
      <p>小测将动态生成本知识点的变式题，通过后可获得更高一级的掌握标识。</p>
      <NAlert type="info">AI 小测服务尚未开放，暂时无法生成题目。你的基础练习进度已保留。</NAlert>
      <template #footer><NButton @click="showIntro = false">返回知识点</NButton></template>
    </NModal>
  </section>
</template>

<style scoped>
.ai-test-entry{padding:20px 27px;border-top:1px solid #eef0eb}
h3{margin:0;font-size:1rem;font-weight:500}
p{font-size:.875rem;line-height:1.8;color:#596c54;margin:12px 0}
.entry-hint{font-size:.8125rem;color:#7b8877}
</style>

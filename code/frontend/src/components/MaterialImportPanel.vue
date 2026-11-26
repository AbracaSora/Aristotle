<script setup lang="ts">
import { ref, onMounted, watch, onBeforeUnmount } from "vue";
import { NButton, NInput, NSelect, NAlert, NTag } from "naive-ui";
import type { Job, KnowledgeNode, Material, SourceChunk } from "../types";
const props = defineProps<{
  call: <T>(path: string, method?: string, body?: unknown) => Promise<T>;
  nodes: KnowledgeNode[];
  materials: Material[];
  disabled: boolean;
}>();
const emit = defineEmits<{ refresh: [] }>();
const title = ref("我的学习讲义"),
  text = ref(""),
  source = ref("text"),
  file = ref<File | null>(null),
  job = ref<Job | null>(null),
  error = ref(""),
  busy = ref(false),
  jobs = ref<Job[]>([]);
async function loadJobs() {
  jobs.value = (await props.call<{ items: Job[] }>("/jobs")).items.filter(j => j.kind === "import");
}
onMounted(() => run(loadJobs));
async function run(operation: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    await operation();
    if (operation !== loadJobs) await loadJobs();
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "操作失败，请重试。";
  } finally {
    busy.value = false;
  }
}
async function create() {
  await run(async () => {
    if (source.value === "pdf") {
      if (!file.value || file.value.size > 20 * 1024 * 1024) throw new Error("请选择不超过 20 MB 的文本型 PDF。");
      const form = new FormData();
      form.set("file",file.value); form.set("title",title.value);
      job.value = await props.call<Job>("/material-imports/pdf", "POST", form);
    } else {
      job.value = await props.call<Job>("/material-imports", "POST", {
        source_type:"text", title:title.value, text:text.value, scenario:"normal",
      });
    }
  });
}
let timer: ReturnType<typeof setTimeout> | undefined;
let ticket = 0;
function stopPolling() { ++ticket; clearTimeout(timer); }
async function poll(id: string, current: number) {
  try {
    const row = await props.call<Job>('/jobs/' + id);
    if (current !== ticket) return;
    job.value = row;
    if (row.status === 'succeeded' || row.status === 'failed') { emit('refresh'); await loadJobs(); }
    else timer = setTimeout(()=>poll(id,current), 1200);
  } catch (e) {
    if (current === ticket) error.value = e instanceof Error ? e.message : '任务状态读取失败';
  }
}
watch(()=>job.value?.id, id=>{
  stopPolling();
  if (id && ['queued','running'].includes(job.value!.status)) void poll(id,ticket);
});
onBeforeUnmount(stopPolling);
async function retry() {
  await run(async () => {
    job.value = await props.call<Job>(`/jobs/${job.value!.id}/retry`, "POST");
  });
}
async function chunk(
  m: Material,
  c: SourceChunk,
  status: string,
  id = c.knowledge_id,
) {
  await run(async () => {
    await props.call(`/materials/${m.id}/chunks/${c.id}`, "PATCH", {
      knowledge_id: id,
      status,
    });
    emit("refresh");
  });
}
</script>
<template>
  <section class="panel import-panel">
    <span class="eyebrow">FROM MATERIAL TO LEARNING</span>
    <h2>导入 → 预览 → 确认知识关联</h2>
    <NAlert type="info" class="notice"
      >文字保留段落，文本型 PDF 保留页码（最多 20 MB、100 页）。请核对并确认知识点关联后再使用；扫描件和加密文件无法抽取正文。</NAlert
    >
    <NAlert v-if="error" type="warning" class="notice" role="alert">{{ error }}</NAlert>
    <div class="scope-bar">
      <NSelect
        aria-label="资料类型"
        v-model:value="source"
        :options="[
          { label: '文字讲义', value: 'text' },
          { label: '文本型 PDF', value: 'pdf' },
        ]"
      /><NInput
        :input-props="{'aria-label':'讲义标题'}"
        v-model:value="title"
        placeholder="讲义标题"
      />
    </div>
    <NInput
      v-if="source === 'text'"
      v-model:value="text"
      type="textarea"
      :rows="4"
      placeholder="粘贴正文，空行分段"
      :input-props="{'aria-label':'讲义正文'}"
    /><input v-else type="file" aria-label="文本型 PDF" accept=".pdf,application/pdf"
      @change="file=($event.target as HTMLInputElement).files?.[0] ?? null"/>
    <div class="actions">
      <NButton
        type="primary"
        :loading="busy"
        :disabled="
          disabled || !title.trim() || (source === 'text' ? !text.trim() : !file)
        "
        @click="create"
        >建立导入任务</NButton
      >
    </div>
    <div v-if="job" class="flow-focus">
      <NTag>{{ job.status }}</NTag>
      <p>
        {{
          job.result.notice ||
          job.result.error ||
          "任务已入队，正在等待后台处理。"
        }}
      </p>
      <p class="muted">{{ job.notice }}</p>
      <NButton v-if="['queued','running'].includes(job.status)" :loading="busy" @click="stopPolling(); poll(job.id,ticket)">刷新导入状态</NButton      ><NButton
        v-if="job.status === 'failed' && job.result.retryable"
        :loading="busy"
        @click="retry"
        >重试（新任务）</NButton
      >
    </div>
    <details v-if="jobs.length" class="history-details">
      <summary>导入记录 · 最近 {{ jobs.length }} 项（刷新后可继续）</summary>
      <p v-for="j in jobs" :key="j.id">
        {{ j.status }} · {{ j.id }}
        <NButton text size="small" @click="job = j">查看 / 继续</NButton>
      </p>
    </details>
  </section>
  <section
    v-for="m in materials.filter((m) => m.chunks?.length)"
    :key="m.id"
    class="panel chunk-panel"
  >
    <h3>{{ m.title }} · 片段确认</h3>
    <article v-for="c in m.chunks" :key="c.id" class="source-chunk">
      <NTag :type="c.status === 'confirmed' ? 'success' : 'warning'">{{
        c.status === "confirmed"
          ? "已确认"
          : c.status === "rejected"
            ? "已排除"
            : "待确认"
      }}</NTag
      ><span class="muted"> {{ c.location }} · {{ c.implementation }}</span>
      <p class="material-text">{{ c.text }}</p>
      <NSelect
        :aria-label="'关联知识点 ' + c.location"
        :value="c.knowledge_id"
        :options="nodes.map((n) => ({ label: n.name, value: n.id }))"
        :disabled="busy"
        @update:value="(id) => chunk(m, c, 'pending', id)"
      />
      <div class="actions">
        <NButton
          size="small"
          :disabled="busy"
          @click="
            chunk(m, c, c.status === 'confirmed' ? 'pending' : 'confirmed')
          "
          >{{ c.status === "confirmed" ? "取消确认" : "确认关联" }}</NButton
        ><NButton
          text
          size="small"
          :disabled="busy"
          @click="chunk(m, c, 'rejected')"
          >排除此片段</NButton
        >
      </div>
    </article>
  </section>
</template>

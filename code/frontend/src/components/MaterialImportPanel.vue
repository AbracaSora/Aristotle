<script setup lang="ts">
import { ref, onMounted } from "vue";
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
  scenario = ref("normal"),
  job = ref<Job | null>(null),
  busy = ref(false),
  jobs = ref<Job[]>([]);
async function loadJobs() {
  jobs.value = (await props.call<{ items: Job[] }>("/jobs")).items;
}
onMounted(() => run(loadJobs));
async function run(operation: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true;
  try {
    await operation();
    await loadJobs();
  } catch {
  } finally {
    busy.value = false;
  }
}
async function create() {
  await run(async () => {
    job.value = await props.call<Job>("/material-imports", "POST", {
      source_type: source.value,
      title: title.value,
      text: text.value,
      scenario: source.value === "text" ? "normal" : scenario.value,
    });
  });
}
async function execute() {
  await run(async () => {
    job.value = await props.call<Job>(`/jobs/${job.value!.id}/run`, "POST");
    emit("refresh");
  });
}
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
      >文字按段落保留原文；知识关联使用 mock 候选，确认后才参与任务。PDF
      使用固定样例模拟流程，真实文件解析接口尚未实现。</NAlert
    >
    <div class="scope-bar">
      <NSelect
        aria-label="资料类型"
        v-model:value="source"
        :options="[
          { label: '文字讲义', value: 'text' },
          { label: 'PDF 样例（mock）', value: 'pdf_mock' },
        ]"
      /><NInput
        aria-label="讲义标题"
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
      aria-label="讲义正文"
    /><NSelect
      v-else
      aria-label="PDF 模拟情形"
      v-model:value="scenario"
      :options="[
        { label: '正常样例（固定两页）', value: 'normal' },
        { label: '扫描件无文本', value: 'scanned' },
        { label: '加密文件', value: 'encrypted' },
        { label: '超出大小/页数', value: 'oversize' },
        { label: '处理超时', value: 'timeout' },
      ]"
    />
    <div class="actions">
      <NButton
        type="primary"
        :loading="busy"
        :disabled="
          disabled || !title.trim() || (source === 'text' && !text.trim())
        "
        @click="create"
        >建立导入任务</NButton
      ><NButton
        text
        :disabled="busy"
        @click="
          run(async () => {
            await call('/material-imports/pdf', 'POST');
          })
        "
        >真实 PDF：查看接口占位</NButton
      >
    </div>
    <div v-if="job" class="flow-focus">
      <NTag>{{ job.status }}</NTag>
      <p>
        {{
          job.result.notice ||
          job.result.error ||
          "任务已入队，运行后预览结果。"
        }}
      </p>
      <p class="muted">{{ job.notice }}</p>
      <NButton v-if="job.status === 'queued'" :loading="busy" @click="execute"
        >运行导入任务</NButton
      ><NButton
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

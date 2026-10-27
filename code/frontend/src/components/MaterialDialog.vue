<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { NModal, NInput, NSelect, NButton, NAlert } from "naive-ui";
import type { KnowledgeNode } from "../types";
const props = defineProps<{
  show: boolean;
  nodes: KnowledgeNode[];
  loading: boolean;
  error: string;
}>();
const emit = defineEmits<{
  "update:show": [show: boolean];
  save: [title: string, text: string, knowledgeId: string];
}>();
const title = ref(""),
  text = ref(""),
  knowledgeId = ref<string | null>(null);
const options = computed(() =>
  props.nodes.map((node) => ({ label: node.name, value: node.id })),
);
watch(
  () => props.show,
  (open) => {
    if (open) knowledgeId.value = props.nodes[0]?.id || null;
    else {
      title.value = "";
      text.value = "";
    }
  },
);
</script>

<template>
  <NModal
    :show="show"
    preset="card"
    title="添加文字讲义"
    class="dialog"
    :mask-closable="false"
    :closable="!loading"
    :close-on-esc="!loading"
    @update:show="emit('update:show', $event)"
  >
    <NAlert v-if="error" type="warning" class="notice" role="alert">{{
      error
    }}</NAlert>
    <form
      @submit.prevent="
        knowledgeId && emit('save', title.trim(), text.trim(), knowledgeId)
      "
    >
      <label class="field"
        >标题<NInput
          v-model:value="title"
          maxlength="80"
          :disabled="loading"
          placeholder="例如：栈的基本操作"
      /></label>
      <label class="field"
        >讲义正文<NInput
          v-model:value="text"
          type="textarea"
          :rows="7"
          :maxlength="20000"
          show-count
          :disabled="loading"
          placeholder="粘贴需要整理的笔记…"
      /></label>
      <label class="field"
        >关联知识点<NSelect
          v-model:value="knowledgeId"
          :options="options"
          :disabled="loading"
          placeholder="选择知识点"
      /></label>
      <p class="muted">
        讲义将保存在学习服务中。当前采用手动关联，保存后仍需确认；内容不会发送给外部模型。
      </p>
      <NButton
        attr-type="submit"
        type="primary"
        :loading="loading"
        :disabled="!title.trim() || !text.trim() || !knowledgeId"
        >保存讲义</NButton
      >
    </form>
  </NModal>
</template>

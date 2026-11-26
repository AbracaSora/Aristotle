<script setup lang="ts">
import {courseLabel,type CourseCall,type CourseProgress} from '../features/map/course';
import PresetPractice from '../features/map/PresetPractice.vue';
import FinalPaper from '../features/map/FinalPaper.vue';

defineProps<{knowledgeId:string;progress:CourseProgress;call:CourseCall}>();
defineEmits<{changed:[]; materials:[]}>();
</script>
<template><section class="course-entry" aria-label="课程掌握进度">
  <h3>课程进度 · {{courseLabel(progress)}}</h3>
  <p>预设题完成 {{progress.completed_count}} / {{progress.total_count}}，各题最近一次答对 {{progress.latest_correct_count}} 道。</p>
  <p v-if="progress.total_count">完成全部预设并至少答对 {{progress.required_correct_count}} 道，即满足本知识点作为先修的要求。</p>
  <template v-if="progress.unlocked && progress.total_count">
    <PresetPractice @materials="$emit('materials')" :knowledge-id="knowledgeId" :call="call" @changed="$emit('changed')" />
    <FinalPaper :knowledge-id="knowledgeId" :eligible="progress.ai_test_eligible" :call="call" @changed="$emit('changed')" />
  </template>
</section></template>
<style scoped>.course-entry{padding:20px 27px;border-top:1px solid #edf0e9}.course-entry p{line-height:1.7}</style>

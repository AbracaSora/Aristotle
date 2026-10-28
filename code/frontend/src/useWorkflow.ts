import { ref, watch } from "vue";
import type { useLearning } from "./useLearning";
import type {
  Scope,
  LearningContext,
  Task,
  TimelineItem,
  ContentReport,
  Level,
} from "./types";
export function useWorkflow(learning: ReturnType<typeof useLearning>) {
  const scopes = ref<Scope[]>([]),
    context = ref<LearningContext | null>(null);
  const timeline = ref<TimelineItem[]>([]),
    reports = ref<ContentReport[]>([]);
  const loading = ref(false);
  let generation = 0;
  async function reload() {
    const id = learning.user.value?.id,
      ticket = generation;
    if (!id || learning.user.value?.role !== "student") return;
    const [s, c, t, r] = await Promise.all([
      learning.call<{ items: Scope[] }>("/scopes"),
      learning.call<LearningContext>("/learning-context"),
      learning.call<{ items: TimelineItem[] }>("/learning-timeline"),
      learning.call<{ items: ContentReport[] }>("/content-reports"),
    ]);
    if (ticket !== generation || learning.user.value?.id !== id) return;
    scopes.value = s.items;
    context.value = c;
    timeline.value = t.items;
    reports.value = r.items;
  }
  async function run<T>(operation: () => Promise<T>): Promise<T | null> {
    if (loading.value) return null;
    loading.value = true;
    learning.error.value = "";
    const ticket = generation;
    try {
      return await operation();
    } catch {
      return null;
    } finally {
      if (ticket === generation) loading.value = false;
    }
  }
  async function choose(id: string) {
    return run(async () => {
      await learning.call("/learning-scope", "PATCH", { scope_id: id });
      learning.selectTask(null);
      await learning.refresh();
      await reload();
      return true;
    });
  }
  async function begin(knowledge_id?: string, target_level?: Level) {
    return run(async () => {
      await learning.call("/diagnostics", "POST", {
        knowledge_id,
        target_level,
      });
      await reload();
      return true;
    });
  }
  async function recommend(knowledge_id?: string) {
    return run(async () => {
      const task = await learning.call<Task>("/recommendations", "POST", {
        mode: "practice",
        knowledge_id,
      });
      learning.selectTask(task);
      await reload();
      return task;
    });
  }
  async function open(id: string) {
    return run(async () => {
      let task = await learning.call<Task>(`/tasks/${id}`);
      if (task.lifecycle === "recommended")
        task = (
          await learning.call<{ task: Task }>(`/tasks/${id}/actions`, "POST", {
            action: "accept",
          })
        ).task;
      learning.selectTask(task);
      await reload();
      return task;
    });
  }
  async function act(action: string, id = learning.task.value?.id) {
    if (!id) return null;
    return run(async () => {
      const result = await learning.call<{
        task: Task;
        replacement: Task | null;
      }>(`/tasks/${id}/actions`, "POST", {
        action,
        reason: action === "skip" ? "学习者选择稍后安排" : "学习者操作",
      });
      learning.selectTask(result.replacement || result.task);
      await learning.refresh();
      await reload();
      return result.task;
    });
  }
  async function rebuild() {
    const round = context.value?.diagnostic;
    if (round?.status === "active") {
      const ok = await run(async () => {
        await learning.call(`/diagnostics/${round.id}/restart`, "POST");
        await reload();
        return true;
      });
      if (!ok) return null;
      const segment = context.value?.diagnostic?.segments.find(
        (s) => s.status !== "completed",
      );
      return segment ? open(segment.task_id) : null;
    }
    await act("replace");
    return null;
  }
  async function next() {
    const feedback =
      learning.task.value?.feedback || context.value?.last_feedback;
    if (feedback?.next_action === "retest") {
      if (!(await begin(feedback.knowledge_id, feedback.target_level)))
        return null;
    } else if (feedback?.next_action !== "diagnostic_next") {
      await recommend();
      return null;
    }
    const segment = context.value?.diagnostic?.segments.find(
      (s) => s.status !== "completed",
    );
    return segment ? open(segment.task_id) : null;
  }
  watch(
    () => learning.user.value?.id,
    () => {
      generation++;
      loading.value = false;
      scopes.value = [];
      context.value = null;
      timeline.value = [];
      reports.value = [];
      if (learning.user.value?.role === "student") void run(reload);
    },
  );
  return {
    scopes,
    context,
    timeline,
    reports,
    loading,
    reload,
    run,
    choose,
    begin,
    recommend,
    open,
    act,
    next,
    rebuild,
  };
}

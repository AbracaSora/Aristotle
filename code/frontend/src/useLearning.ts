import { computed, ref } from "vue";
import { ApiError, createApiClient } from "./api";
import type {
  Attempt,
  HistoryPage,
  KnowledgeGraph,
  LearningState,
  LoginResult,
  Material,
  PendingSubmission,
  Task,
  User,
} from "./types";

const TOKEN_KEY = "aristotle-api-token";
const taskKey = (id: string) => `aristotle-api-task:${id}`;
function readStorage(key: string) {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}
function writeStorage(key: string, value: string | null) {
  try {
    if (value === null) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, value);
  } catch {
    /* The in-memory session can still be used. */
  }
}

export function useLearning() {
  const user = ref<User | null>(null),
    graph = ref<KnowledgeGraph | null>(null),
    state = ref<LearningState | null>(null);
  const history = ref<HistoryPage>({
    items: [],
    total: 0,
    correct_total: 0,
    limit: 50,
    offset: 0,
  });
  const materials = ref<Material[]>([]),
    task = ref<Task | null>(null);
  const error = ref(""),
    busy = ref(false),
    submitting = ref(false),
    mutating = ref(false);
  const pendingSubmission = ref<PendingSubmission | null>(null);
  let epoch = 0,
    api = createApiClient();
  const capture = () => ({ epoch, api, user: user.value });
  const current = (context: ReturnType<typeof capture>) =>
    context.epoch === epoch;
  function clearData() {
    graph.value = null;
    state.value = null;
    materials.value = [];
    task.value = null;
    history.value = {
      items: [],
      total: 0,
      correct_total: 0,
      limit: 50,
      offset: 0,
    };
    pendingSubmission.value = null;
  }
  function clearSession() {
    epoch++;
    user.value = null;
    api = createApiClient();
    writeStorage(TOKEN_KEY, null);
    clearData();
  }
  function report(reason: unknown, context = capture()) {
    if (!current(context)) return;
    if (reason instanceof ApiError && reason.status === 401) {
      clearSession();
      error.value = "会话已失效，请重新登录。";
    } else
      error.value =
        reason instanceof Error ? reason.message : "操作失败，请重试。";
  }
  async function hydrate(restoreTask = false, context = capture()) {
    if (context.user?.role !== "student") return;
    const [nextGraph, nextState, nextHistory, nextMaterials] =
      await Promise.all([
        context.api.request<KnowledgeGraph>("/knowledge"),
        context.api.request<LearningState>("/learning-state"),
        context.api.request<HistoryPage>("/history?limit=50"),
        context.api.request<{ items: Material[] }>("/materials"),
      ]);
    if (!current(context)) return;
    graph.value = nextGraph;
    state.value = nextState;
    history.value = nextHistory;
    materials.value = nextMaterials.items;
    if (restoreTask) {
      const id = readStorage(taskKey(context.user.id));
      if (id) {
        try {
          const restored = await context.api.request<Task>(
            `/tasks/${encodeURIComponent(id)}`,
          );
          if (current(context)) task.value = restored;
        } catch (reason) {
          if (reason instanceof ApiError && reason.status === 404)
            writeStorage(taskKey(context.user.id), null);
          else throw reason;
        }
      }
    }
  }
  async function restore() {
    const token = readStorage(TOKEN_KEY);
    if (!token) return;
    busy.value = true;
    api = createApiClient(token);
    const context = capture();
    try {
      const restoredUser = await context.api.request<User>("/auth/me");
      if (!current(context)) return;
      user.value = restoredUser;
      await hydrate(true, capture());
    } catch (reason) {
      report(reason, context);
    } finally {
      busy.value = false;
    }
  }
  async function login(username: string, password: string) {
    if (busy.value) return false;
    busy.value = true;
    clearSession();
    error.value = "";
    const context = capture();
    try {
      const result = await context.api.request<LoginResult>(
        "/auth/login",
        "POST",
        { username, password },
      );
      if (!current(context)) return false;
      api = createApiClient(result.access_token);
      user.value = result.user;
      writeStorage(TOKEN_KEY, result.access_token);
      await hydrate(true, capture());
      return true;
    } catch (reason) {
      report(reason, context);
      return false;
    } finally {
      busy.value = false;
    }
  }
  async function logout() {
    if (busy.value || submitting.value || mutating.value) return false;
    busy.value = true;
    error.value = "";
    const context = capture();
    try {
      await context.api.request("/auth/logout", "POST");
      clearSession();
      return true;
    } catch (reason) {
      report(reason, context);
      return !user.value;
    } finally {
      busy.value = false;
    }
  }
  async function refresh() {
    if (busy.value) return;
    busy.value = true;
    error.value = "";
    const context = capture();
    try {
      await hydrate(false, context);
    } catch (reason) {
      report(reason, context);
    } finally {
      busy.value = false;
    }
  }
  async function requestTask(knowledgeId?: string) {
    if (busy.value || submitting.value) return null;
    busy.value = true;
    error.value = "";
    const context = capture();
    try {
      const next = await context.api.request<Task>("/tasks", "POST", {
        mode: history.value.total ? "practice" : "diagnostic",
        ...(knowledgeId ? { knowledge_id: knowledgeId } : {}),
      });
      if (!current(context) || !context.user) return null;
      task.value = next;
      pendingSubmission.value = null;
      writeStorage(taskKey(context.user.id), next.id);
      return next;
    } catch (reason) {
      report(reason, context);
      return null;
    } finally {
      busy.value = false;
    }
  }
  async function submit(questionKey: string, selected: string) {
    const active = task.value;
    if (!active || submitting.value) return;
    const pending = pendingSubmission.value;
    if (
      pending &&
      (pending.taskId !== active.id ||
        pending.questionKey !== questionKey ||
        pending.selected !== selected)
    ) {
      error.value = "上次提交结果尚未确认，请先重试保存原答案。";
      return;
    }
    const submission = pending || {
      taskId: active.id,
      questionKey,
      selected,
      submissionId: crypto.randomUUID(),
    };
    pendingSubmission.value = submission;
    submitting.value = true;
    error.value = "";
    const context = capture();
    try {
      const saved = await context.api.request<Attempt>(
        `/tasks/${active.id}/attempts`,
        "POST",
        {
          question_key: questionKey,
          selected,
          submission_id: submission.submissionId,
        },
      );
      if (!current(context)) return;
      pendingSubmission.value = null;
      if (task.value?.id === active.id)
        task.value = {
          ...task.value,
          attempts: [
            ...task.value.attempts.filter(
              (a) => a.question_key !== saved.question_key,
            ),
            saved,
          ],
        };
      try {
        await hydrate(false, context);
      } catch (reason) {
        report(reason, context);
        if (current(context))
          error.value = "作答已保存，但最新统计读取失败，请刷新学习状态。";
      }
    } catch (reason) {
      if (
        reason instanceof ApiError &&
        reason.status >= 400 &&
        reason.status < 500 &&
        current(context)
      ) {
        pendingSubmission.value = null;
        if (reason.status === 409) {
          try {
            const restored = await context.api.request<Task>(
              `/tasks/${active.id}`,
            );
            if (current(context)) task.value = restored;
          } catch {
            /* Preserve the original conflict message. */
          }
        }
      }
      report(reason, context);
    } finally {
      submitting.value = false;
    }
  }
  function syncMaterial(id: string, material?: Material) {
    if (!task.value) return;
    task.value = {
      ...task.value,
      materials: task.value.materials.map((m) =>
        m.id !== id
          ? m
          : material?.confirmed &&
              material.knowledge_id === task.value?.knowledge_id
            ? material
            : {
                id,
                unavailable: true as const,
                reason: "来源已删除或关联已取消/变更",
              },
      ),
    };
  }
  async function addMaterial(title: string, text: string, knowledgeId: string) {
    if (mutating.value) return false;
    mutating.value = true;
    error.value = "";
    const context = capture();
    try {
      const row = await context.api.request<Material>("/materials", "POST", {
        title,
        text,
        knowledge_id: knowledgeId,
      });
      if (!current(context)) return false;
      materials.value = [...materials.value, row];
      return true;
    } catch (reason) {
      report(reason, context);
      return false;
    } finally {
      mutating.value = false;
    }
  }
  async function updateMaterial(
    material: Material,
    knowledgeId: string,
    confirmed: boolean,
  ) {
    if (mutating.value) return;
    mutating.value = true;
    error.value = "";
    const context = capture();
    try {
      const row = await context.api.request<Material>(
        `/materials/${material.id}`,
        "PATCH",
        { knowledge_id: knowledgeId, confirmed },
      );
      if (!current(context)) return;
      materials.value = materials.value.map((m) => (m.id === row.id ? row : m));
      syncMaterial(row.id, row);
    } catch (reason) {
      report(reason, context);
    } finally {
      mutating.value = false;
    }
  }
  async function removeMaterial(id: string) {
    if (mutating.value) return;
    mutating.value = true;
    error.value = "";
    const context = capture();
    try {
      await context.api.request(`/materials/${id}`, "DELETE");
      if (!current(context)) return;
      materials.value = materials.value.filter((m) => m.id !== id);
      syncMaterial(id);
    } catch (reason) {
      report(reason, context);
    } finally {
      mutating.value = false;
    }
  }
  async function loadMore() {
    if (busy.value) return;
    busy.value = true;
    error.value = "";
    const context = capture();
    try {
      const next = await context.api.request<HistoryPage>(
        `/history?limit=50&offset=${history.value.items.length}`,
      );
      if (current(context))
        history.value = {
          ...next,
          items: [
            ...history.value.items,
            ...next.items.filter(
              (a) => !history.value.items.some((old) => old.id === a.id),
            ),
          ],
        };
    } catch (reason) {
      report(reason, context);
    } finally {
      busy.value = false;
    }
  }
  async function call<T>(
    path: string,
    method = "GET",
    body?: unknown,
  ): Promise<T> {
    const context = capture();
    try {
      const value = await context.api.request<T>(path, method, body);
      if (!current(context)) throw new Error("会话已切换，请重新操作。");
      return value;
    } catch (reason) {
      report(reason, context);
      throw reason;
    }
  }
  function selectTask(next: Task | null) {
    task.value = next;
    pendingSubmission.value = null;
    if (user.value) writeStorage(taskKey(user.value.id), next?.id || null);
  }
  const hasPendingTask = computed(
    () =>
      !!task.value?.questions.some(
        (q) => !task.value?.attempts.some((a) => a.question_key === q.key),
      ),
  );
  return {
    call,
    selectTask,
    user,
    graph,
    state,
    history,
    materials,
    task,
    error,
    busy,
    submitting,
    mutating,
    pendingSubmission,
    hasPendingTask,
    restore,
    login,
    logout,
    refresh,
    requestTask,
    submit,
    addMaterial,
    updateMaterial,
    removeMaterial,
    loadMore,
  };
}

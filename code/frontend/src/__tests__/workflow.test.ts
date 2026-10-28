import { describe, it, expect, vi } from "vitest";
import { effectScope, ref } from "vue";
import { useWorkflow } from "../useWorkflow";
import type { useLearning } from "../useLearning";
import type { LearningContext, Task } from "../types";
function setup() {
  const data: LearningContext = {
    selected_scope: {
      id: "stack",
      title: "栈",
      knowledge_ids: ["stack"],
      published: true,
      description: "",
    },
    diagnostic: null,
    current_task: null,
    last_feedback: null,
    stage: "diagnosis",
  };
  const task = {
    id: "t",
    scope_id: "stack",
    lifecycle: "recommended",
    questions: [],
    attempts: [],
  } as unknown as Task;
  const calls: { path: string; body: any }[] = [];
  const call = vi.fn(
    async (path: string, _method?: string, body?: any): Promise<any> => {
      calls.push({ path, body });
      if (path === "/learning-context") return structuredClone(data);
      if (path === "/scopes") return { items: [data.selected_scope] };
      if (path === "/learning-timeline" || path === "/content-reports")
        return { items: [] };
      if (path === "/diagnostics") {
        data.diagnostic = {
          id: "d",
          scope_id: "stack",
          status: "active",
          completed_segments: 0,
          notice: "",
          segments: [
            {
              task_id: "t",
              knowledge_id: "stack",
              level: "apply",
              question_count: 3,
              answered: 0,
              status: "recommended",
            },
          ],
        };
        return data.diagnostic;
      }
      if (path === "/tasks/t") return { ...task };
      if (path === "/tasks/t/actions") {
        task.lifecycle = body.action === "complete" ? "completed" : "accepted";
        task.feedback =
          body.action === "complete"
            ? {
                answered: 0,
                correct: 0,
                message: "无新增证据",
                state: null,
                next_action: "retest",
                knowledge_id: "stack",
                target_level: "apply",
              }
            : null;
        return { task: { ...task }, replacement: null };
      }
      if (path === "/recommendations") return { ...task };
      return {};
    },
  );
  const learning = {
    user: ref({ id: "u", role: "student" }),
    task: ref<Task | null>(null),
    error: ref(""),
    call,
    refresh: vi.fn(async () => {}),
    selectTask: (t: Task | null) => {
      learning.task.value = t;
    },
  };
  const scope = effectScope();
  const workflow = scope.run(() =>
    useWorkflow(learning as unknown as ReturnType<typeof useLearning>),
  )!;
  return { workflow, learning, calls, data, task, scope };
}
describe("design workflow state", () => {
  it("requires explicit accept before putting a recommended task into the activity dialog", async () => {
    const s = setup();
    await s.workflow.reload();
    await s.workflow.open("t");
    expect(
      s.calls.find((c) => c.path === "/tasks/t/actions")?.body.action,
    ).toBe("accept");
    expect(s.learning.task.value?.lifecycle).toBe("accepted");
    s.scope.stop();
  });
  it("transitions reading completion into a targeted new diagnostic rather than awarding evidence", async () => {
    const s = setup();
    s.learning.task.value = s.task;
    await s.workflow.act("complete");
    await s.workflow.next();
    expect(s.calls.find((c) => c.path === "/diagnostics")?.body).toEqual({
      knowledge_id: "stack",
      target_level: "apply",
    });
    expect(s.learning.task.value?.id).toBe("t");
    expect(s.calls.some((c) => c.path.includes("/attempts"))).toBe(false);
    s.scope.stop();
  });
  it("clears the selected task when switching scope but does not delete history", async () => {
    const s = setup();
    s.learning.task.value = s.task;
    await s.workflow.choose("stack");
    expect(s.learning.task.value).toBeNull();
    expect(s.calls.some((c) => c.path === "/learning-scope")).toBe(true);
    expect(s.calls.some((c) => c.path.includes("/history"))).toBe(false);
    s.scope.stop();
  });
  it("does not accept or open a task when loading it fails", async () => {
    const s = setup();
    s.learning.call.mockRejectedValueOnce(new Error("offline"));
    expect(await s.workflow.open("t")).toBeNull();
    expect(s.learning.task.value).toBeNull();
    expect(s.workflow.loading.value).toBe(false);
    s.scope.stop();
  });
  it("ignores an old context response when the session changes", async () => {
    const s = setup();
    let release!: (value: any) => void;
    const wait = new Promise((r) => (release = r));
    s.learning.call.mockImplementationOnce(() => wait);
    const pending = s.workflow.reload();
    s.learning.user.value = { id: "other", role: "maintainer" };
    await Promise.resolve();
    release({ items: [s.data.selected_scope] });
    await pending;
    expect(s.workflow.context.value).toBeNull();
    expect(s.workflow.scopes.value).toEqual([]);
    s.scope.stop();
  });
});

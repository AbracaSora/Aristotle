import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createApiClient, ApiError } from "../api";
import { useLearning } from "../useLearning";
import type { Attempt, Material, Task } from "../types";

function setupService() {
  const records: Attempt[] = [],
    materials: Material[] = [],
    bodies: any[] = [];
  const task: Task = {
    id: "task-1",
    mode: "diagnostic",
    graph_version: "g1",
    created_at: 100,
    knowledge_id: "linear",
    target_level: "remember",
    question_keys: ["l1:v1"],
    reason: "规则依据",
    warnings: [],
    policy_version: "baseline-0.1",
    material_ids: [],
    status: "ready",
    questions: [
      {
        key: "l1:v1",
        question_id: "l1",
        version: 1,
        knowledge_id: "linear",
        prompt: "测试题",
        options: ["A", "B"],
        level: "remember",
        status: "published",
        dataset: "demo-seed",
      },
    ],
    materials: [],
    attempts: [],
    evidence_snapshot: [],
    notice: "原型",
  };
  const service = {
    loseNextSubmission: false,
    failHistory: false,
    expire: false,
    denyUpdates: false,
    holdSecondLogin: null as Promise<void> | null,
    records,
    materials,
    bodies,
  };
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).replace("/api/v1", "").split("?")[0];
      const body = init?.body ? JSON.parse(String(init.body)) : {};
      const token = (init?.headers as Record<string, string>)?.Authorization;
      const other = token === "Bearer token-student2";
      const json = (data: unknown, status = 200) =>
        new Response(JSON.stringify(data), {
          status,
          headers: { "Content-Type": "application/json" },
        });
      if (path === "/auth/login") {
        if (body.username === "student2") await service.holdSecondLogin;
        return json({
          access_token: "token-" + body.username,
          user: { id: body.username, username: body.username, role: "student" },
          expires_at: 9999999999,
        });
      }
      if (path === "/auth/me")
        return json({ id: "student1", username: "student1", role: "student" });
      if (path === "/auth/logout") return new Response(null, { status: 204 });
      if (path === "/knowledge")
        return json({
          version: "g1",
          nodes: [{ id: "linear", name: "基础", prerequisites: [] }],
        });
      if (path === "/learning-state")
        return service.expire
          ? json({ error: { message: "会话过期" } }, 401)
          : json({
              graph_version: "g1",
              policy_version: "baseline-0.1",
              window_days: 14,
              states: [],
              notice: "规则",
            });
      if (path === "/history")
        return service.failHistory
          ? json({ error: { message: "统计不可用" } }, 503)
          : json({
              items: other ? [] : records,
              total: other ? 0 : records.length,
              correct_total: other
                ? 0
                : records.filter((a) => a.correct).length,
              limit: 50,
              offset: 0,
            });
      if (path === "/materials" && init?.method === "POST") {
        const row = {
          ...body,
          id: "material-1",
          confirmed: false,
          source_location: "第 1 段",
        };
        materials.push(row);
        return json(row, 201);
      }
      if (path === "/materials") return json({ items: other ? [] : materials });
      if (path === "/materials/material-1")
        return service.denyUpdates
          ? json({ error: { message: "保存失败" } }, 500)
          : json({ ...materials[0], ...body });
      if (path === "/tasks") return json(task, 201);
      if (path === "/tasks/task-1") return json({ ...task, attempts: records });
      if (path === "/tasks/task-1/attempts") {
        bodies.push(body);
        if (service.loseNextSubmission) {
          service.loseNextSubmission = false;
          throw new TypeError("connection lost");
        }
        const row: Attempt = {
          id: "attempt-1",
          task_id: task.id,
          question_key: body.question_key,
          selected: body.selected,
          submission_id: body.submission_id,
          correct: true,
          created_at: 120,
          answer: "B",
          explanation: "服务端解析",
          level: "remember",
          question_version: 1,
          content_status: "published",
        };
        records.push(row);
        return json(row);
      }
      throw new Error("Unexpected request: " + path);
    },
  );
  vi.stubGlobal("fetch", fetchMock);
  return service;
}

beforeEach(() => {
  const values = new Map<string, string>();
  vi.stubGlobal("sessionStorage", {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
  });
});
afterEach(() => vi.unstubAllGlobals());

describe("学习 API 对接状态", () => {
  it("网络中断后保留原提交编号和答案，成功前不本地判分", async () => {
    const service = setupService(),
      store = useLearning();
    await store.login("student1", "password");
    await store.requestTask();
    service.loseNextSubmission = true;
    await store.submit("l1:v1", "B");
    expect(store.task.value?.attempts).toHaveLength(0);
    expect(store.pendingSubmission.value?.selected).toBe("B");
    await store.submit("l1:v1", "B");
    expect(service.bodies[0].submission_id).toBe(
      service.bodies[1].submission_id,
    );
    expect(store.task.value?.attempts[0].explanation).toBe("服务端解析");
    expect(store.pendingSubmission.value).toBeNull();
    expect(store.history.value.total).toBe(1);
  });
  it("结果不确定时不能替换成另一答案重试", async () => {
    const service = setupService(),
      store = useLearning();
    await store.login("student1", "password");
    await store.requestTask();
    service.loseNextSubmission = true;
    await store.submit("l1:v1", "A");
    await store.submit("l1:v1", "B");
    expect(service.bodies).toHaveLength(1);
    expect(store.error.value).toContain("原答案");
  });
  it("保存成功后统计故障仍保留已保存反馈", async () => {
    const service = setupService(),
      store = useLearning();
    await store.login("student1", "password");
    await store.requestTask();
    service.failHistory = true;
    await store.submit("l1:v1", "B");
    expect(store.task.value?.attempts).toHaveLength(1);
    expect(store.pendingSubmission.value).toBeNull();
    expect(store.error.value).toContain("作答已保存");
  });
  it("账号切换开始时清空旧数据，不能显示旧账号的任务和资料", async () => {
    const service = setupService(),
      store = useLearning();
    await store.login("student1", "password");
    await store.requestTask();
    await store.submit("l1:v1", "B");
    await store.addMaterial("私人资料", "只属于学生一", "linear");
    let release!: () => void;
    service.holdSecondLogin = new Promise<void>((resolve) => {
      release = resolve;
    });
    const switching = store.login("student2", "password");
    expect(store.user.value).toBeNull();
    expect(store.materials.value).toHaveLength(0);
    expect(store.task.value).toBeNull();
    release();
    await switching;
    expect(store.user.value?.username).toBe("student2");
    expect(store.history.value.total).toBe(0);
    expect(store.materials.value).toHaveLength(0);
  });
  it("刷新时恢复会话和所属任务，已保存反馈从服务端读取", async () => {
    setupService();
    const first = useLearning();
    await first.login("student1", "password");
    await first.requestTask();
    await first.submit("l1:v1", "B");
    const restored = useLearning();
    await restored.restore();
    expect(restored.user.value?.id).toBe("student1");
    expect(restored.task.value?.attempts).toHaveLength(1);
    expect(restored.history.value.total).toBe(1);
  });
  it("会话过期清除身份和业务数据", async () => {
    const service = setupService(),
      store = useLearning();
    await store.login("student1", "password");
    await store.requestTask();
    service.expire = true;
    await store.refresh();
    expect(store.user.value).toBeNull();
    expect(store.task.value).toBeNull();
    expect(sessionStorage.getItem("aristotle-api-token")).toBeNull();
    expect(store.error.value).toContain("重新登录");
  });
  it("资料确认失败不显示为已确认", async () => {
    const service = setupService(),
      store = useLearning();
    await store.login("student1", "password");
    await store.addMaterial("笔记", "内容", "linear");
    service.denyUpdates = true;
    await store.updateMaterial(store.materials.value[0]!, "linear", true);
    expect(store.materials.value[0]?.confirmed).toBe(false);
    expect(store.error.value).toContain("保存失败");
  });
});

describe("API 错误契约", () => {
  it("读取统一业务错误及字段原因", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              error: {
                message: "输入校验失败",
                fields: [{ message: "正文不能为空" }],
              },
            }),
            { status: 422 },
          ),
      ),
    );
    await expect(
      createApiClient().request("/materials", "POST", {}),
    ).rejects.toThrow("正文不能为空");
  });
  it("将不可读响应作为错误，不伪装成成功", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("gateway failed", { status: 502 })),
    );
    await expect(createApiClient().request("/tasks")).rejects.toBeInstanceOf(
      ApiError,
    );
  });
  it("退出的 204 响应不尝试读取 JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(null, { status: 204 })),
    );
    await expect(
      createApiClient("token").request("/auth/logout", "POST"),
    ).resolves.toBeUndefined();
  });
});

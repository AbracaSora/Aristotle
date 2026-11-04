import { expect, test, type Page } from "@playwright/test";

async function login(page: Page, username: string) {
  await page.goto("/");
  await page.getByRole("textbox", { name: "账号", exact: true }).fill(username);
  await page
    .getByRole("textbox", { name: "密码", exact: true })
    .fill(process.env.ARISTOTLE_DEMO_PASSWORD || "demo-password");
  await page.getByRole("button", { name: "进入学习空间" }).click();
  await expect(page.locator(".shell")).toBeVisible();
}

for (const [username, label] of [
  ["admin", "系统管理"],
  ["editor", "内容工作台"],
]) {
  test(`${username}: navigation stays aligned after login, reload and brand click`, async ({
    page,
  }) => {
    await login(page, username);
    const nav = page
      .getByRole("navigation", { name: "主导航" })
      .getByRole("button", { name: label });
    await expect(nav).toHaveClass(/active/);
    await expect(page.locator(".topbar")).toContainText(label);
    await page.reload();
    await expect(nav).toHaveClass(/active/);
    await page.locator("a.brand").click();
    await expect(nav).toHaveClass(/active/);
    await expect(page.locator(".topbar")).toContainText(label);
    await expect(page.locator("main h1")).toHaveText(
      username === "admin" ? "系统管理" : "内容维护与审核",
    );
    await page.getByRole("button", { name: "退出 / 切换账号" }).click();
    await login(page, "student2");
    await expect(page.locator(".nav-link.active")).toHaveText("学习概览");
  });
}

test("student: disabled imports, diagnosis restrictions, saved answers and targeted task", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await login(page, "student1");
  await expect(page.locator(".scope-bar")).toBeVisible();
  await page.getByRole("button", { name: "我的资料", exact: true }).click();
  const pdf = page.getByRole("button", { name: "真实 PDF：查看接口占位" });
  await expect(pdf).toBeVisible();
  await expect(page.locator(".import-panel .n-button--loading")).toHaveCount(0);
  await expect(pdf).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "建立导入任务" }),
  ).toBeDisabled();
  let pdfRequests = 0;
  page.on("request", (request) => {
    if (request.url().endsWith("/material-imports/pdf")) pdfRequests++;
  });
  // Synthetic clicks must not send a PDF request while imports are disabled.
  await pdf.dispatchEvent("click");
  expect(pdfRequests).toBe(0);

  await page.getByRole("button", { name: "学习概览", exact: true }).click();
  await page.getByLabel("学习范围", { exact: true }).click();
  await page.getByText("线性结构基础", { exact: true }).click();
  await page.getByRole("button", { name: "确认范围" }).click();
  await expect(
    page.getByRole("button", { name: "开始初始诊断" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "知识地图", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "请先完成初始诊断" }).first(),
  ).toBeDisabled();
  await page.getByRole("button", { name: "学习概览", exact: true }).click();
  const started = page.waitForResponse(
    (response) =>
      response.url().endsWith("/diagnostics") &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "开始初始诊断" }).click();
  const diagnostic = await (await started).json();
  await page.getByRole("button", { name: "知识地图", exact: true }).click();
  const blocked = page
    .getByRole("button", { name: "请先完成当前诊断" })
    .first();
  await expect(blocked).toBeDisabled();
  await blocked.dispatchEvent("click");
  await expect(page.locator(".dialog")).not.toBeVisible();
  await expect(page.locator(".nav-link.active")).toHaveText("知识地图");

  // Use real API grading and persist every segment before requesting a task.
  await page.getByRole("button", { name: "学习概览", exact: true }).click();
  await page.getByRole("button", { name: /^继续诊断/ }).click();
  const dialog = page.locator(".dialog");
  for (let index = 0; index < diagnostic.segments.length; index++) {
    const segment = diagnostic.segments[index];
    for (let question = 0; question < segment.question_count; question++) {
      await dialog.locator(".answers .n-radio").first().click();
      await dialog.getByRole("button", { name: "提交答案" }).click();
      await expect(dialog.locator(".feedback")).toBeVisible();
      await dialog.getByRole("button", { name: /^(下一题|查看反馈)$/ }).click();
    }
    await dialog.getByRole("button", { name: "完成本段并查看反馈" }).click();
    await expect(
      dialog.getByRole("heading", { name: "本段诊断已完成" }),
    ).toBeVisible();
    if (index < diagnostic.segments.length - 1) {
      await dialog.getByRole("button", { name: "继续下一段诊断" }).click();
    }
  }
  await dialog.getByRole("button", { name: "学习记录", exact: true }).click();
  await expect(page.locator(".history-row")).toHaveCount(
    diagnostic.segments.reduce(
      (count: number, segment: { question_count: number }) =>
        count + segment.question_count,
      0,
    ),
  );
  await page.getByRole("button", { name: "知识地图", exact: true }).click();
  const target = page
    .locator(".cards > article")
    .first()
    .getByRole("button", { name: "获取此知识点任务" });
  await expect(target).toBeEnabled();
  const recommended = page.waitForResponse(
    (response) =>
      response.url().endsWith("/recommendations") &&
      response.request().method() === "POST",
  );
  await target.click();
  const response = await recommended;
  expect(response.ok()).toBe(true);
  expect(response.request().postDataJSON().knowledge_id).toBe("linear");
  expect((await response.json()).knowledge_id).toBe("linear");
  await expect(page.locator(".nav-link.active")).toHaveText("学习概览");
});

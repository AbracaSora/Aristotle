import { expect, test } from "@playwright/test";

test("学生可以从登录进入诊断并看到可追溯的学习安排", async ({ page }) => {
  await page.goto("/");

  await page.getByRole("textbox", { name: "账号" }).fill("student1");
  await page.getByRole("textbox", { name: "密码" }).fill("demo-password");
  await page.getByRole("button", { name: /进入学习空间/ }).click();

  await expect(page.getByText("选择范围", { exact: true })).toBeVisible();
  const scope = page.getByRole("combobox", { name: "学习范围" });
  await scope.click();
  await page.getByText("栈：从理解到应用", { exact: true }).click();
  await page.getByRole("button", { name: "确认范围" }).click();

  await page.getByRole("button", { name: "开始初始诊断" }).click();
  await expect(page.getByText("诊断 · 收集认知证据", { exact: true })).toBeVisible();

  // The demo seed has three questions per segment. Select the first option so
  // this test remains independent of the answer key while exercising the real
  // submit, feedback, and next-question transitions.
  for (let question = 0; question < 3; question += 1) {
    await page.locator(".answers .n-radio").first().click();
    await page.getByRole("button", { name: "提交答案" }).click();
    await expect(page.getByText("单题结果仅作为一条作答证据。", { exact: false })).toBeVisible();
    if (question < 2) {
      await page.getByRole("button", { name: "下一题" }).click();
    }
  }

  await page.getByRole("button", { name: "完成本段并查看反馈" }).click();
  await expect(page.getByText("本段诊断已完成", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "继续下一段诊断" }).click();
  await expect(page.getByText("诊断 · 收集认知证据", { exact: true })).toBeVisible();
});

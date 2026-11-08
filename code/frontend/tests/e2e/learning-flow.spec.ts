import { expect, test } from "@playwright/test";

test("学生可以从登录进入诊断并看到可追溯的学习安排", async ({ page }) => {
  await page.setViewportSize({width:1440,height:1000});
  await page.goto("/");

  await page.getByRole("textbox", { name: "账号" }).fill("student1");
  await page.getByRole("textbox", { name: "密码" }).fill("demo-password");
  await page.getByRole("button", { name: /进入学习空间/ }).click();

  await expect(page.getByRole("region", {name:"知识地图与学习路径"})).toBeVisible();
  await expect(page.locator(".map-edge")).toHaveCount(2);
  // Canvas dimensions must not leak into toolbar icons and block node clicks.
  await expect(page.locator('.map-controls button').first().locator('svg')).toHaveCSS("height", "17px");
  await page.getByRole("button", {name:"栈的概念，证据不足", exact:true}).click();
  await expect(page.getByRole("heading", {name:"栈的概念", exact:true})).toBeVisible();
  const initialZoom = await page.locator(".map-controls span").textContent();
  await page.getByRole("button", {name:"放大地图", exact:true}).click();
  await expect(page.locator(".map-controls span")).not.toHaveText(initialZoom || "");
  await page.getByRole("button", {name:"定位当前学习目标", exact:true}).click();
  const scope = page.locator("#map-scope");
  await scope.click();
  await page.getByText("栈：从理解到应用", { exact: true }).click();
  await page.getByRole("button", { name: "确认范围" }).click();

  await page.getByRole("button", { name: "当前安排", exact:true }).click();
  await page.getByRole("button", { name: "开始初始诊断", exact:true }).click();
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

  await page.getByRole("button", { name: "查看反馈", exact: true }).click();
  await page.getByRole("button", { name: "完成本段并查看反馈" }).click();
  await expect(page.getByText("本段诊断已完成", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "继续下一段诊断" }).click();
  const dialog = page.getByRole("dialog");
  // Both segments use the same dialog title. Wait for the next segment's
  // unique content, not the previous dialog's title during its leave transition.
  await expect(dialog.getByText("栈的概念 · 理解", { exact: true })).toBeVisible();
  await dialog.getByRole("radio").first().focus();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await page.getByRole("button", {name:"知识点",exact:true}).click();
  await page.screenshot({path:"../../.local/learning-map.png",fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await expect(page.locator('.map-controls button').first().locator('svg')).toHaveCSS("height", "17px");
  await page.getByRole("button", {name:"定位当前学习目标",exact:true}).click();
  await page.locator('.map-node[aria-pressed="true"]').click();
  await expect(page.locator(".inspector-intro h2")).toBeVisible();
  await page.screenshot({path:"../../.local/learning-map-mobile.png",fullPage:true});
});

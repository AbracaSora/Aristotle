import { expect, test } from "@playwright/test";

test("学生可以从登录进入诊断并看到可追溯的学习安排", async ({ page }) => {
  await page.setViewportSize({width:1440,height:1000});
  await page.goto("/");

  await page.getByRole("textbox", { name: "账号" }).fill("student1");
  await page.getByRole("textbox", { name: "密码" }).fill("demo-password");
  await page.getByRole("button", { name: /进入学习空间/ }).click();

  await expect(page.getByRole("region", {name:"知识地图与学习路径"})).toBeVisible();
  const scope = page.locator("#map-scope");
  await scope.click();
  await page.getByText("栈：从理解到应用", { exact: true }).click();
  await page.getByRole("button", { name: "确认范围" }).click();

  await page.getByRole("button", { name: "当前安排", exact:true }).click();
  await page.getByRole("button", { name: "开始初始诊断", exact:true }).click();
  const practice = page.getByRole("region", {name:"独立答题页面"});
  await expect(practice.getByRole("heading", {name:"线性结构基础",exact:true})).toBeVisible();

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
  await expect(practice.getByRole("heading", {name:"栈的概念",exact:true})).toBeVisible();
  await expect(practice.locator(".quiz-top")).toContainText("理解");
  await practice.getByRole("button", {name:"返回学习空间"}).click();
  await expect(practice).toBeHidden();
  await page.getByRole("button", {name:"学习地图", exact:true}).first().click();
  await page.getByRole("button", {name:"线性结构与栈", exact:true}).click();
  const canvas = page.frameLocator('iframe[title="科目随机地形知识地图"]').getByRole("img", {name:"知识点及其先修关系图"});
  await expect(canvas).toBeVisible();
  await expect(page.locator(".curriculum-node")).toHaveCount(3);
  const successor = page.locator(".curriculum-node").filter({has:page.getByText("栈操作与分析", {exact:true})});
  await expect(successor).toContainText("待达标先修");
  await canvas.hover();
  await page.mouse.wheel(0, -220);
  await canvas.dblclick();
  await page.screenshot({path:"../../.local/learning-map.png",fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await expect(canvas).toBeVisible();
  await expect(page.getByRole("region", {name:"408 课程地图"})).toBeInViewport();
  await page.screenshot({path:"../../.local/learning-map-mobile.png",fullPage:true});
  const root = page.locator(".curriculum-node").filter({has:page.getByText("线性结构基础", {exact:true})});
  await root.getByRole("button").click();
  await expect(page.getByRole("region", {name:"课程掌握进度"})).toBeVisible();
});

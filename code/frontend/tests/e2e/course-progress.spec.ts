import { expect, test } from "@playwright/test";

test("全部答错仍锁定，订正两题解锁，最终小测通过才显示掌握", async ({page})=>{
  await page.goto("/");
  await page.getByRole("textbox",{name:"账号"}).fill("student2");
  await page.getByRole("textbox",{name:"密码"}).fill("demo-password");
  await page.getByRole("button",{name:/进入学习空间/}).click();
  async function map() {
    await page.getByRole("button",{name:"学习地图",exact:true}).first().click();
    await page.getByRole("button",{name:"data-structures",exact:true}).click();
    await page.getByRole("button",{name:"线性结构与栈",exact:true}).click();
  }
  const root=page.locator(".curriculum-node").filter({has:page.getByText("线性结构基础",{exact:true})});
  const child=page.locator(".curriculum-node").filter({has:page.getByText("栈的概念",{exact:true})});
  await map();
  await expect(child.getByRole("button")).toBeDisabled();
  await root.getByRole("button").click();
  const entry=page.getByRole("region",{name:"课程掌握进度"});
  await entry.getByRole("button",{name:"进入预设练习"}).click();
  const practice=entry.getByRole("region",{name:"课程预设练习"});
  const correctIds:string[]=[];
  for(let i=0;i<3;i++){
    // The published three baseline linear questions all have A as their correct option.
    await practice.getByRole("radio").nth(1).check();
    await practice.getByRole("button",{name:"提交本题"}).click();
    await expect(practice.getByRole("status")).toContainText("答错了");
    await expect(practice.getByText(`本轮已答 ${i+1} / 3 题`)).toBeVisible();
    const match=(await practice.getByRole("status").innerText()).match(/正确选项 ([A-H])/);
    expect(match).toBeTruthy();
    correctIds.push(match![1]);
  }
  await expect(entry.getByText(/各题最近一次答对 0 道/)).toBeVisible();
  await map();
  await expect(child.getByRole("button")).toBeDisabled();
  await root.getByRole("button").click();
  await entry.getByRole("button",{name:"进入预设练习"}).click();
  await entry.getByRole("button",{name:"重新练习并更新各题结果"}).click();
  for(const [i,id] of correctIds.slice(0,2).entries()){
    await practice.getByRole("radio").nth(id.charCodeAt(0)-65).check();
    await practice.getByRole("button",{name:"提交本题"}).click();
    await expect(practice.getByText(`本轮已答 ${i+1} / 3 题`)).toBeVisible();
  }
  await map();
  await expect(child.getByRole("button")).toBeEnabled();
  await root.getByRole("button").click();
  await expect(entry.getByRole("heading",{name:"课程进度 · 预设题已完成"})).toBeVisible();
  await entry.getByRole("button",{name:/生成最终小测/}).click();
  const paper=entry.getByRole("region",{name:"最终小测"});
  await paper.getByRole("group").first().waitFor();
  for(const field of await paper.getByRole("group").all()){
    await field.getByRole("radio").first().check();
  }
  await paper.getByRole("button",{name:"提交整卷"}).click();
  await expect(entry.getByRole("heading",{name:"课程进度 · 已掌握"})).toBeVisible();
  await page.setViewportSize({width:375,height:844});
  await expect(paper.getByRole("status")).toContainText("小测通过");
});

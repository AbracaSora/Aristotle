# Vue 与后端 API 联调记录

日期：2026-10-27。基础版本：后端原型 `19d1abe`，已推送至 `feat/backend-prototype`。本轮在 `feat/frontend-backend-integration` 分支完成对接，保留原型分支便于比较。尚未合并 master，不代表完整需求或发布验收通过。

## 1. 已接通的流程

| 前端页面/操作 | 使用的后端接口 | 行为 |
| --- | --- | --- |
| 登录、刷新会话、退出 | auth/login、auth/me、auth/logout | 以服务端身份获取个人数据，退出撤销令牌；过期清空视图并要求重登录 |
| 概览、知识地图 | knowledge、learning-state、history、materials | 展示真实图结构、先修约束、证据和计数；未满足先修的知识点入口禁用，服务端仍做校验 |
| 获取或继续关卡 | POST tasks、GET tasks/{id} | 不再使用前端写死的栈样例；按服务器任务展示题目，刷新后可恢复当前所属任务 |
| 提交与解析 | POST tasks/{id}/attempts | 答案与判分来自后端；反馈成功后重新读取状态与累计记录 |
| 学习记录 | GET history | 分页加载；累计作答 total、累计正确 correct_total 来自后端总量，不使用页长估算 |
| 文字资料 | GET/POST/PATCH/DELETE materials | 保存、确认、取消、纠正关联与删除均调用 API；成功后更新视图，失败不假装成功 |
| 维护者账号 | auth/me，管理工作台入口 | 不调用学生私人学习接口，提供独立内容工作台入口 |

拆分后的前端模块：`api.ts` 处理请求与错误；`types.ts` 描述接口；`useLearning.ts` 管理会话和异步业务状态；关卡、讲义与登录分别放入组件。App 保留原绿色布局并渲染服务端数据。

## 2. 数据与一致性

- 前端不再读取 `aristotle-demo-*` localStorage，也不自动上传或删除旧演示数据。
- sessionStorage 只保留当前标签页的令牌和按用户命名的任务 ID；题目、答案、作答、讲义和知识状态重新从后端读取。
- 一个提交编号对应原答案；网络结果不确定时保留编号并锁定改选，重试复用同编号。成功前不本地判分。
- 服务端保存成功但统计刷新失败时，保留已保存的反馈，并明确提示“作答已保存”。
- 每组异步操作捕获当前会话上下文；身份变化后不把旧响应写入新账号视图。切换身份先清空旧数据。
- 删除或取消资料关联后，当前任务的资料引用同步失效，避免继续展示已移除原文。

## 3. 与对接直接相关的后端修正

1. history 增加 total/correct_total，提供响应模型；分页不改变累计口径，按当前用户统计。
2. 修正 FR-4.2 的 last_at：从窗口内全部有效作答取最近时间；题数、正确率继续按每题首次有效作答计算。重复练习不会增加独立证据。

没有在本轮新增 PDF、真实模型调用、章节选择或开放题功能，未调整需求验收门槛。

## 4. 自动化检查

| 检查 | 本地结果与范围 |
| --- | --- |
| 后端 ruff 及格式 | 通过 |
| pytest | 35 项通过，包括新增的统计分页/账号口径与最近作答时间回归 |
| 前端测试类型检查与 Vitest | 10 项通过：网络重试编号、原答案保护、保存与统计失败分离、身份切换、刷新恢复、会话失效、资料失败及错误契约 |
| Vue 类型检查与 Vite 生产构建 | 通过；前端测试的 Node 类型配置独立于浏览器代码 |
| 原型 GitHub CI | `feat/backend-prototype` 的 Backend checks 已通过，运行 ID 40489767304 |

新分支添加 Frontend checks（Node 22、npm ci、测试、构建）；后端沿用原 workflow。本地通过不替代云端运行结果，实际状态查看 GitHub Actions。

## 5. 浏览器实测

使用独立本地联调数据库 `.local/integration.db`、后端 `127.0.0.1:8020`、前端 `127.0.0.1:5180`，不修改此前 `.local/aristotle.db` 的演示记录。实测步骤与观察：

1. Vue 登录 student1，读取初始零作答/零资料。
2. 请求关卡，取得后端的三道线性结构题；逐题提交，获得后端解析。第三题后概览显示 3 次正确作答，基础知识为初步掌握。
3. 点击下一任务，实际切换为栈理解题，界面显示通俗认知目标和题目版本。
4. 刷新页面后恢复登录、累计记录和未完成任务。
5. 新建文字讲义，显示待确认；确认后刷新，概览仍显示 1 份已确认资料。
6. 退出后切换 student2，作答/资料均为零；切回 student1，三条作答和讲义仍在。
7. 暂停本次联调后端，点击刷新，页面显示服务错误，未把旧记录改成零；重启同一数据库服务后刷新，错误消失且数据保留。
8. 知识地图显示基础已掌握、栈概念可继续、栈操作因先修不足禁用。

资料删除的数据库行为由后端测试覆盖；本轮浏览器手工核验了新增和确认，没有把未操作的浏览器删除、移动端或跨浏览器检查记为通过。

## 6. 启动与配置

标准端口启动见 [前端 README](../../code/frontend/README.md) 和 [后端 README](../../code/backend/README.md)。Vite `/api` 代理默认到 8018，`/backend-demo` 代理到同一后端的 `/demo`。

复用本轮独立联调环境时，在仓库根目录：

```bash
ARISTOTLE_DATABASE_URL=sqlite:///.local/integration.db uv run python -m aristotle_backend.seed --demo
ARISTOTLE_DATABASE_URL=sqlite:///.local/integration.db uv run uvicorn aristotle_backend.app:create_app --factory --host 127.0.0.1 --port 8020
```

另开终端进入 `code/frontend`：

```bash
ARISTOTLE_BACKEND_URL=http://127.0.0.1:8020 npm run dev -- --host 127.0.0.1 --port 5180 --strictPort
```

演示账号 student1/student2/editor，默认密码 demo-password。业务数据库、令牌和任何真实凭据不提交 Git。

## 7. 未覆盖的需求

本轮完成的是已有 API 与 Vue 的对接。真实 LLM/PDF、章节范围选择、完整诊断轮次/任务跳过与回退、学生报错、模型管理及正式内容仍有缺口。没有开展规定规模的并发、备份恢复、标签准确率、学习效果或完整 AC/NFR 验收。

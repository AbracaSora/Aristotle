# 后端 API 联调约定 v0.1（基础接口）

状态：后端原型已实现，Vue 学习端已接入，整体需求与正式发布仍待评审验收。基础路径 `/api/v1`，内容为 JSON，认证为 `Authorization: Bearer <access_token>`。时间字段使用 UTC Unix 秒，前端 `new Date(created_at * 1000)` 转成本地时间显示。

2026-10-28 新增范围、诊断轮次、任务动作、资料 job、mock 标注、纠错和系统管理，见 [原设计对齐流程与新增 API](design_aligned_workflow.md)。本页保留基础接口约定；新学习端使用 `/diagnostics` 和 `/recommendations` 代替旧的通用 `/tasks` 创建入口。

运行时 `/openapi.json` 是机器契约，`/docs` 可交互调用。公开题目响应模型不含答案和解析；只有维护者题目接口，以及学生自己的已提交作答反馈可以包含这些字段。

## 1. 路由清单

| 方法及路径（省略 /api/v1） | 权限 | 说明 |
| --- | --- | --- |
| POST /auth/login | 匿名 | username、password；返回令牌、过期时间和身份 |
| GET /auth/me | 已登录 | 当前用户与角色 |
| POST /auth/logout | 已登录 | 撤销当前令牌，204 |
| GET /knowledge | 已登录 | 当前图版本及节点/先修关系 |
| GET /learning-state | 学生 | 14 天知识状态与各认知维度摘要 |
| POST /tasks | 学生 | 请求诊断/练习任务；保存选题与证据快照，201 |
| GET /tasks/{task_id} | 所属学生 | 固定任务、公开题目和本人已提交反馈 |
| POST /tasks/{task_id}/attempts | 所属学生 | 程序判分、原子保存和幂等重放 |
| GET /history?limit=50&offset=0 | 学生 | 本人历史、累计作答 total 与累计正确 correct_total；包含停用题目标记；limit 最大 200 |
| GET /materials | 学生 | 本人未删除资料 |
| POST /materials | 学生 | 新文字资料，初始待确认，201 |
| PATCH /materials/{id} | 所属学生 | 修改知识点关联及确认状态 |
| DELETE /materials/{id} | 所属学生 | 清除当前业务字段原文并保留墓碑，204 |
| POST /admin/graphs | 维护者 | 校验并发布新图快照，201 |
| GET /admin/questions | 维护者 | 题目全部版本，含答案、解析和来源 |
| POST /admin/questions | 维护者 | 创建不可变内容版本，201 |
| POST /admin/questions/{key}/candidates | 维护者 | 手动录入候选并校验；不直接发布，201 |
| GET /admin/candidates | 维护者 | 候选及审核状态 |
| POST /admin/candidates/{id}/review | 维护者 | 批准/驳回；批准需核验内容与最终标签 |
| POST /admin/questions/{key}/retire | 维护者 | 停用版本并记录审计 |
| GET /admin/audit?limit=100 | 维护者 | 公共内容变更审计，limit 最大 200 |

`/health`、`/demo`、`/docs` 和 `/openapi.json` 不需要认证；它们不提供私人学习数据。其余权限由服务端逐请求验证，猜到另一学生的资源 ID 也返回 404。

## 2. 学习流程示例

登录：

```json
{"username":"student1","password":"demo-password"}
```

将返回令牌放入后续请求头。创建任务：

```json
{"mode":"diagnostic"}
```

也可请求 `{"mode":"practice","knowledge_id":"linear","target_level":"remember"}`；目标参数不是绕过先修的权限。省略参数由规则选择。原型只有一个数据结构演示图，尚无章节范围参数。

任务响应主要字段：

```json
{
  "id":"由服务端生成的任务 ID",
  "mode":"diagnostic",
  "graph_version":"ds-demo-v1",
  "policy_version":"baseline-0.1",
  "knowledge_id":"linear",
  "target_level":"remember",
  "status":"ready",
  "question_keys":["l1:v1","l2:v1","l3:v1"],
  "warnings":[],
  "reason":"基于知识状态与先修约束的解释",
  "questions":[
    {"key":"l1:v1","question_id":"l1","version":1,"knowledge_id":"linear","prompt":"线性结构中，元素之间的基本关系是？","options":["一对一","一对多","多对多"],"level":"remember","status":"published","dataset":"demo-seed"}
  ],
  "materials":[],
  "attempts":[]
}
```

上例省略时间、资料 ID、证据快照、其他题目和说明字段，完整结构以 OpenAPI 为准。`status=material_review` 表示只有资料可复习；`content_unavailable` 表示该目标无题也无已确认资料，两者都不是“关卡已完成”。少于 3 题将返回明确 warnings。

提交至 `POST /tasks/{id}/attempts`：

```json
{"question_key":"l1:v1","selected":"一对一","submission_id":"b7d3df34-6a21-42c1-91ad-b6e8bc920771"}
```

`submission_id` 在用户第一次点击时生成，**网络超时、响应丢失后的重试复用原值**。同一任务同题只接受首次答案；同键用于不同题/任务/选项返回 409。首次成功 `replayed=false`；重复成功返回同一作答记录且 `replayed=true`，不会增加历史条数或证据。错误选项不属于题目选项时返回 422。

提交响应包含 selected、correct、answer、explanation、题目版本和作答时间。之后可重新读取 `/learning-state`，或者再请求 `/tasks` 获取新的推荐。历史保留同题重复练习，但规则窗口内每个稳定题目 ID 只计首次有效证据。

## 3. 资料

```json
{"title":"栈笔记","text":"后进先出，操作发生在栈顶。","knowledge_id":"stack"}
```

文字上限 20,000 字符、标题上限 80；空白正文无效。新资料总是 `confirmed=false`。确认或纠正关联：

```json
{"knowledge_id":"stack","confirmed":true}
```

目前来源仅为“粘贴文本第 1 段”，未实现 PDF 页码或片段检索。删除后历史任务的资料引用返回 `unavailable=true` 和原因；不再返回原文。取消或改变关联同样会阻止旧任务继续展示不匹配资料。

## 4. 维护与审核

创建题目请求必须包含 `question_id`、递增整数 version、knowledge_id、prompt、唯一 options、属于选项的 answer、explanation、source。题目键由服务端生成，如 `team_example_1:v1`。内容修改需要新版本，新版本从草稿重新审核；旧任务仍绑定旧版本。

候选请求示例：

```json
{"question_id":"team_example_1","question_version":1,"primary_level":"remember","secondary_levels":[],"rationale":"需要识别线性结构的一对一关系，属于事实提取。","confidence":0.5,"ambiguity_note":""}
```

主标签与次标签使用六类英文枚举，次标签不重复、不包含主标签；理由非空，confidence 限制为 0—1。题目版本不符返回 409；非法标签、非法字段或伪造审核状态返回 422。当前 provider 固定为 `manual-prototype`，没有真实模型调用。

审核请求：

```json
{"decision":"approve","reason":"核验了答案、解析及认知要求","final_level":"remember","content_verified":true}
```

驳回使用 `decision=reject` 并填写理由。已批准版本不可重新标注；并发批准通过题目状态条件更新保证只有一个审核生效。评价/创造标签可保留在内容库，但首版选题不会分配它们。

## 5. 错误与兼容

业务错误统一为 `{"error":{"message":"可展示原因"}}`；输入错误额外带 fields（location、message、type），不回显密码或私人原文。OpenAPI 对 401/403/404/409/422/503 使用统一 ErrorView 响应定义。

| HTTP | 前端行为 |
| --- | --- |
| 401 | 会话无效，重新登录 |
| 403 | 角色不具备权限，不重试提交 |
| 404 | 资源不存在或不属于当前账号 |
| 409 | 幂等冲突、状态/版本变化或先修未满足；展示原因并刷新 |
| 422 | 修正输入，不自动循环重试 |
| 503 | 尚无知识结构，维护者需初始化或发布 |

SQLite 竞争、服务故障等非业务错误不应被前端当作成功；本原型尚未实现统一追踪 ID、故障告警及所有 5xx 的 JSON 错误模型。

Vue 现在通过上述接口创建新任务与作答；业务数据不再写入 localStorage。旧浏览器记录只有题目 ID、对错、时间，无法作为可信服务端作答导入，本次不自动读取、上传或删除它们。登录令牌与当前任务 ID 仅保留在当前标签页 sessionStorage。

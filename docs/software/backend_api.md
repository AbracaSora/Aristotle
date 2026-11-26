# 后端 API 联调约定 v0.1（基础接口）

2026-11-23：408 课程、完整预设任务、完成度/解锁及 AI 最终小测接口已补齐，见 [实现对照与部署](apifox_api_408_implementation_check.md)。新对象使用 ISO 时间；旧诊断任务仍按本页约定，预设任务响应使用新版结构。

状态：后端原型已实现，Vue 学习端已接入，整体需求与正式发布仍待评审验收。基础路径 `/api/v1`，内容为 JSON，认证为 `Authorization: Bearer <access_token>`。时间字段使用 UTC Unix 秒，前端 `new Date(created_at * 1000)` 转成本地时间显示。

2026-10-28 新增范围、诊断轮次、任务动作、资料 job、mock 标注、纠错和系统管理，见 [原设计对齐流程与新增 API](design_aligned_workflow.md)。本页保留基础接口约定；新学习端使用 `/diagnostics` 和 `/recommendations` 代替旧的通用 `/tasks` 创建入口。

运行时 `/openapi.json` 是机器契约，`/docs` 可交互调用。公开题目响应模型不含答案和解析；只有维护者题目接口，以及学生自己的已提交作答反馈可以包含这些字段。

2026-11-26 的内部重构将一次学习操作的会话、用户和时间归入 `LearnerAction`；诊断与推荐使用含知识图、作答和状态的 `LearningRun`。生成模型调用由 `ModelContext` 传递会话和调用者，`GenerationPrompt` 传递用途、指令、输入和输出预算。前端继续使用已导出的 [OpenAPI 契约](openapi.json)，测试比对全部路径、方法、参数、响应及组件。

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

直接粘贴来源为“粘贴文本第 1 段”；已确认来源现可分段检索并保留字符位置，文本型 PDF 抽取现通过 `POST /material-imports/pdf` 排队导入并保留页码，扫描件不支持 OCR。删除后历史任务的资料引用返回 `unavailable=true` 和原因；不再返回原文。取消或改变关联同样会阻止旧任务继续展示不匹配资料。

## 4. 维护与审核

创建题目请求必须包含 `question_id`、递增整数 version、knowledge_id、prompt、唯一 options、属于选项的 answer、explanation、source。题目键由服务端生成，如 `team_example_1:v1`。内容修改需要新版本，新版本从草稿重新审核；旧任务仍绑定旧版本。

候选请求示例：

```json
{"question_id":"team_example_1","question_version":1,"primary_level":"remember","secondary_levels":[],"rationale":"需要识别线性结构的一对一关系，属于事实提取。","confidence":0.5,"ambiguity_note":""}
```

主标签与次标签使用六类英文枚举，次标签不重复、不包含主标签；理由非空，confidence 限制为 0—1。题目版本不符返回 409；非法标签、非法字段或伪造审核状态返回 422。此手工候选入口使用 `manual-prototype`；真实模型候选使用第 6 节的独立入口，同样进入人工审核。

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

数据库竞争、服务故障等非业务错误不应被前端当作成功；本原型尚未实现统一追踪 ID、故障告警及所有 5xx 的 JSON 错误模型。

Vue 现在通过上述接口创建新任务与作答；业务数据不再写入 localStorage。旧浏览器记录只有题目 ID、对错、时间，无法作为可信服务端作答导入，本次不自动读取、上传或删除它们。登录令牌与当前任务 ID 仅保留在当前标签页 sessionStorage。

## 6. 学习地图、检索与真实模型（2026-11-08）

路径均以 `/api/v1` 为前缀，须携带现有 Bearer 会话。结构以 OpenAPI 为准；完整业务及模型配置见 [学习空间实现](learning_space_implementation.md)。

| 方法与路径 | 请求 / 返回要点 |
| --- | --- |
| `GET /knowledge-map` | 学生；已发布版本、全图 nodes/edges、本人 states、window_days；不创建任务 |
| `GET /model-status` | 已登录；仅 configured/model/namespace、enabled、storage；不探测模型、不返回密钥 |
| `GET /retrieval/sources?knowledge_id=stack` | 学生；本人可用来源、位置、授权状态；linked-sources 不表示语义命中 |
| `POST /retrieval/search` | query、knowledge_id、mode（keyword/semantic/hybrid）、limit（1–12）；语义类须 allow_external_query=true |
| `POST /retrieval/index` | knowledge_id、allow_external=true；202 返回 live_index job |
| `PATCH /materials/{id}/external-consent` | allowed 布尔值；本人资料，撤销即清理派生索引及相关旧解释 |
| `POST /explanations` | knowledge_id、query、source_keys（1–6 个）、allow_external=true；可带本人 attempt_id；202 返回 live_explanation job |
| `POST /admin/questions/{key}/model-annotations` | 维护者；无需正文，仅可草稿/待审核版本；202 返回 live_annotation job，候选不会自动发布 |
| `GET /jobs/{id}` | 查询本人任务；status、result、implementation、知识点/作答上下文 |
| `POST /model-jobs/{id}/dispatch` | 显式执行本人 queued 真实任务；多次竞争只领取一次 |
| `POST /model-jobs/{id}/retry` | 仅 failed 且 retryable 的本人真实任务；重新计入调用配额 |
| `GET /admin/model-calls` | 管理员；最近 100 条调用状态、用量和耗时，不含输入正文 |

新任务返回 202 表示已接收，不能作为模型成功；轮询 `/jobs/{id}` 直到 succeeded/failed。默认后端响应后执行，也支持独立 worker。mock `/jobs/{id}/run` 不接受真实任务。关键词检索不发外部请求；语义查询是有总预算的同步请求，前端对应超时为 65 秒。私人资料须逐份授权，不能只用请求中的 allow_external 绕过。

索引按批处理。每批选择片段和每次调用模型前都会重新读取授权与片段指纹，供应商返回可重试错误时也重新检查。若撤回已生效，后续批次跳过该私人片段，携带旧片段的整次重试终止。保存向量或解释前再核对一次。已经送达供应商的请求无法追回。

模型相关错误额外包含 `error.code`：403 consent_required、409 source_unavailable、413 scope_too_large、429 quota_exceeded、503 not_configured/disabled；无有效语义索引明确提示，不用关键词结果冒充。供应商或输出校验错误为 502；异步执行的错误记录在失败 job 中，返回可展示的脱敏原因。

## 2026-11-25 资料导入与服务配置更新

`POST /material-imports/pdf` 使用 multipart：file 为PDF、title可选（1–80字），成功返回202 queued。鉴权并选择学习范围后可用；文件超过20MB返回413，非法头返回422。使用本人 `POST /jobs/{id}/run` 领取真实抽取，成功返回 material_id/chunk_count/requires_confirmation；加密、无文本层、损坏或超过100页写入failed及明确原因。抽取结束删除任务中的临时PDF字节，来源片段保持待确认。当前没有PDF自动worker，性能与资源隔离待专项验收。

管理员 provider-settings 增加 live 模式；超时/重试/任务总预算/标注限额实际作用于真实适配器。真实服务地址、模型名和密钥由后端环境变量配置，model_name原模拟字段为旧界面兼容；返回implementation=runtime-config。个人默认100次/日，标注全局默认200次/日，按上海自然日预留重试调用额度。模型任务从创建时计算总预算，包含排队，超时不再开始外部调用。小测反馈失败提供error_code及规则建议，成绩先保存。

最终小测整卷提交后，服务端先保存评分和掌握事件，随后生成学习建议。评语最多使用该学生在本次交卷时间之前的五条答题记录，按服务端时间从近到远选取。时间相同的记录因无法确定先后顺序而排除。即使稍后才恢复生成，后续练习和试卷也不会进入这次反馈。

恢复进程每批最多选取 20 条未领取或领取已超过 30 分钟的待处理评语。未领取的可继续处理，超时领取的保留规则建议并记录 `interrupted`。已超时的出卷任务收到迟到的模型响应时，仍保留原来的中断状态。[小测课程回归](../../tests/integration/test_curriculum_contract.py)


完整开发/运行边界见 [后端对齐记录](backend_alignment_20261125.md)。

## 资料worker补完（2026-11-26）

资料任务现可由`python -m aristotle_backend.import_worker`自动处理；原本人`POST /jobs/{id}/run`复用同一领取逻辑。任务冻结范围/图版本，抽取前后重查权限，完成/失败清理任务内原PDF。PDF在独立进程中受30秒墙钟/CPU限制；Linux限512MiB地址空间，macOS不宣称相同内存硬限制。运行60秒未完成和排队24小时过期任务标失败并要求重新上传。详见[实现与验证](worker_and_logs_20261126.md)。

## 408 课程先修门槛与重练（2026-11-26）

所有直接前驱分别完成当前非空预设集合，且每个前驱最近一次答对的不同题目数均达到本集合题数的三分之二（含等号），后继才解锁。课程批量／单点／详情返回最新答对题数、所需题数和先修资格。重练走 `POST /api/v1/tasks/{task_id}/retry-preset`。完成、解锁和最终小测掌握分别判定，详见[交接最新规则](backend_handoff_objects_408.md)。

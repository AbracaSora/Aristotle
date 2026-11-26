> **2026-11-26 数据库状态更新：连接问题已解决。** 真实 PostgreSQL 集成测试110项全部通过；业务库已升级至 `0003_curriculum_tests`，原有22张表共148条记录的行数全部保持不变，新增7张表，pgvector 0.8.7 可用。未导入演示数据、未重建业务库。证据：[PG测试日志](quality_evidence/after/postgresql-tests.txt)、[迁移行数核对](quality_evidence/after/business-migration.json)。下文“Docker不可连接/迁移未执行”的历史记录已被本次结果取代；其余质量与人工验收未据此自动通过。

# 408 API：交接契约与后端实现对照

对照日期：2026-11-23。以 [对象交接 v1.5](backend_handoff_objects_408.md) 为依据；本次补齐后端核心流程，前端切换和真实模型出题质量验收仍需单独进行。运行时 `/openapi.json` 是机器契约，可直接导入 ApiFox；仓库也提供本轮导出的 [OpenAPI 文件](openapi.json)，无需启动服务即可查看和导入。

## 已实现的接口

下表路径均省略 `/api/v1`。成功直接返回业务对象，错误为 `{"error":{"message":"...","fields":[]}}`，`fields` 可省略。没有 `success/data/request_id` 外层包装。

| 方法 | 路径 | 返回与行为 |
|---|---|---|
| GET | `/subjects` | 四科 → 章节 → 已发布知识点；直接数组；无用户进度、无 graph_version 包装 |
| GET | `/tags` | 内容标签字典；Bloom 不混入标签 |
| GET | `/knowledge-points/{id}/questions` | 完整预设集合，固定顺序；锁定 409；不创建任务、不泄露答案 |
| POST | `/tasks` | `{mode:"practice", knowledge_id}`；课程知识点创建完整集合任务，201；相同用户/集合版本恢复 200 |
| POST | `/tasks/{id}/retry-preset` | 本轮已完成可新建订正轮，保留旧答案；重试返回同一订正任务 |
| GET | `/tasks/{id}` | 用户自己的任务、已提交反馈、下一未答题；预设任务为 `activity=preset_practice` |
| POST | `/tasks/{id}/attempts` | 接受 `selected_option_id`；兼容旧 `selected` 文本，冲突值 422；按用户＋任务＋submission_id 幂等 |
| GET | `/knowledge-points/{id}/progress` | locked / available / completed / mastered 四态摘要 |
| GET | `/progress?subject_id=...` | 同一计算服务的批量摘要，直接数组 |
| GET | `/knowledge-points/{id}/progress-detail` | 第 3 节细粒度 KnowledgePointProgress，含完成率、正确率、当前集合和小测资格 |
| POST | `/knowledge-points/{id}/ai-tests` | 202，持久化生成请求；相同 request_id 不重复出卷 |
| GET | `/knowledge-points/{id}/ai-tests` | 本人历史，版本倒序，limit=20（1–100）、offset=0 |
| GET | `/ai-tests/{id}` | 生成轮询、固定题目、整卷提交结果；他人试卷 404 |
| POST | `/ai-tests/{id}/submit` | 整卷等权判分、保存通过证据、反馈和事件；不写入预设题 Attempt |
| POST | `/admin/curriculum` | 维护者发布完整课程配置，校验章节、DAG、标签、已发布题、冻结版本及选项映射 |
| GET | `/admin/standard-questions/{key}` | 维护者查询标准完整题对象；学生不可访问 |

旧 `/diagnostics` 和 `/learning-state` 保留原来的诊断证据含义。推荐仍依据多题证据选择活动；正式课程中的目标同时以 mastery-v2 的直接前驱条件决定能否进入；其中 `provisional` 不能代表新课程的 `completed`。`/curriculum-progress` 在课程启用后复用新进度计算，继续提供旧 `{知识点:{total,completed}}` 形式。课程启用后，孤立的 `/admin/graphs` 发布被拒绝，须通过 `/admin/curriculum` 同时验证章节、预设集合和知识关系，避免两个图来源不一致。

## 核心规则

- 当前集合中提交不同的 question_key 计完成，答错也计完成。正确率另算；同题不同版本分别处理；重复请求不新增记录。
- 所有直接前驱分别完成当前非空预设集合，且每个前驱最近一次答对的不同题目数均达到本集合题数的三分之二（含等号），后继才解锁。无需前驱 AI 小测通过；零题前驱不视为完成。
- 无提交 new、部分提交 learning、全部完成 covered、通过本集合最终小测 mastered。摘要将前两者映射为 available；锁定优先。
- 预设题集合、题目元数据和小测试卷均保留版本。相同版本不能覆盖内容；题目换版后依当前集合重算完成度，旧任务和作答不覆盖。
- 新集合不沿用旧集合的 AI 通过证据；仍属当前集合的历史 question_key 可继续计完成。本轮没有实现历史关系变更后的状态迁移。
- 有 generating/ready 小测时暂不允许替换该知识点的预设集合，避免未提交试卷在提交过程中改变掌握度归属。须先完成小测或确认生成失败；这是当前发布保护边界，后续可另定作废流程。
- 小测题和标准答案只保存在用户所属试卷，未整卷提交前不返回答案和解析，不自动发布进公共题库。
- 小测先提交判分事务，再读取本人最近记录并调用模型生成建议。上下文和模型反馈不能改成绩；历史读取失败继续判分，模型失败返回规则反馈。

## 前端联调顺序与兼容边界

1. `/subjects` 获取内容，`/progress` 获取唯一用户状态来源。地图和学习中心都用这份状态，不从本地计数或旧诊断颜色推导。
2. 只读预设题可调用 `/knowledge-points/{id}/questions`；实际作答先 `POST /tasks` 获得任务 ID。
3. 课程预设任务返回 `PresetTaskView`：`questions` 是新 QuestionPublic（`stem`、`options:[{id,text}]`），`attempts` 是新反馈，`next_question_key` 供恢复定位；`created_at` 仍为既有任务的 Unix 秒。
4. 旧诊断/推荐任务继续返回旧 TaskView，保留 `prompt`、字符串选项、旧生命周期字段。按 `activity=preset_practice` 区分，不能把新任务直接套进旧 TaskView。
5. 提交 `selected_option_id` 得新反馈（ISO 时间、`answer.option_id`）；提交旧文本 `selected` 得旧反馈（Unix 秒、答案文本）。两值同时传入必须一致。旧任务也接受选项 ID，按该版本原顺序 A–H 映射。
6. 预设题提交后刷新 `/progress`，后继解锁立即可见。只有后端 `ai_test_eligible=true` 才展示创建入口；仍由服务端二次校验。
7. 小测创建后轮询详情，ready 才显示固定题目；一次提交全卷，不能逐题调用预设题作答接口。
8. 提交响应包含 `learning_feedback` 和 `events`。动画按 event_id 去重；重放可能带回相同事件。小测记录与预设作答历史分开查询。

本次未修改前端本地题库或 UI。前端尚需移除学生作答前可见的本地答案/解析，并接入新小测和进度接口；后端验收不等于前端已完成切换。

## 部署与数据

新增迁移 `0003_curriculum_tests`：7 张课程/预设集合/标准题快照/任务绑定/小测表，调整 Attempt 幂等唯一键。迁移只改表结构，不导入演示数据、不清空原记录。

```bash
uv run python -m aristotle_backend.migrations
```

已有本地演示环境需要显式运行以下命令填充标准课程表；导入器可重复执行，保留历史。它会使用现有四科资源，发布为 **demo-seed 演示内容**，不是正式审核题库：

```bash
uv run python scripts/import_resource_demo.py --demo
```

资源数据保持 4 科、24 章、203 知识点、650 题。`past_exam_adapted` 适配为 `source.type=authored`，原始改编类型与待审核说明保留在 title，原题链接、年份和题号保留；不把改编题称作原题。数字难度没有已确认映射，因此标准视图暂为 null。标准元数据时间表示此次适配记录的建立时间，不伪造旧题原始创作时间。

正式内容走现有题目创建、人工审核发布流程，再由维护者 `POST /admin/curriculum` 指明来源类型、标签和当前预设集合。该接口拒绝 demo-seed 进入正式配置。`questions` 必须包含所引用的当前已发布版本；不存在或无法唯一映射旧答案的版本拒绝导入。

AI 小测复用 `ARISTOTLE_LLM_*` 服务配置、管理员禁用开关、调用配额和用量记录。创建后通过后台任务处理；若服务进程在领取前中断，另启持久队列 worker 处理尚未领取的试卷：

```bash
uv run python -m aristotle_backend.final_tests
# 或只处理一次
uv run python -m aristotle_backend.final_tests --once
```

已领取超过 30 分钟仍未完成的生成任务会标记 `generation_failed/interrupted`，不自动重放未知状态的外部请求。用户用新的 request_id 显式重试，得到新版本，保留失败历史。

## 验证与尚待工作

新增契约测试覆盖两账号隔离、多前驱/跨科前驱、零题、答错完成、五题完整集合、恢复任务、并发幂等、整卷校验、答案隔离、生成失败/恢复、模型反馈降级、题目和集合换版、发布校验、旧数据库升级与历史保留。模型通过 `httpx.MockTransport` 测试，不调用真实付费服务，不把模拟模型输出作为教学效果证据。

本轮已运行 SQLite 集成测试和 PostgreSQL 离线迁移 SQL 校验。真实 PostgreSQL 暂不可连接（本机 5433 拒绝连接、Docker daemon 不可连接），业务库尚未执行此次迁移。本轮最终后端测试为 121 passed、1 skipped（需 PostgreSQL），保留一条既有 TestClient 弃用提示；Ruff 检查、格式检查、git diff --check 通过，导出的 OpenAPI 与运行时契约一致。真实数据库验证、真实模型出题质量、前端联调分开验收。

本轮范围不包括 OCR、批量外部题库导入 UI、科目统计面板、正式题目内容审核、关系变化迁移。旧 ApiFox 草案里的单数 `/ai-test`、`/users/me/progress` 以及 `success/data` 包装均不再作为本次实现目标。

2026-11-25：已增加真实文本型PDF、规则版本完整输入、生效的模型配置/上海配额/任务预算、小测建议防重恢复。质量扫描及未关闭事项见 [code_quality.md](code_quality.md)、[code_review.md](code_review.md)、[对齐矩阵](backend_alignment_20261125.md)。

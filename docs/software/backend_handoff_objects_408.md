# 408 后端交接：标准化科目、章节、知识点与题目对象

日期：2026-11-23　版本：提案 v1.5（前端分工、上下文反馈与完成事件）

本文是待实现的数据契约，不代表接口已经上线。范围为知识结构、题库及必要的用户状态，不含 OCR。依据会议纪要和当前 `schemas.py` 设计；数据库表结构由后端决定。保留学习中心现有 UI，通过接口适配统一地图和学习中心的数据。

范围调整：课程结构按固定配置处理，保留后端现有 `graph_version` 字段用于标识当前课程图配置和问题追踪；不要求保存历史关系快照，也不考虑关系变化引起的解锁状态重算或迁移。解锁仅依据当前固定前驱关系与用户掌握状态计算。

## 1. 通用约定

- API 字段统一 `snake_case`；ID 是稳定字符串，不使用名称、数组下标或地图坐标作为 ID。兼容现有标识符约束：1–64 位字母、数字、下划线或连字符。
- 科目 ID：`data-structures`、`computer-organization`、`operating-systems`、`computer-networks`。
- 时间字段：新对象采用 UTC ISO 8601；旧接口仍为 Unix 秒，适配时显式转换，不直接改变旧接口语义。
- 比率范围 0–1；没有样本时为 `null`，不能用 0 表示未知。数组无数据返回 `[]`，可空字段显式返回 `null`。
- 以下字段表中，除明确标记可空外均必填。示例使用演示数据，不代表真实题目来源或审核结果。
- 对象定义与 HTTP 响应包装分离。现有 API 直接返回业务对象；不强制引入之前需求稿中的 `success/data/request_id` 包装。
- `graph_version`：当前课程图配置的稳定版本标识。已有知识图、学习状态和任务接口继续返回或保存该字段；`GET /api/v1/subjects` 保持直接返回科目数组，不增加外层响应包装，也不在该响应中新增 `graph_version`。它只用于前后端追踪、缓存和问题定位，不用于前端自行判定解锁，也不要求实现关系变化后的历史状态迁移。

### 1.1 科目对象 Subject

```json
{
  "id": "data-structures",
  "name": "数据结构",
  "description": "学习数据组织、存储及基本算法。",
  "order": 1,
  "status": "published"
}
```

### 1.2 章节对象 Chapter

```json
{
  "id": "ds-linear-lists",
  "subject_id": "data-structures",
  "name": "线性表",
  "description": "线性表的定义、存储结构及基本操作。",
  "order": 2,
  "status": "published"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 稳定标识，遵循通用 ID 约束 |
| `name` | string | 展示名称，1–100 字符 |
| `description` | string | 简介，允许空字符串 |
| `order` | integer | ≥0；科目全局排序，章节在所属科目内排序 |
| `status` | enum | draft/published/retired |
| `subject_id` | string | 仅章节对象需要，引用已存在的科目 |

三级关联为“科目 → 章节 → 知识点”：章节通过 subject_id 归属科目，知识点通过 chapter_id 归属章节；知识点的 subject_id 必须与所属章节一致。对象不重复保存完整子对象列表，查询时按父级 ID 聚合。章节和科目的完成率、正确率属于用户学习状态，由后端汇总计算，不放入公共内容对象。

## 2. 知识点对象 KnowledgePoint

知识点对象是公共课程内容，不包含某一用户的进度。地图只生成地理布局，不能改变章节归属与先修关系。

```json
{
  "id": "ds-sequential-list",
  "name": "顺序表",
  "subject_id": "data-structures",
  "chapter_id": "ds-linear-lists",
  "description": "理解顺序表的存储结构及插入、删除操作。",
  "order": 2,
  "prerequisite_ids": ["ds-linear-basics"],
  "tag_ids": ["linear-list", "sequential-storage"],
  "preset_set": {
    "id": "preset-ds-sequential-list",
    "version": 1,
    "question_keys": ["ds-seq-q001:v1", "ds-seq-q002:v1"],
    "question_count": 2
  },
  "status": "published",
  "updated_at": "2026-11-23T08:00:00Z"
}
```

| 字段 | 类型 | 说明与约束 |
|---|---|---|
| `id` | string | 知识点稳定 ID；名称调整不改变 ID |
| `name` | string | 展示名称，1–100 字符 |
| `subject_id` / `chapter_id` | string | 引用已存在科目和章节，章节必须属于该科目 |
| `description` | string | 学习目标或简述，允许空字符串 |
| `order` | integer | 章节内展示顺序，≥0；不是先修依据 |
| `prerequisite_ids` | string[] | 直接前驱，去重、不可包含自己；允许跨章节，必须引用固定课程配置中存在的节点 |
| `tag_ids` | string[] | 来自统一标签字典的 ID；不混用名称、ID 和 Bloom 层级 |
| `preset_set` | object | 当前预设题集合，确定“全部完成”的分母 |
| `preset_set.id` / `version` | string / integer | 集合稳定 ID、正整数版本 |
| `preset_set.question_keys` | string[] | 去重后的已发布题目版本键；顺序即默认出题顺序 |
| `preset_set.question_count` | integer | 必须等于 `question_keys.length`，服务端计算 |
| `status` | enum | `draft`、`published`、`retired` |
| `updated_at` | datetime | 内容更新时间 |

图发布时必须校验：所有引用存在、先修关系无环、章节归属合法、预设题存在且已发布。空预设题集合表示题目待补充，不自动视为完成。关系依据和审核信息可另存图谱维护记录，不根据随机地图位置反推关系。

## 3. 用户知识点状态 KnowledgePointProgress

这是独立于 KnowledgePoint 的个性化对象。用户身份由登录会话确定，前端不能提交掌握状态或传入任意用户 ID 更新进度。

```json
{
  "knowledge_id": "ds-sequential-list",
  "policy_version": "mastery-v1",
  "preset_set_id": "preset-ds-sequential-list",
  "preset_set_version": 1,
  "mastery_status": "learning",
  "unlocked": false,
  "unmet_prerequisite_ids": ["ds-linear-basics"],
  "preset_total": 2,
  "preset_completed": 1,
  "completion_rate": 0.5,
  "attempt_count": 1,
  "correct_attempt_count": 0,
  "accuracy": 0,
  "ai_test": {"eligible": false, "latest_test_id": null, "passed_test_id": null},
  "updated_at": "2026-11-23T08:30:00Z"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `knowledge_id` | string | 对应 KnowledgePoint.id |
| `policy_version` | string | 本次计算使用的掌握度与解锁判定规则版本 |
| `preset_set_id` / `preset_set_version` | string / integer | 与知识点预设题集合一致 |
| `mastery_status` | enum | `new`、`learning`、`covered`、`mastered` |
| `unlocked` | boolean | 是否允许进入该知识点，服务端计算 |
| `unmet_prerequisite_ids` | string[] | 未达解锁门槛的直接前驱；解锁时为空 |
| `preset_total` / `preset_completed` | integer | 预设题总数、已提交的不同题目版本数，0≤completed≤total |
| `completion_rate` | number或null | completed/total；total=0 时为 null |
| `attempt_count` / `correct_attempt_count` | integer | 当前预设题集合中有效提交次数、正确次数；排除 AI 小测和幂等重放 |
| `accuracy` | number或null | correct_attempt_count/attempt_count；无作答为 null |
| `ai_test.eligible` | boolean | 是否允许创建最终小测，服务端最终校验 |
| `ai_test.latest_test_id` | string或null | 最近一次最终小测 |
| `ai_test.passed_test_id` | string或null | 支撑当前紫色状态的已通过小测 |
| `updated_at` | datetime | 进度更新时间 |

### 判定规则与待确认项

会议已经明确：未提交任何预设题为 `new`；提交部分为 `learning`；所有预设题完成为 `covered`；最终 AI 小测通过为 `mastered`。有效提交即计为完成，答错不等于未完成；正确率独立记录。重复提交同题不增加完成题数。零题节点保持 `new` 且不可开始小测。

**已确认的解锁门槛：**所有直接前驱的预设题全部完成，即解锁当前知识点，无需通过 AI 小测；没有前驱的已发布节点直接解锁。有效提交即算完成，不要求全部答对。零题前驱不视为完成。当前实现使用的 `provisional` 只是旧证据状态，不可直接映射成 `covered`，需要依据预设题提交记录计算。

锁定与掌握是两个维度：没有前驱的知识点即使未学习也可解锁，有未掌握前驱的知识点则锁定；不能仅凭自身 mastery_status 判断能否进入。前端优先将 `unlocked=false` 显示为灰色并禁止进入；否则按 mastery_status 着色。地图和学习中心必须读取同一结果。不设计关系变更导致的重新锁定或进度迁移流程。

AI 最终小测的通过分数、题数、重测间隔尚需产品确认，并随测试保存规则快照；日常 AI 变式练习不得直接赋予 `mastered`。首次最终小测仅在 `covered` 且已解锁时开放；已通过用户是否重测另行配置，失败重测不自动删除既有通过证据。

更换预设集合或题目版本时，应创建新版本并重新计算该集合的完成率；历史作答与通过记录保留。建议新集合需重新满足完成和小测条件，不静默沿用旧紫色状态；具体迁移政策发布前确认。

## 4. 题目对象 Question（服务端完整对象）

第一阶段只承诺单选题 `single_choice`，与现有判分能力一致；多选和主观题需另定答案模型及评分契约后扩展。

```json
{
  "question_id": "ds-seq-q001",
  "version": 1,
  "key": "ds-seq-q001:v1",
  "knowledge_id": "ds-sequential-list",
  "related_knowledge_ids": [],
  "type": "single_choice",
  "stem": "在顺序表中随机访问一个元素的时间复杂度是？",
  "content_format": "plain_text",
  "options": [
    {"id": "A", "text": "O(1)"},
    {"id": "B", "text": "O(n)"},
    {"id": "C", "text": "O(n²)"},
    {"id": "D", "text": "O(log n)"}
  ],
  "answer": {"option_id": "A"},
  "explanation": "顺序表可通过首地址和下标直接计算元素地址。",
  "tag_ids": ["sequential-storage", "time-complexity"],
  "bloom_level": "understand",
  "secondary_bloom_levels": [],
  "difficulty": null,
  "source": {"type": "authored", "title": "演示样题", "year": null, "question_number": null, "url": null},
  "review_status": "draft",
  "dataset": "demo-seed",
  "created_at": "2026-11-23T08:00:00Z",
  "updated_at": "2026-11-23T08:00:00Z"
}
```

| 字段 | 类型 | 说明与约束 |
|---|---|---|
| `question_id` | string | 逻辑题目稳定 ID |
| `version` / `key` | integer / string | 正整数版本；key 必须为 question_id + `:v` + version |
| `knowledge_id` | string | 主知识点，决定完成统计归属 |
| `related_knowledge_ids` | string[] | 关联知识点，去重且不包含主知识点；不自动给这些节点增加完成数 |
| `type` | enum | 本阶段固定 `single_choice` |
| `stem` | string | 题干，1–5000 字符 |
| `content_format` | enum | 本阶段固定 plain_text；题干、选项和解析作为纯文本显示，公式、图片后续扩展 |
| `options` | object[] | 2–8 项；每项 id 非空且版本内唯一、text 非空且不重复 |
| `answer.option_id` | string | 必须引用该版本一个有效选项 ID |
| `explanation` | string | 标准解析，1–5000 字符 |
| `tag_ids` | string[] | 统一内容标签字典 ID；与 Bloom 分开 |
| `bloom_level` | enum或null | remember/understand/apply/analyze/evaluate/create；草稿可空，发布必须确认 |
| `secondary_bloom_levels` | enum[] | 同上枚举；不可重复或包含主层级 |
| `difficulty` | enum或null | easy/medium/hard；未知为 null，不根据 Bloom 自动推算 |
| `source` | object | 来源；type 为 past_exam/authored/ai_generated，title 非空 |
| `source.year` | integer或null | 真题年份，非真题可空 |
| `source.question_number` / `source.url` | string或null | 原题题号、可核验链接；不伪造来源 |
| `review_status` | enum | draft/pending_review/published/retired，与现有发布流程一致 |
| `dataset` | string | 保留现有数据集标记，demo-seed 明确表示演示内容 |
| `created_at` / `updated_at` | datetime | 当前内容版本的时间 |

公共题库只有已审核发布版本可分配给学生；动态小测题只在所属用户的测试会话中使用，不自动发布进公共题库。正式发布与待审核、演示数据必须清晰区分。

## 5. 对外返回视图与提交契约

### 学生作答视图 QuestionPublic

从完整对象中选择返回：question_id、version、key、knowledge_id、related_knowledge_ids、type、stem、content_format、options、tag_ids、bloom_level、secondary_bloom_levels、difficulty、source、review_status、dataset。**不得返回 answer 或 explanation**，也不得将这些字段藏在浏览器本地题库中。

### 已提交反馈 QuestionFeedback

继续复用 `POST /api/v1/tasks/{task_id}/attempts`；新提交结构作为后续兼容版本提案：

```json
{
  "question_key": "ds-seq-q001:v1",
  "selected_option_id": "A",
  "submission_id": "submission-unique-001"
}
```

返回对象建议：

```json
{
  "attempt_id": "attempt-001",
  "question_key": "ds-seq-q001:v1",
  "selected_option_id": "A",
  "correct": true,
  "answer": {"option_id": "A"},
  "explanation": "顺序表支持通过下标直接计算地址。",
  "replayed": false,
  "created_at": "2026-11-23T08:30:00Z"
}
```

标准答案与解析仅向题目维护者及该用户允许查看反馈的会话返回。最终小测在整卷提交后才返回反馈，不能逐题泄露答案。

提交时校验题目版本属于该用户任务、选项存在、先修条件满足；诊断是否允许越过先修需单独定义模式权限，不能绕过普通练习的锁定规则。同一用户、任务、submission_id 的相同请求返回原结果，replayed=true；同键不同答案返回 409。保存答题与更新进度必须在同一事务内完成。

## 6. 与现有实现的字段映射

| 当前字段 | 标准字段 | 迁移说明 |
|---|---|---|
| Node.id/name | KnowledgePoint.id/name | 原值保留 |
| Node.prerequisites | prerequisite_ids | 字段重命名；增加科目、章节等内容字段 |
| QuestionInput.prompt | stem | 旧接口题干字段映射 |
| options: string[] | options: {id,text}[] | 旧版本按原选项顺序分配 A–H，映射冻结保存 |
| answer: string | answer.option_id | 用旧答案文本匹配唯一选项，匹配失败拒绝迁移并报错 |
| question_id/version/key/knowledge_id | 同名字段 | 保留当前稳定 ID 和版本键 |
| level、候选 primary_level | bloom_level | 使用人工审核确认的最终标签；不是任意候选标签 |
| 候选 secondary_levels | secondary_bloom_levels | 仅纳入经过确认的标签 |
| status | review_status | 发布状态统一命名；不是用户掌握状态 |
| source: string | source 对象 | 保留原文为 title；无结构化依据时先人工确认 type，不能推断为真题 |
| 本地 Label/label/tags | tag_ids | 建字典并去重映射，不直接混入认知层级 |
| KnowledgeState.status | 旧证据状态 | insufficient/needs_review/provisional 不能直接转换四级掌握度；从作答和小测记录重新计算 |
| unmet_prerequisites | unmet_prerequisite_ids | 确认使用新解锁规则后再转换 |
| AttemptInput.selected | selected_option_id | 旧客户端仍提交文本，兼容层按题目版本转换；不能同时接受冲突的两种值 |

历史题目版本与作答记录不可覆盖。内容修订新增 version，旧任务继续使用原版本快照。旧接口保留原字段及时间单位，新前端通过适配层使用本标准；启用正式契约前同步更新 OpenAPI 和 ApiFox 文档。

## 7. 后端交付与验收

1. 知识图接口提供 KnowledgePoint；进度接口提供当前用户的 KnowledgePointProgress，可按 knowledge_id 关联，并可返回当前 `graph_version` 供追踪。地图和学习中心使用同一固定课程配置和进度服务；前端不得用 `graph_version` 自行推导解锁状态。
2. 任务接口返回 QuestionPublic；题目管理接口按权限提供完整对象；反馈接口按上述权限返回答案解析。
3. 发布校验覆盖悬空前驱、先修环、非法章节、错误答案引用、重复选项、未知标签、未审核题加入正式预设集合。
4. 用两个账号验证状态隔离；用重复提交验证完成数不增加；答错仍增加有效完成数但不增加正确次数。
5. 验证无前驱、多个前驱、跨章节前驱、零题节点、题目换版，以及小测通过/失败的状态边界。
6. 解锁门槛已确认；小测通过规则和题库更新后的进度迁移政策仍需确认。固定 policy_version 并提供示例数据，不能由前端使用颜色反推业务状态。

相关资料：[当前后端接口](backend_api.md)、[ApiFox 需求稿](apifox_api_408.md)、[实现对照](apifox_api_408_implementation_check.md)。本文件对对象语义与字段映射的说明优先于早期需求稿中的示例；实际接口上线前仍以当前 OpenAPI 为准。

## 8. API 需求（ApiFox 格式）

本节为目标契约，新增路由不代表已经实现。不包含 OCR。所有路径均含 `/api/v1`。认证为 `Authorization: Bearer <access_token>`，请求和响应为 JSON；当前用户由登录态确定。成功直接返回下列业务对象，不增加 success/data 包装。错误沿用现有结构：`{"error":{"message":"错误说明","fields":[]}}`，fields 可省略。时间为 UTC ISO 8601。现有知识图、学习状态和任务响应继续按现有契约返回当前 `graph_version`；`GET /api/v1/subjects` 直接返回 `SubjectWithChapters[]`，不包装 `graph_version`。该字段仅表示课程图配置标识。

前端负责小测规则配置、统计展示、标签 ID 映射和完成动画；后端负责参数校验、用户状态读取、判分、状态计算及事件返回。题目本期统一使用 `plain_text`。前端上下文不得直接改变判分、完成度、掌握度或解锁结果。

### 8.1 获取全部知识结构

- **Method / Route**：`GET /api/v1/subjects`
- **功能**：返回四科列表，内部按章节包含全部已发布知识点；每层按 order、id 稳定排序，无用户进度数据。
- **鉴权**：已登录学生；无请求参数。
- **成功状态**：200。
- **返回类型**：`SubjectWithChapters[]`。科目包含 `chapters: ChapterWithKnowledge[]`，章节包含 `knowledge_points: KnowledgePoint[]`；对象字段沿用前文定义。

**Response Example**（演示一个科目，实际返回四科；空章节知识点数组为 []）：

```json
[
  {
    "id": "data-structures", "name": "数据结构", "description": "数据组织与算法", "order": 1, "status": "published",
    "chapters": [
      {
        "id": "ds-linear-lists", "subject_id": "data-structures", "name": "线性表", "description": "线性表及基本操作", "order": 2, "status": "published",
        "knowledge_points": [
          {
            "id": "ds-sequential-list", "name": "顺序表", "subject_id": "data-structures", "chapter_id": "ds-linear-lists",
            "description": "顺序表的存储与操作", "order": 2, "prerequisite_ids": [], "tag_ids": ["sequential-storage"],
            "preset_set": {"id": "preset-ds-sequential-list", "version": 1, "question_keys": ["ds-seq-q001:v1"], "question_count": 1},
            "status": "published", "updated_at": "2026-11-23T08:00:00Z"
          }
        ]
      }
    ]
  }
]
```

### 8.2 查询知识点全部预设题

- **Method / Route**：`GET /api/v1/knowledge-points/{knowledge_id}/questions`
- **功能**：按预设题集合顺序返回全部题目，不包含 AI 小测题。
- **鉴权**：学生；后端校验知识点已解锁。
- **Path Params**：knowledge_id，string，必填，知识点 ID。
- **成功状态**：200；返回 `QuestionPublic[]`，字段定义见第 5 节；无题返回 []。
- **错误**：404 知识点不存在或未发布；409 知识点未解锁。

**Response Example**：

```json
[
  {
    "question_id": "ds-seq-q001", "version": 1, "key": "ds-seq-q001:v1", "knowledge_id": "ds-sequential-list",
    "related_knowledge_ids": [], "type": "single_choice", "stem": "顺序表随机访问的时间复杂度是？", "content_format": "plain_text",
    "options": [{"id": "A", "text": "O(1)"}, {"id": "B", "text": "O(n)"}],
    "tag_ids": ["sequential-storage"], "bloom_level": "understand", "secondary_bloom_levels": [], "difficulty": "easy",
    "source": {"type": "authored", "title": "演示题", "year": null, "question_number": null, "url": null},
    "review_status": "published", "dataset": "demo-seed"
  }
]
```

不得返回答案或解析。查询不创建任务、不增加完成数；提交需按 8.9 获取任务上下文。

### 8.3 创建 AI 小测

- **Method / Route**：`POST /api/v1/knowledge-points/{knowledge_id}/ai-tests`
- **功能**：为当前用户生成一套新小测，试卷标记版本号并持久化。
- **Path Params**：knowledge_id，string，必填。
- **Body Params**：request_id，string，必填，客户端生成的唯一幂等 ID；rules，object，必填，由前端配置，字段见第 9 节。
- **前置条件**：知识点已解锁、预设题数量大于 0 且全部完成。已通过的小测重测本期不开放。
- **成功状态**：202（已接受异步生成），响应含 test_id，可通过 8.5 轮询。

**Request Example**：

```json
{"request_id":"create-test-unique-001","rules":{"question_count":5,"pass_score":0.8}}
```

**Response Example**：

```json
{
  "test_id": "test-001", "knowledge_id": "ds-sequential-list", "version": 1,
  "status": "generating", "created_at": "2026-11-23T09:00:00Z"
}
```

版本号在“用户＋知识点”范围内递增，test_id 全局唯一；数据库唯一约束保证并发不重复。题目生成成功后保存题目、选项、标准答案、解析及通过规则快照；后续查询不得重新生成。试卷版本与题目版本是不同概念。

同一 request_id 重试返回同一试卷，不重复生成；不同 request_id 但已有 generating/ready 试卷时返回 409，前端应继续原试卷。生成失败记录为 generation_failed，用户可用新 request_id 创建下一版本，不覆盖失败记录。

**错误**：404 知识点不存在；409 未解锁、预设题未完成、零题、已有进行中小测或已经通过；422 请求参数错误；503 生成服务未配置或暂不可用。

### 8.4 查询知识点的 AI 小测列表

- **Method / Route**：`GET /api/v1/knowledge-points/{knowledge_id}/ai-tests`
- **功能**：返回当前用户在该知识点的全部历史小测摘要，通过分页查询，不返回其他用户记录。
- **Path Params**：knowledge_id，string，必填。
- **Query Params**：limit，integer，可选，默认 20，范围 1–100；offset，integer，可选，默认 0，≥0。
- **成功状态**：200；按 version 降序排列。
- **错误**：404 知识点不存在。

**Response Example**：

```json
{
  "items": [
    {"test_id": "test-001", "knowledge_id": "ds-sequential-list", "version": 1, "status": "submitted", "score": 0.8, "passed": true, "created_at": "2026-11-23T09:00:00Z", "submitted_at": "2026-11-23T09:10:00Z"}
  ],
  "total": 1, "limit": 20, "offset": 0
}
```

`status`：generating/ready/generation_failed/submitted。score、passed、submitted_at 在尚未提交时为 null；score 范围 0–1。已提交是否通过由 passed 区分，不与生成失败混用。

### 8.5 查询 AI 小测详情

- **Method / Route**：`GET /api/v1/ai-tests/{test_id}`
- **功能**：查询生成状态、试卷题目和已提交结果；供生成轮询和刷新恢复使用。
- **Path Params**：test_id，string，必填。
- **鉴权**：仅试卷所属用户；他人试卷与不存在的试卷统一返回 404。
- **成功状态**：200。

**Response Example**（生成中）：

```json
{
  "test_id": "test-001", "knowledge_id": "ds-sequential-list", "version": 1, "status": "generating",
  "questions": [], "rules": null, "result": null, "error": null, "created_at": "2026-11-23T09:00:00Z"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| test_id / knowledge_id / version / status | 同列表 | 标识及状态 |
| questions | QuestionPublic[] | ready/submitted 时返回固定题目；生成中或失败为空数组 |
| rules | object或null | ready 后返回 question_count（正整数）、pass_score（0–1）；本期单选题等权计分 |
| result | object或null | 仅 submitted 时返回 8.6 的结果对象 |
| error | object或null | generation_failed 时包含 code、message；不得泄露内部服务密钥或原始错误栈 |
| created_at | datetime | 创建时间 |

题目来源标记 ai_generated；动态试卷题不自动进入公共题库。通过阈值与题数由前端配置并在创建请求中传入；后端校验范围、随试卷冻结并用于判分，提交时不可修改。具体约定见第 9 节。

### 8.6 提交 AI 小测

- **Method / Route**：`POST /api/v1/ai-tests/{test_id}/submit`
- **功能**：整卷提交、服务端判分、保存结果；通过后将知识点标记为 mastered。
- **Path Params**：test_id，string，必填。

| Body 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| submission_id | string | 是 | 幂等提交 ID |
| answers | object[] | 是 | 必须覆盖试卷全部题目，不得重复、缺漏或包含试卷外题目 |
| answers[].question_key | string | 是 | 试卷中的题目版本键 |
| answers[].selected_option_id | string | 是 | 该题有效选项 ID |

**Request Example**（一题试卷示例）：

```json
{"submission_id":"submit-test-unique-001","answers":[{"question_key":"ai-q001:v1","selected_option_id":"A"}]}
```

**Response Example**：

```json
{
  "test_id": "test-001", "status": "submitted", "score": 1, "passed": true,
  "knowledge_status": "mastered", "submitted_at": "2026-11-23T09:10:00Z", "replayed": false,
  "feedback": [
    {"question_key":"ai-q001:v1","selected_option_id":"A","correct":true,"answer":{"option_id":"A"},"explanation":"解析内容"}
  ]
}
```

成功状态 200。score=正确题数/总题数，passed 按该试卷保存的 pass_score 判定。未通过时 knowledge_status 仍为 completed。提交结果与知识点状态更新在同一事务内完成；AI 小测作答不计入预设题完成数。

同 submission_id、同答案重试返回原结果且 replayed=true；同 ID 不同内容返回 409。已提交试卷禁止修改或换 ID 再评分。生成未完成返回 409；试卷不可访问返回 404；无效或不完整答案返回 422。标准答案、解析及可展示 Prompt 仅在整卷提交后返回。

提交时可附带 `client_context`：`elapsed_seconds`、`used_hint`、`learning_goal`，全部可选，仅用于反馈。后端同时读取当前用户最近默认 5 条、硬上限 20 条有效提交，按时间倒序，仅取题目键、知识点、正确性、提示使用、耗时和时间等白名单字段；不允许跨用户访问。历史读取失败不得回滚本次判分。响应增加 `learning_feedback` 和 `events`；反馈先判分后生成，AI 失败时降级为规则文案；无新事件返回 `[]`，前端按 event_id 去重。

### 8.7 查询单个知识点状态

- **Method / Route**：`GET /api/v1/knowledge-points/{knowledge_id}/progress`
- **功能**：返回当前用户在该知识点的完成进度和交互状态。
- **Path Params**：knowledge_id，string，必填。
- **成功状态**：200；不存在返回 404。锁定节点也允许查询状态和原因。

**Response Example**：

```json
{
  "knowledge_id":"ds-sequential-list", "status":"available", "unlocked":true,
  "completed_count":1, "total_count":3, "unmet_prerequisite_ids":[],
  "ai_test_eligible":false, "passed_test_id":null
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| knowledge_id | string | 知识点 ID |
| status | enum | locked / available / completed / mastered |
| unlocked | boolean | 是否满足所有前驱；必须与 status 一致 |
| completed_count / total_count | integer | 已有效提交的不同预设题数/预设题总数；重复答题不增加分子 |
| unmet_prerequisite_ids | string[] | 未完成预设题的前驱；已解锁时为空 |
| ai_test_eligible | boolean | 已解锁、有预设题且全部完成、未通过 AI 小测时为 true；是否有进行中试卷仍由创建接口校验 |
| passed_test_id | string或null | 支撑 mastered 的通过记录，无记录为 null |

状态判定顺序：有未完成前驱 → locked；否则有通过小测记录 → mastered；否则 total_count>0 且 completed_count=total_count → completed；其余 → available。无前驱默认解锁，零题不算完成。未通过小测保持 completed。

此处 status 是供前端使用的四态摘要，第 3 节 mastery_status 为细粒度学习状态。转换：unlocked=false → locked；new/learning 且已解锁 → available；covered → completed；mastered → mastered。前端用 available 下的 completed_count 区分未学习和部分完成，不能把这两组枚举混用。

### 8.8 批量查询知识点状态

- **Method / Route**：`GET /api/v1/progress`
- **功能**：地图批量读取状态，避免每个节点分别请求。
- **Query Params**：subject_id，string，可选，限定一个科目；省略返回四科全部已发布知识点。
- **成功状态**：200，直接返回 `KnowledgeProgressSummary[]`；数组元素与 8.7 完全一致。
- **错误**：404 指定科目不存在。单点与批量接口必须使用同一计算逻辑。

**Response Example**：

```json
[
  {"knowledge_id":"ds-sequential-list","status":"completed","unlocked":true,"completed_count":3,"total_count":3,"unmet_prerequisite_ids":[],"ai_test_eligible":true,"passed_test_id":null}
]
```

### 8.9 预设题提交：复用现有任务接口

不重复新增独立 /attempts 路由，但必须补齐 8.2 查询后的作答上下文：

| Method / Route | 功能 | 参数及返回 |
|---|---|---|
| POST /api/v1/tasks | 创建或恢复知识点预设练习任务 | 请求 mode=practice、knowledge_id；返回 task_id（现有响应字段为 id）、question_keys 和公开题目 |
| POST /api/v1/tasks/{task_id}/attempts | 保存预设题作答并判分 | 采用第 5 节提交与反馈契约；旧 selected 文本字段通过兼容层转换 |

**必须扩展现有行为：**普通预设练习任务绑定该知识点固定预设集合，能覆盖 8.2 返回的全部题目，不得因旧推荐算法只取部分题而导致剩余题无法提交。创建请求为 `{"mode":"practice","knowledge_id":"..."}`；同一用户、知识点和预设集合重复进入时恢复有效任务，返回已有 attempts 并定位未答题，新建返回 201，恢复返回 200。创建与提交均校验用户和任务归属、题目成员关系及解锁条件。学生不可直接写 completed 或 mastered。

有效提交后更新知识点及其后继解锁结果；答错也计完成，正确率单独统计。前端提交成功后刷新 8.7/8.8。现有历史诊断的预设题有效作答可按 question_key 去重计入完成数，非预设题和 AI 小测题不计入。

### 8.10 公共错误码与验收

| HTTP 状态码 | 含义 |
|---|---|
| 401 | 登录失效 |
| 403 | 角色不允许访问 |
| 404 | 资源不存在、未发布或当前用户不可访问 |
| 409 | 解锁条件、小测资格、试卷状态或幂等请求内容冲突 |
| 422 | 请求参数或答案格式无效 |
| 503 | AI 生成服务不可用 |

核心验收：四科章节知识点结构完整；预设题与小测题隔离；所有前驱预设题完成即解锁；未完成禁止创建小测；试卷版本与内容持久化且查询不重新生成；账号隔离；重复请求不重复出卷或计分；小测通过变 mastered、失败保持 completed；单点和批量状态一致；学生提交前无法读取答案。


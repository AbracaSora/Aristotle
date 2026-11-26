# 408 学习系统 API 接口文档

> 历史 ApiFox 需求草案 v0.1。2026-11-23 后端按 [对象交接 v1.5](backend_handoff_objects_408.md) 实现，见 [实现对照](apifox_api_408_implementation_check.md)。本页的外层包装、单数 ai-test 路径和 OCR 范围已被新契约替代；联调请导入运行时 /openapi.json。

## 公共说明

- **Base URL**：`/api/v1`
- **Content-Type**：`application/json`
- **认证方式**：`Authorization: Bearer <access_token>`
- **时间格式**：ISO 8601 UTC，例如 `2026-11-23T08:30:00Z`

### 公共成功响应

```json
{
  "success": true,
  "data": {},
  "request_id": "req_xxx"
}
```

### 公共失败响应

```json
{
  "success": false,
  "error": {
    "code": "PROGRESS_NOT_READY",
    "message": "完成预设题目后才能开始 AI 小测",
    "details": {}
  },
  "request_id": "req_xxx"
}
```

---

# 一、地图与知识结构

## 1. 获取四科和章节

- **Method**：`GET`
- **Path**：`/subjects`
- **鉴权**：需要登录
- **功能**：获取四个 408 科目、章节及章节顺序。

### Response Data

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `version` | string | 是 | 地图数据版本 |
| `subjects` | array | 是 | 科目列表 |
| `subjects[].id` | string | 是 | 科目 ID |
| `subjects[].name` | string | 是 | 科目名称 |
| `subjects[].chapters` | array | 是 | 章节列表 |
| `subjects[].chapters[].id` | string | 是 | 章节 ID |
| `subjects[].chapters[].name` | string | 是 | 章节名称 |
| `subjects[].chapters[].order` | integer | 是 | 章节顺序 |

### Response Example

```json
{
  "success": true,
  "data": {
    "version": "408-resource-v1",
    "subjects": [
      {
        "id": "data-structures",
        "name": "数据结构",
        "chapters": [
          {"id": "ds-linear", "name": "线性表", "order": 1}
        ]
      }
    ]
  },
  "request_id": "req_001"
}
```

## 2. 获取科目知识地图

- **Method**：`GET`
- **Path**：`/subjects/{subject_id}/graph`
- **鉴权**：需要登录
- **功能**：获取知识点、章节归属、题目数量及前后驱关系。

### Path Params

| 参数 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `subject_id` | string | 是 | 科目 ID |

### Response Data

| 字段 | 类型 | 说明 |
|---|---|---|
| `subject_id` | string | 科目 ID |
| `version` | string | 图数据版本 |
| `nodes` | array | 知识点节点 |
| `nodes[].id` | string | 知识点 ID |
| `nodes[].chapter_id` | string | 所属章节 ID |
| `nodes[].name` | string | 知识点名称 |
| `nodes[].description` | string | 知识点描述 |
| `nodes[].question_count` | integer | 预设题数量 |
| `nodes[].mastery_status` | string | `new`/`learning`/`covered`/`mastered` |
| `nodes[].mastery_score` | number | 掌握度，0–1 |
| `edges` | array | 前后驱关系 |
| `edges[].from` | string | 前置节点 ID |
| `edges[].to` | string | 后置节点 ID |
| `edges[].type` | string | 固定为 `prerequisite` |

---

# 二、题目管理

## 3. 获取知识点预设题

- **Method**：`GET`
- **Path**：`/knowledge-points/{knowledge_point_id}/questions`
- **鉴权**：需要登录
- **功能**：获取答题页面使用的预设题。学生端不返回答案字段。

### Path Params

| 参数 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `knowledge_point_id` | string | 是 | 知识点 ID |

### Response Example

```json
{
  "success": true,
  "data": {
    "knowledge_point_id": "ds-linear",
    "questions": [
      {
        "id": "q_001",
        "type": "single_choice",
        "stem": "线性结构中元素之间的基本关系是？",
        "options": [
          {"key": "A", "text": "一对一"},
          {"key": "B", "text": "一对多"}
        ],
        "label": ["线性表", "基础概念"],
        "source_type": "真题",
        "review_status": "published"
      }
    ]
  },
  "request_id": "req_002"
}
```

## 4. 导入结构化题目

- **Method**：`POST`
- **Path**：`/questions/import`
- **鉴权**：维护者或导入服务
- **功能**：导入人工录入或 OCR/AI 整理后的题目，默认进入待审核状态。

### Body Params

| 参数 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `source` | string | 是 | `manual`/`ocr`/`ai` |
| `knowledge_point_id` | string | 是 | 知识点 ID |
| `questions` | array | 是 | 题目列表 |
| `questions[].type` | string | 是 | 题型 |
| `questions[].stem` | string | 是 | 题干 |
| `questions[].options` | array | 否 | 选项 |
| `questions[].answer` | string | 是 | 标准答案 |
| `questions[].explanation` | string | 否 | 解析 |
| `questions[].label` | string[] | 是 | 标签 |

### Response Example

```json
{
  "success": true,
  "data": {
    "import_id": "imp_001",
    "status": "pending_review",
    "created_count": 8,
    "warnings": []
  },
  "request_id": "req_003"
}
```

---

# 三、答题与进度

## 5. 提交答题记录

- **Method**：`POST`
- **Path**：`/attempts`
- **鉴权**：学生
- **功能**：判分、保存作答记录并更新知识点掌握度。

### Body Params

| 参数 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `question_id` | string | 是 | 题目 ID |
| `selected_answer` | string/string[] | 是 | 用户答案 |
| `client_submission_id` | string | 是 | 幂等请求 ID |

### Response Example

```json
{
  "success": true,
  "data": {
    "attempt_id": "att_001",
    "question_id": "q_001",
    "is_correct": true,
    "correct_answer": "A",
    "explanation": "解析内容",
    "knowledge_point_id": "ds-linear",
    "mastery": {
      "status": "learning",
      "completed": 2,
      "total": 5,
      "score": 0.4
    }
  },
  "request_id": "req_004"
}
```

## 6. 获取当前用户学习进度

- **Method**：`GET`
- **Path**：`/users/me/progress`
- **鉴权**：学生
- **功能**：返回地图和学习中心共用的统一进度。

### Response Data

```json
{
  "success": true,
  "data": {
    "subjects": [
      {
        "subject_id": "data-structures",
        "completed": 12,
        "total": 30,
        "mastery_status": "learning"
      }
    ],
    "knowledge_points": [
      {
        "id": "ds-linear",
        "completed": 5,
        "total": 5,
        "mastery_status": "covered",
        "ai_test_passed": false
      }
    ]
  },
  "request_id": "req_005"
}
```

### 掌握度枚举

| 值 | 含义 | 地图颜色 |
|---|---|---|
| `new` | 未开始 | 灰/白 |
| `learning` | 部分完成 | 蓝 |
| `covered` | 预设题全部完成 | 绿 |
| `mastered` | AI 小测通过 | 紫 |

---

# 四、AI 小测

## 7. 生成知识点 AI 小测

- **Method**：`POST`
- **Path**：`/knowledge-points/{knowledge_point_id}/ai-test`
- **鉴权**：学生
- **功能**：动态生成最终掌握度测试。
- **前置条件**：知识点状态必须为 `covered`。

### Path Params

| 参数 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `knowledge_point_id` | string | 是 | 知识点 ID |

### Response Example

```json
{
  "success": true,
  "data": {
    "test_id": "ait_001",
    "knowledge_point_id": "ds-linear",
    "status": "ready",
    "questions": [
      {
        "id": "aiq_001",
        "type": "single_choice",
        "stem": "动态生成的变式题",
        "options": [{"key": "A", "text": "选项"}]
      }
    ]
  },
  "request_id": "req_006"
}
```

## 8. 提交 AI 小测

- **Method**：`POST`
- **Path**：`/ai-tests/{test_id}/submit`
- **鉴权**：学生
- **功能**：判定 AI 小测是否通过，并更新紫色掌握状态。

### Body Example

```json
{
  "answers": [
    {"question_id": "aiq_001", "selected_answer": "A"}
  ]
}
```

### Response Example

```json
{
  "success": true,
  "data": {
    "test_id": "ait_001",
    "passed": true,
    "score": 0.8,
    "mastery": {
      "status": "mastered",
      "knowledge_point_id": "ds-linear"
    }
  },
  "request_id": "req_007"
}
```

---

# 五、学习记录与统计

## 9. 获取学习记录

- **Method**：`GET`
- **Path**：`/users/me/learning-records`
- **鉴权**：学生
- **功能**：提供学习中心使用的错题、正确率和 Bloom 统计。

### Response Example

```json
{
  "success": true,
  "data": {
    "accuracy": {
      "overall": 0.76,
      "by_subject": {
        "data-structures": 0.82,
        "computer-organization": 0.71
      }
    },
    "wrong_knowledge_points": [
      {"id": "ds-stack", "name": "栈", "wrong_count": 3}
    ],
    "recent_attempts": [],
    "bloom_distribution": {
      "remember": 0.8,
      "understand": 0.6,
      "apply": 0.4,
      "analyze": 0.3,
      "evaluate": 0.2,
      "create": 0.1
    }
  },
  "request_id": "req_008"
}
```

---

# 六、OCR 教辅

## 10. 上传 PDF 并启动 OCR

- **Method**：`POST`
- **Path**：`/material-imports/pdf`
- **鉴权**：学生
- **Content-Type**：`multipart/form-data`
- **功能**：上传 2–3 页短篇 PDF，启动 OCR 和 AI 题目结构化。

### Form Data

| 参数 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `file` | file | 是 | PDF 文件 |
| `subject_id` | string | 是 | 科目 ID |
| `chapter_id` | string | 否 | 章节 ID |

### Response Example

```json
{
  "success": true,
  "data": {
    "job_id": "ocr_001",
    "status": "processing",
    "page_count": 3
  },
  "request_id": "req_009"
}
```

## 11. 查询 OCR 任务

- **Method**：`GET`
- **Path**：`/material-imports/{job_id}`
- **鉴权**：学生
- **功能**：查询 OCR 进度、结构化题目和警告。

### Response Example

```json
{
  "success": true,
  "data": {
    "job_id": "ocr_001",
    "status": "ready_for_review",
    "progress": 100,
    "questions": [],
    "warnings": []
  },
  "request_id": "req_010"
}
```

## 12. 确认 OCR 结果并导入

- **Method**：`POST`
- **Path**：`/material-imports/{job_id}/confirm`
- **鉴权**：学生
- **功能**：确认 OCR 结果后正式导入题库。

### Response Example

```json
{
  "success": true,
  "data": {
    "job_id": "ocr_001",
    "status": "imported",
    "import_id": "imp_002",
    "created_count": 8
  },
  "request_id": "req_011"
}
```

---

# 七、错误码

| HTTP 状态码 | 错误码 | 说明 |
|---:|---|---|
| 400 | `INVALID_PARAM` | 参数格式错误 |
| 401 | `UNAUTHORIZED` | 未登录或令牌失效 |
| 403 | `FORBIDDEN` | 无权限 |
| 404 | `NOT_FOUND` | 资源不存在 |
| 409 | `DUPLICATE_SUBMISSION` | 重复提交 |
| 409 | `INVALID_STATE` | 当前状态不允许该操作 |
| 422 | `PROGRESS_NOT_READY` | 未完成预设题，不能开始 AI 小测 |
| 422 | `FILE_LIMIT_EXCEEDED` | PDF 页数、大小或格式不符合要求 |
| 500 | `INTERNAL_ERROR` | 服务端错误 |
| 501 | `NOT_IMPLEMENTED` | 功能尚未实现，仅允许开发环境使用 |

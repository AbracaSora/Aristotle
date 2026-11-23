# 408 学习系统 API 需求文档

版本：v0.1  
基础路径：`/api/v1`  
数据格式：JSON  
认证：`Authorization: Bearer <access_token>`

## 1. 统一返回格式

成功：

```json
{
  "success": true,
  "data": {},
  "request_id": "req_xxx"
}
```

失败：

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

时间统一使用 ISO 8601 UTC 字符串，例如 `2026-11-23T08:30:00Z`。

## 2. 地图与知识结构

### GET /subjects

**功能**：获取 408 四科及章节列表，用于学习地图标签和章节区域。

**返回格式**：

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
  }
}
```

### GET /subjects/{subject_id}/graph

**功能**：返回科目知识点、章节归属及前后驱关系。地图布局由前端完成。

**返回格式**：

```json
{
  "success": true,
  "data": {
    "subject_id": "data-structures",
    "version": "408-resource-v1",
    "nodes": [
      {
        "id": "ds-linear",
        "chapter_id": "ds-linear",
        "name": "线性表",
        "description": "线性结构基础",
        "question_count": 5,
        "mastery_status": "learning",
        "mastery_score": 0.4
      }
    ],
    "edges": [
      {"from": "ds-linear", "to": "ds-stack", "type": "prerequisite"}
    ]
  }
}
```

`mastery_status` 取值：`new`、`learning`、`covered`、`mastered`，分别对应灰/蓝/绿/紫。

## 3. 题目

### GET /knowledge-points/{knowledge_point_id}/questions

**功能**：获取知识点的预设题目。学生端不得返回答案。

**返回格式**：

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
  }
}
```

### POST /questions/import

**功能**：维护者或 OCR 流程导入结构化题目。

**请求格式**：

```json
{
  "source": "ocr",
  "knowledge_point_id": "ds-linear",
  "questions": [
    {
      "type": "single_choice",
      "stem": "题干",
      "options": [{"key": "A", "text": "选项"}],
      "answer": "A",
      "explanation": "解析",
      "label": ["线性表"]
    }
  ]
}
```

**返回格式**：

```json
{
  "success": true,
  "data": {
    "import_id": "imp_001",
    "status": "pending_review",
    "created_count": 1,
    "warnings": []
  }
}
```

## 4. 答题与学习进度

### POST /attempts

**功能**：提交一次答题，判分并保存学习记录。

**请求格式**：

```json
{
  "question_id": "q_001",
  "selected_answer": "A",
  "client_submission_id": "uuid"
}
```

**返回格式**：

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
  }
}
```

### GET /users/me/progress

**功能**：获取当前用户在四科、章节和知识点上的统一进度。

**返回格式**：

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
  }
}
```

## 5. AI 小测

### POST /knowledge-points/{knowledge_point_id}/ai-test

**功能**：完成全部预设题后，动态生成最终掌握度小测。

**前置条件**：知识点必须为 `covered`，否则返回 `PROGRESS_NOT_READY`。

**返回格式**：

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
  }
}
```

### POST /ai-tests/{test_id}/submit

**功能**：提交 AI 小测并判定是否通过。

**返回格式**：

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
  }
}
```

## 6. 学习记录与统计

### GET /users/me/learning-records

**功能**：获取错题、知识点掌握情况和作答历史。

**返回格式**：

```json
{
  "success": true,
  "data": {
    "accuracy": {"overall": 0.76, "by_subject": {}},
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
  }
}
```

## 7. OCR 教辅

### POST /material-imports/pdf

**功能**：上传 2–3 页短 PDF，启动 OCR 和题目结构化任务。

**限制**：超过页数、文件大小或清晰度要求时拒绝。

**返回格式**：

```json
{
  "success": true,
  "data": {
    "job_id": "ocr_001",
    "status": "processing",
    "page_count": 3
  }
}
```

### GET /material-imports/{job_id}

**功能**：查询 OCR 处理状态和结构化结果。

**返回格式**：

```json
{
  "success": true,
  "data": {
    "job_id": "ocr_001",
    "status": "ready_for_review",
    "questions": [],
    "warnings": []
  }
}
```

### POST /material-imports/{job_id}/confirm

**功能**：用户确认 OCR 结果后，正式导入题库。

**返回格式**：

```json
{
  "success": true,
  "data": {
    "job_id": "ocr_001",
    "status": "imported",
    "import_id": "imp_002",
    "created_count": 8
  }
}
```

## 8. 状态码要求

- `200` 查询或处理成功
- `201` 创建成功
- `400` 参数错误
- `401` 未登录或令牌失效
- `403` 无权限
- `404` 资源不存在
- `409` 重复提交或状态冲突
- `422` 业务校验失败
- `500` 服务端错误
- `501` 功能尚未实现，仅允许在开发环境返回

## 9. 后端实现顺序

1. `/subjects`、`/subjects/{id}/graph`
2. `/knowledge-points/{id}/questions`
3. `/attempts`、`/users/me/progress`
4. `/ai-tests`
5. `/users/me/learning-records`
6. `/material-imports`

前端应以本文件中的字段名为联调契约，地图、学习中心和答题页不得各自维护掌握度判定逻辑。


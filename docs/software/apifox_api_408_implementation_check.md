# 408 API：ApiFox 需求与当前实现对照

> 对照日期：2026-11-23  
> 结论：当前后端仍以既有“学习流程/任务”API 为主，上一版 ApiFox 文档中的新接口大部分尚未注册。

## 一、当前已实现接口

| Method | Route | 当前功能 | 对应需求 | 状态 |
|---|---|---|---|---|
| POST | `/api/v1/auth/login` | 登录并返回令牌 | 公共认证 | 已实现 |
| GET | `/api/v1/auth/me` | 获取当前用户 | 公共认证 | 已实现 |
| POST | `/api/v1/auth/logout` | 登出 | 公共认证 | 已实现 |
| GET | `/api/v1/knowledge` | 获取当前知识图谱 | 地图知识结构 | 部分实现 |
| GET | `/api/v1/curriculum-progress` | 获取课程进度 | 学习进度 | 部分实现 |
| GET | `/api/v1/learning-state` | 获取学习状态摘要 | 学习进度 | 部分实现 |
| POST | `/api/v1/tasks` | 创建诊断/练习任务 | 答题流程 | 已实现 |
| GET | `/api/v1/tasks/{task_id}` | 获取任务、题目和作答状态 | 答题流程 | 已实现 |
| POST | `/api/v1/tasks/{task_id}/attempts` | 提交任务题目答案 | 答题记录 | 已实现 |
| GET | `/api/v1/history` | 获取历史作答记录 | 学习记录 | 已实现 |
| GET | `/api/v1/materials` | 获取个人资料 | 教辅资料 | 已实现 |
| POST | `/api/v1/materials` | 创建文字资料 | 教辅资料 | 已实现 |
| PATCH | `/api/v1/materials/{material_id}` | 更新资料确认状态 | 教辅资料 | 已实现 |
| DELETE | `/api/v1/materials/{material_id}` | 删除资料 | 教辅资料 | 已实现 |
| POST | `/api/v1/material-imports` | 创建资料处理任务 | 教辅资料 | 已实现 |
| GET | `/api/v1/jobs/{job_id}` | 查询后台任务 | OCR/模型任务 | 已实现 |
| POST | `/api/v1/jobs/{job_id}/run` | 执行后台任务 | OCR/模型任务 | 已实现 |
| POST | `/api/v1/jobs/{job_id}/retry` | 重试后台任务 | OCR/模型任务 | 已实现 |
| GET | `/api/v1/knowledge-map` | 获取知识地图 | 地图 | 已实现 |
| POST | `/api/v1/retrieval/search` | 检索资料 | 辅助资料 | 已实现 |
| POST | `/api/v1/explanations` | 创建解释任务 | AI 辅助 | 已实现 |
| POST | `/api/v1/admin/graphs` | 发布知识图谱 | 地图维护 | 已实现 |
| GET | `/api/v1/admin/questions` | 查询全部题目 | 题目管理 | 已实现 |
| POST | `/api/v1/admin/questions` | 创建题目 | 题目导入 | 已实现 |
| POST | `/api/v1/admin/questions/{question_key}/candidates` | 创建题目候选 | 题目审核 | 已实现 |
| POST | `/api/v1/admin/candidates/{candidate_id}/review` | 审核候选题 | 题目审核 | 已实现 |
| POST | `/api/v1/admin/questions/{question_key}/annotation-jobs` | 创建题目标注任务 | Label 补全 | 已实现 |

## 二、ApiFox 需求中尚未实现或路径不一致的接口

| 需求接口 | 当前情况 | 建议 |
|---|---|---|
| `GET /subjects` | 未注册 | 新增四科和章节聚合接口，或由 `/knowledge-map` 扩展返回 |
| `GET /subjects/{subject_id}/graph` | 未注册 | 复用 `/knowledge-map` 的图结构，增加 `subject_id`、章节和前后驱字段 |
| `GET /knowledge-points/{id}/questions` | 未注册 | 从 `/tasks` 的题目选择逻辑中抽出只读接口 |
| `POST /questions/import` | 未注册 | 复用 `/admin/questions`，增加批量导入参数和导入批次 |
| `POST /attempts` | 未注册 | 当前实际路径为 `/tasks/{task_id}/attempts`，建议先保持现状，避免重复记录 |
| `GET /users/me/progress` | 未注册 | 当前有 `/curriculum-progress` 和 `/learning-state`，建议统一为一个聚合接口 |
| `POST /knowledge-points/{id}/ai-test` | 未注册 | 当前没有绿色状态门禁和动态最终小测接口 |
| `POST /ai-tests/{test_id}/submit` | 未注册 | 当前没有 AI 小测提交和紫色掌握度写入 |
| `GET /users/me/learning-records` | 未注册 | 当前 `/history` 只有历史记录，缺少错题、科目正确率和 Bloom 统计 |
| `POST /material-imports/pdf` | 已注册但返回 501 | 目前是预留接口，不是可用 OCR 流程 |
| `GET /material-imports/{job_id}` | 未注册 | 当前通过 `/jobs/{job_id}` 查询通用任务 |
| `POST /material-imports/{job_id}/confirm` | 未注册 | 当前没有 OCR 结果确认后导入接口 |

## 三、当前返回格式与 ApiFox 文档的差异

上一版 ApiFox 文档约定了统一外层结构：

```json
{"success": true, "data": {}, "request_id": "req_xxx"}
```

当前实际接口并不完全使用该包装格式，主要是 FastAPI response model 或直接返回业务对象。例如任务接口直接返回任务字段，错误通常由 HTTP 状态码和 FastAPI 错误体表达。因此联调前需要二选一：

1. **兼容现有实现**：ApiFox 文档按当前真实 response model 编写；
2. **统一新规范**：新增响应包装层，并同步修改现有接口和前端请求处理。

建议第一阶段兼容现有实现，避免一次性改动登录、任务和学习中心；新接口再统一使用 `success/data/request_id`。

## 四、当前后端实现的关键缺口

1. 没有以知识点为粒度的预设题查询接口。
2. 答题记录绑定任务，尚未提供地图节点直接提交的接口。
3. 地图掌握度尚未统一由后端计算，前端演示仍使用本地进度。
4. 尚未实现 `covered -> mastered` 的 AI 小测状态机。
5. 学习记录没有科目正确率、错题知识点、Bloom 六层统计。
6. PDF OCR 路由虽然存在，但当前明确返回 501。
7. OCR 任务没有“待确认后正式导入”的闭环。
8. Label 标注有后台任务接口，但缺少面向前端的批量导入和审核结果接口。

## 五、推荐联调顺序

### 第一阶段：直接复用现有接口

- `/auth/login`
- `/knowledge-map`
- `/tasks`
- `/tasks/{task_id}`
- `/tasks/{task_id}/attempts`
- `/history`
- `/curriculum-progress`

### 第二阶段：补齐核心学习闭环

- `/subjects`
- `/subjects/{subject_id}/graph`
- `/knowledge-points/{id}/questions`
- `/users/me/progress`
- `/knowledge-points/{id}/ai-test`
- `/ai-tests/{test_id}/submit`

### 第三阶段：补齐统计和 OCR

- `/users/me/learning-records`
- 可用的 `/material-imports/pdf`
- `/material-imports/{job_id}/confirm`

## 六、判断标准

后端完成以下条件后，才算满足会议纪要的核心闭环：

- 地图和学习中心读取同一个用户进度接口；
- 完成全部预设题后才返回 `covered`；
- AI 小测通过后才返回 `mastered`；
- `mastered` 状态能被地图和学习中心同时显示为紫色；
- 答题记录、错题统计和科目正确率可被查询；
- OCR 结果经过确认后才能进入正式题库。

# 后端重构前后对照

两个采样点采用同一份护栏阈值。表内为函数自身度量，提取出的函数也参加本轮全量扫描。

| 函数 | 形参 | 有效行 | 圈复杂度 | 审阅要点 |
|---|---:|---:|---:|---|
| `providers.generate` | 9 → 4 | 29 → 18 | 1 → 1 | 模型用途、提示、输入和预算放进一次生成请求；保留响应解码和来源校验 |
| `policy.recommend` | 6 → 4 | 23 → 24 | 8 → 8 | 调用者明确提供同一轮的知识图、状态与作答 |
| `workflow.create_recommendation` | 9 → 4 | 30 → 34 | 8 → 8 | 使用同一份学习快照，目标知识点、层次和排除题仍独立指定 |
| `final_papers.create_test` | 5 → 3 | 38 → 39 | 4 → 4 | 用户、会话和时间由服务端捆绑传递；题数与知识点仍由请求校验 |
| `model_jobs.run_job` | 3 → 3 | 71 → 36 | 21 → 8 | 分别领取、执行、确认任务所有权，失去所有权时回滚标注 |
| `material_routes.run_job` | 4 → 4 | 81 → 23 | 12 → 7 | 分开处理任务领取、模拟失败、候选保存和审计 |

## 模型任务中断

重构前，标注 worker 重新读到任务状态后，仅在自己持有任务时填写结果，但两条路径都会提交数据库事务。若超时回收发生在模型返回前，候选标注和题目的待审状态仍可能提交。

```python
if current.status == "running" and current.result.get("run_id") == run_id:
    current.status = "succeeded"
    current.result = {"implementation": "openai-compatible", **result}
db.commit()
```

本次将提交放回所有权分支。回归在模型响应函数中触发超时回收，再返回有效候选，核对任务保持中断、题目保持草稿且候选数为零。

```python
if current.status == "running" and current.result.get("run_id") == run_id:
    current.status = "succeeded"
    current.result = {"implementation": "openai-compatible", **result}
    db.commit()
else:
    db.rollback()
```

同一条回归在原始提交 `c0d8539` 实跑时失败，题目的实际状态为 `pending_review`。本轮重跑通过。[原始提交失败输出](claim-before.txt) · [当前通过输出](claim-after.txt)

## 外部契约

测试把应用实际返回的整份 OpenAPI 与仓库保存的契约作结构化全等比较。PostgreSQL 的三个 Alembic 修订在重构前后分别生成从起点到 head 的升级 SQL 及从 head 回到起点的降级 SQL，两个方向的字节数和 SHA-256 均相同。课程先修和掌握规则另由数据库用例及浏览器场景验证。[DDL 摘要](ddl-digests.json) · [浏览器结果](browser.txt)

[重构前扫描](../final_paper/guardrails.json) · [重构后扫描](guardrails.json) · [含源码摘要的工具记录](source_manifest.json)

## 邻近模块的分支覆盖

同一轮全量测试还记录了下表。当前护栏配置逐文件设门槛的七个模块另见护栏 JSON 中的 `core_branches`。

| 模块 | 已覆盖分支／总分支 | 比例 |
|---|---:|---:|
| `diagnostic.py` | 14/14 | 100.00% |
| `workflow.py` | 44/54 | 81.48% |
| `task_sources.py` | 8/10 | 80.00% |
| `source_units.py` | 17/20 | 85.00% |
| `retrieval.py` | 32/40 | 80.00% |
| `learning_routes.py` | 33/44 | 75.00% |
| `task_routes.py` | 28/42 | 66.67% |
| `model_jobs.py` | 45/70 | 64.29% |

# 资料检索、诊断与旧库导入的重构对比

2026-11-26。以下指标取自同一份仓库护栏配置。有效行数排除注释、空行及嵌套函数体。圈复杂度按函数分别测量，拆出的函数也列入全仓扫描。两列依次为上一轮 mastery-v2 与本轮工作区。[上轮扫描](../mastery_v2/guardrails.json) · [本轮扫描](guardrails.json)

| 后端入口 | 有效行 | 圈复杂度 | 实际改变 |
|---|---:|---:|---|
| `source_units` | 80 → 3 | 16 → 3 | 分离公共来源、本人资料和保留页码的切片。带段落的私有资料一次关联查询，只读取已确认段落 |
| `index_sources` | 67 → 31 | 18 → 9 | 查缓存只取键和指纹，索引任务逐批选择、每次发出前检查、取得响应后核对并保存 |
| `create_diagnostic` | 66 → 33 | 21 → 10 | 题库按稳定顺序分组一次，轮次保存固定蓝图。该入口仍有 8 个形参，超出 4 个的门槛 |
| `diagnose` | 48 → 19 | 22 → 5 | 分开提取 14 天窗口内不同题目的证据、计算维度正确率与按图顺序判断状态 |
| `import_snapshot` | 68 → 14 | 24 → 1 | 分开检查源库、锁定空目标、分批复制和核验。一批最多复制 500 行；按主键匹配内容，源库与目标库可使用不同的字符串排序规则 |

### 私人讲义在两批之间撤回

修改前的 `index_sources` 在分批循环里直接使用任务开始时的片段，再在响应返回后检查能否保存向量。以下是基础提交 `c0d8539` 中连续的两行。

```python
batch = pending[start : start + 8]
vectors, metadata = embed(db, user_id, [u.text for u in batch], transport)
```

现在组装每批前读取最新可发送来源。索引把同一批来源的复核函数传入模型适配器，解释任务传入用户选中的来源。每次网络尝试均先执行复核，授权或内容已变化会终止该次发送。

```python
current = scope.authorized()
batch = [u for u in pending[start : start + 8] if unchanged(u, current)]
```

```python
for attempt in range(cfg.retries + 1):
    if request.validate_sources:
        request.validate_sources()
```

测试通过学生接口撤回授权，记录模拟供应商收到的请求，并查验模型调用记录和索引。下一批索引、索引失败重试、解释失败重试这三例，修改前各收到两次请求，修改后各收到一次。测试未向外部模型发送材料。[失败与通过记录](consent-regression.txt) · [实际用例](../../../../tests/integration/test_model_assistance.py)

### 学习规则的两个时间口径

诊断以 14 天窗口内同一题的首次有效作答计一次独立证据。课程解锁看每个直接前驱当前非空预设集合，每道题取最近一次有效提交，必须做完且正确率至少 2/3。前者用于描述认知状态，后者允许学生通过订正解锁后继。只有当前版本的最终小测通过才标记 mastered。[诊断实现](../../../../code/core_engine/aristotle_core/policy.py) · [课程进度回归](../../../../tests/integration/test_curriculum_contract.py)

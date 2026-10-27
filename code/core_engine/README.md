# 学习规则引擎

`aristotle_core.policy` 是无 HTTP、数据库和模型依赖的规则模块：

- `validate_graph(nodes)`：先修引用、重复节点和环路校验，返回拓扑顺序。
- `diagnose(nodes, attempts, now)`：14 天首次题目证据、先修约束与认知维度摘要。
- `recommend(...)`：已审核题目候选的目标和排序选择，保留标签并显式报告库存不足。

输入的有效题目与作答集合由服务层授权、版本检查后提供。所有时间为 UTC Unix 秒。
见 [规则说明](../../docs/algorithm/baseline.md) 和 `tests/unit/test_policy.py`。

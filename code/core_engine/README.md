# 学习规则引擎

`aristotle_core.policy` 是无 HTTP、数据库和模型依赖的规则模块：

- `validate_graph(nodes)`：先修引用、重复节点和环路校验，返回拓扑顺序。
- `diagnose(nodes, attempts, now)`：14 天首次题目证据、先修约束与认知维度摘要。
- `recommend(RecommendationEvidence(nodes, states, attempts), questions, knowledge_id=None, level=None)` 用同一轮的知识图、状态和作答记录选择目标，再对已审核的候选题排序。指定标签的题目不足时，返回对应提示。

输入的有效题目与作答集合由服务层授权、版本检查后提供。所有时间为 UTC Unix 秒。
见 [规则说明](../../docs/algorithm/baseline.md) 和 `tests/unit/test_policy.py`。

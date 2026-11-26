"""Versioned annotation contract, based on functional_spec FR-3 (not difficulty)."""

RULE_VERSION = "bloom-required-process-1"
RULES = {
    "remember": "从长期记忆提取、识别或复述事实、术语和定义。",
    "understand": "解释、举例、分类、概括、推断或比较概念含义。",
    "apply": "在给定情境执行已知步骤或使用方法求解。",
    "analyze": "分解信息，辨别组成部分、结构及相互关系。",
    "evaluate": "依据明确标准检查、批判或判断方案是否成立。",
    "create": "整合要素，产生新的方案、模型或作品。",
    "decision": "以正确完成本题实际必需的认知活动为主标签，不能仅凭动词、题型或难度判定。"
    "仅在存在另一项实质性必要活动时添加不同的次标签。"
    "存在多种解法、上下文不足或层级边界不清时写出歧义并降低置信度。"
    "标签是内容属性，不是学生能力评价；模型只提出候选，必须人工审核。",
}

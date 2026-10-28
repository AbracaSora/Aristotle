"""Explicit, additive mock fixtures for the original learning-flow design."""

import os
import time
from uuid import uuid4

from .db import Annotation, Audit, LearningResource, LearningScope, Question, Review, User
from .security import hash_password


def seed_design_flow(sessions):
    with sessions() as db:
        if not db.get(User, "editor") or not db.get(Question, "c1:v1"):
            raise ValueError("请先初始化基础演示数据")
        if not db.get(User, "admin"):
            db.add(
                User(
                    id="admin",
                    username="admin",
                    role="admin",
                    password_hash=hash_password(os.getenv("ARISTOTLE_DEMO_PASSWORD", "demo-password")),
                )
            )
        scopes = [
            ("foundations", "线性结构基础", ["linear"], True, "小范围体验：诊断、资料、任务与反馈"),
            (
                "stack",
                "栈：从理解到应用",
                ["linear", "stack"],
                True,
                "包含必要先修，分别检验理解与应用；支持回退与复测",
            ),
            (
                "stack-analysis",
                "栈操作与分析",
                ["linear", "stack", "stack_ops"],
                True,
                "扩展到操作与分析题，题库仍为演示样例",
            ),
            ("os-planned", "操作系统（尚未开放）", [], False, "知识图与审核题库尚未准备，不会伪造诊断"),
        ]
        for key, title, ids, published, description in scopes:
            if not db.get(LearningScope, key):
                db.add(
                    LearningScope(
                        id=key, title=title, knowledge_ids=ids, published=published, description=description
                    )
                )
        resources = [
            (
                "lesson-linear",
                "linear",
                "回看：线性结构的一对一关系",
                "线性结构按先后次序组织元素。首元素没有直接前驱，末元素没有直接后继；中间元素各有一个直接前驱和直接后继。顺序存储用连续空间表示逻辑相邻关系，但线性结构也可以用链式存储。",
            ),
            (
                "lesson-stack",
                "stack",
                "回看：先理解栈，再推演操作",
                "栈只在栈顶进行入栈和出栈，遵循后进先出。把每一步的栈内容按栈底到栈顶写下来：push(A) → [A]；push(B) → [A,B]；pop() → [A]。要区分‘弹出的元素’与‘弹出后的栈顶’，它们不是同一个问题。阅读后应使用不同题目检查，而非直接增加掌握分数。",
            ),
            (
                "lesson-stack-ops",
                "stack_ops",
                "回看：栈顶状态与更新顺序",
                "先明确 top 的含义：若 top 为栈顶下标、空栈为 -1，push 应先递增 top 再写入；pop 应先读取当前栈顶值，再递减 top。分析错误程序时，把空栈和单元素栈代入，核对每步下标和元素关系。",
            ),
        ]
        for key, kid, title, text in resources:
            if not db.get(LearningResource, key):
                db.add(
                    LearningResource(
                        id=key,
                        knowledge_id=kid,
                        title=title,
                        text=text,
                        source="公共演示讲义 · 团队自编样例，非正式审核内容",
                    )
                )
        extra = [
            (
                "wf_stack_a1",
                "空栈执行 push(2)、push(5)、pop()、push(7)，栈顶是？",
                ["2", "5", "7"],
                "7",
                "5 出栈后，7 入栈成为栈顶。",
            ),
            (
                "wf_stack_a2",
                "A、B、C 依次入栈，再出栈两次，剩余元素是？",
                ["A", "B", "C"],
                "A",
                "C 和 B 先后出栈，只剩 A。",
            ),
            (
                "wf_stack_a3",
                "空栈执行 push(1)、pop()、push(4)、push(6)、pop()，剩余元素是？",
                ["1", "4", "6"],
                "4",
                "1 已弹出，6 随后弹出，留下 4。",
            ),
            (
                "wf_stack_b1",
                "空栈依次 push(3)、push(9)、pop()，此时栈顶是？",
                ["3", "9", "空栈"],
                "3",
                "最后进入的 9 已出栈，剩下的栈顶为 3。",
            ),
            (
                "wf_stack_b2",
                "执行 push(X)、push(Y)、pop()、push(Z)、pop()，剩余元素是？",
                ["X", "Y", "Z"],
                "X",
                "Y 和 Z 分别被弹出，X 保留在栈中。",
            ),
            (
                "wf_stack_b3",
                "执行 push(8)、push(10)、pop()、push(12)、pop()，此时栈顶是？",
                ["8", "10", "12"],
                "8",
                "10、12 依次被弹出，栈中剩下 8。",
            ),
        ]
        for key, prompt, options, answer, explanation in extra:
            qkey = key + ":v1"
            if db.get(Question, qkey):
                continue
            db.add(
                Question(
                    key=qkey,
                    question_id=key,
                    version=1,
                    knowledge_id="stack",
                    prompt=prompt,
                    options=options,
                    answer=answer,
                    explanation=explanation,
                    source="自编流程演示题；需正式人工复核",
                    status="published",
                    level="apply",
                    dataset="demo-seed",
                )
            )
            db.flush()
            aid = str(uuid4())
            db.add(
                Annotation(
                    id=aid,
                    question_key=qkey,
                    provider="demo-fixture",
                    rule_version="bloom-0.1",
                    created_at=time.time(),
                    payload={
                        "question_id": key,
                        "question_version": 1,
                        "primary_level": "apply",
                        "secondary_levels": [],
                        "rationale": "按给定规则推演栈操作",
                        "confidence": 0.5,
                        "ambiguity_note": "流程演示，非模型实测",
                    },
                )
            )
            db.flush()
            db.add(
                Review(
                    id=str(uuid4()),
                    annotation_id=aid,
                    reviewer_id="editor",
                    decision="approve",
                    reason="明确标记的模拟审核夹具",
                    final_level="apply",
                    content_verified=True,
                    created_at=time.time(),
                )
            )
        db.add(
            Audit(
                id=str(uuid4()),
                actor_id="editor",
                action="ensure_design_mock_fixtures",
                target="design-flow-v1",
                at=time.time(),
            )
        )
        db.commit()

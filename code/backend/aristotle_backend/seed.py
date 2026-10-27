"""Opt-in local demonstration fixtures; never an automatic production bootstrap."""

import argparse
import os
import time
from uuid import uuid4

from sqlalchemy import select

from .app import DEFAULT_DB
from .db import Annotation, Audit, Graph, Question, Review, User, open_database
from .security import hash_password

NODES = [
    {"id": "linear", "name": "线性结构基础", "prerequisites": []},
    {"id": "stack", "name": "栈的概念", "prerequisites": ["linear"]},
    {"id": "stack_ops", "name": "栈操作与分析", "prerequisites": ["stack"]},
]

# All original teaching examples. Review rows below simulate the release workflow;
# they must not be cited as actual independent human content review.
BANK = [
    (
        "l1",
        "linear",
        "remember",
        "线性结构中，元素之间的基本关系是？",
        ["一对一", "一对多", "多对多"],
        "一对一",
        "线性结构的元素按先后次序形成一对一关系。",
    ),
    (
        "l2",
        "linear",
        "remember",
        "非空线性表的第一个元素有几个直接前驱？",
        ["0", "1", "2"],
        "0",
        "第一个元素没有直接前驱。",
    ),
    (
        "l3",
        "linear",
        "remember",
        "顺序存储结构通常使用哪种空间存放相邻元素？",
        ["连续存储空间", "必须不连续", "只使用磁盘"],
        "连续存储空间",
        "顺序存储用连续空间表示逻辑上的相邻关系。",
    ),
    (
        "c1",
        "stack",
        "understand",
        "为什么叠放盘子能用来解释栈？",
        ["最近放上的盘子先取走", "最早放上的盘子先取走", "每次随机取一个"],
        "最近放上的盘子先取走",
        "从同一端放入和取出，使最后加入的对象先离开。",
    ),
    (
        "c2",
        "stack",
        "understand",
        "函数调用返回次序为何适合用栈表示？",
        ["后调用的函数先返回", "所有函数同时返回", "先调用的函数总先返回"],
        "后调用的函数先返回",
        "嵌套调用先完成内层调用，对应后进先出的次序。",
    ),
    (
        "c3",
        "stack",
        "understand",
        "栈与一般线性表相比，主要限制是什么？",
        ["只在一端执行入栈和出栈", "元素必须是整数", "元素不能重复"],
        "只在一端执行入栈和出栈",
        "栈限制操作发生在栈顶；限制并不来自元素类型。",
    ),
    (
        "s1",
        "stack_ops",
        "apply",
        "依次将 1、2、3 入栈，连续出栈两次。第二次出栈元素是？",
        ["1", "2", "3"],
        "2",
        "第一次弹出 3，第二次弹出 2。",
    ),
    (
        "s2",
        "stack_ops",
        "apply",
        "执行 push(A)、push(B)、pop()、push(C) 后，栈顶元素是？",
        ["A", "B", "C"],
        "C",
        "B 弹出后 C 入栈，成为新的栈顶。",
    ),
    (
        "s3",
        "stack_ops",
        "apply",
        "空栈执行 push(4)、pop()、push(6)、push(8)、pop() 后，剩余元素是？",
        ["4", "6", "8"],
        "6",
        "4 与 8 先后弹出，只剩下 6。",
    ),
    (
        "a1",
        "stack_ops",
        "analyze",
        "数组栈规定 top 为栈顶下标，空栈 top=-1。错误入栈代码为 data[top]=x; top++。错误根因是？",
        ["先写入再递增导致空栈访问下标 -1", "数组栈不能存储 x", "每次应把 top 减一"],
        "先写入再递增导致空栈访问下标 -1",
        "根据 top 的定义，应先递增再写入，错误来自状态含义与更新顺序不一致。",
    ),
    (
        "a2",
        "stack_ops",
        "analyze",
        "栈顶下标为 top。pop 先执行 top-- 再返回 data[top]。单元素栈调用后访问了 -1，下列定位正确的是？",
        ["读取栈顶值应在递减 top 之前", "应删除整个数组", "入栈必须从数组末尾开始"],
        "读取栈顶值应在递减 top 之前",
        "应先保存当前栈顶值，再改变栈顶位置，避免读取到前一位置。",
    ),
    (
        "a3",
        "stack_ops",
        "analyze",
        "括号匹配程序遇到右括号只判断栈非空就弹出，导致 '(]' 被接受。缺失的检查是？",
        ["栈顶左括号与当前右括号类型是否匹配", "输入长度是否为偶数即可", "字符是否按字典序排列"],
        "栈顶左括号与当前右括号类型是否匹配",
        "非空只说明数量上有候选左括号，类型关系还需要单独判断。",
    ),
]


def seed_demo(sessions, password="demo-password"):
    with sessions() as db:
        if db.scalar(select(User.id).limit(1)) or db.scalar(select(Graph.version).limit(1)):
            return False
        for name, role in [("student1", "student"), ("student2", "student"), ("editor", "maintainer")]:
            db.add(User(id=name, username=name, role=role, password_hash=hash_password(password)))
        db.add(Graph(version="ds-demo-v1", nodes=NODES))
        db.flush()
        for qid, kid, level, prompt, options, answer, explanation in BANK:
            key = f"{qid}:v1"
            db.add(
                Question(
                    key=key,
                    question_id=qid,
                    version=1,
                    knowledge_id=kid,
                    prompt=prompt,
                    options=options,
                    answer=answer,
                    explanation=explanation,
                    source="团队自编演示样例；非正式审核题库",
                    status="published",
                    level=level,
                    dataset="demo-seed",
                )
            )
            db.flush()
            candidate_id = str(uuid4())
            db.add(
                Annotation(
                    id=candidate_id,
                    question_key=key,
                    payload={
                        "question_id": qid,
                        "question_version": 1,
                        "primary_level": level,
                        "secondary_levels": [],
                        "rationale": explanation,
                        "confidence": 0.5,
                        "ambiguity_note": "演示标签，正式使用前需独立人工审核",
                    },
                    provider="demo-fixture",
                    rule_version="bloom-0.1",
                    created_at=time.time(),
                )
            )
            db.flush()
            db.add(
                Review(
                    id=str(uuid4()),
                    annotation_id=candidate_id,
                    reviewer_id="editor",
                    decision="approve",
                    reason="模拟审核种子，仅用于流程演示；不表示独立人工审核已完成",
                    final_level=level,
                    content_verified=True,
                    created_at=time.time(),
                )
            )
        db.add(
            Audit(
                id=str(uuid4()),
                actor_id="editor",
                action="seed_demo_fixtures",
                target="ds-demo-v1",
                at=time.time(),
            )
        )
        db.commit()
        return True


def main():
    parser = argparse.ArgumentParser(description="创建本地演示账号与模拟审核题库；仅对空库执行")
    parser.add_argument("--demo", action="store_true", required=True)
    parser.parse_args()
    engine, sessions = open_database(os.getenv("ARISTOTLE_DATABASE_URL", DEFAULT_DB))
    created = seed_demo(sessions, os.getenv("ARISTOTLE_DEMO_PASSWORD", "demo-password"))
    engine.dispose()
    print(
        "已创建 student1 / student2 / editor 演示账号和 12 道演示题。"
        if created
        else "数据库已有数据，跳过初始化，未覆盖原有内容。"
    )


if __name__ == "__main__":
    main()

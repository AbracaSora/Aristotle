# 408 四科题库与知识图谱

本目录提供数据结构、计算机组成原理、操作系统、计算机网络四科的题目、知识点、知识关系和考纲映射，用于知识地图展示、选择题练习及认知层级标注。

共 **203 个知识点、650 道单选题、325 条知识关系**。每个知识点配置 3–5 道题。

## 四科内容

| 科目 | 代码 | 知识点 | 题目 | 科内关系 | 题库 |
| --- | --- | ---: | ---: | ---: | --- |
| 数据结构 | DS | 64 | 213 | 118 | [questions.jsonl](data-structures/questions.jsonl) |
| 计算机组成原理 | CO | 40 | 128 | 56 | [questions.jsonl](computer-organization/questions.jsonl) |
| 操作系统 | OS | 46 | 146 | 63 | [questions.jsonl](operating-systems/questions.jsonl) |
| 计算机网络 | CN | 53 | 163 | 73 | [questions.jsonl](computer-networks/questions.jsonl) |

科内关系共 310 条，另有 15 条跨科关系。统计、文件路径及哈希见 [manifest.json](manifest.json)。

## 目录结构

四科使用相同的维护方式，每科四份核心文件；接口导出和检查报告统一保存。

```text
resource/
├── README.md
├── manifest.json                  # 四科索引、数量与哈希
├── cross_subject_relations.jsonl  # 跨科关系
├── validation_report.json         # 四科统一检查报告
├── data-structures/               # 数据结构
├── computer-organization/         # 计算机组成原理
├── operating-systems/             # 操作系统
├── computer-networks/             # 计算机网络
├── exports/
│   ├── aristotle_graph.full.json  # 四科知识图接口格式
│   ├── aristotle_questions.jsonl  # 四科题目接口格式
│   └── aristotle_candidates.jsonl # 四科认知标签候选接口格式
└── scripts/
    ├── build_resources.py        # 统一校验、生成导出及报告
    ├── verify_answers.py         # 四科计算与算法核对
    └── answer_cases.json         # 核对用例绑定的题干、选项哈希
```

每个科目目录均包含：

```text
<科目目录>/
├── questions.jsonl          # 题干、选项、答案、解析及题目属性
├── knowledge_points.jsonl   # 知识点、章节及考纲定位
├── relations.jsonl          # 本科目知识关系
└── syllabus.json            # 考纲版本、来源及条目映射
```

## 文件用途与维护边界

| 文件 | 内容与用途 | 是否直接编辑 |
| --- | --- | --- |
| 各科 `questions.jsonl` | 题目、所属知识点、难度、认知候选、答案解析和来源字段 | 是 |
| 各科 `knowledge_points.jsonl` | 知识点稳定 ID、名称、科目、章节及考纲定位 | 是 |
| 各科 `relations.jsonl` | 关系两端、类型、方向与理由 | 是 |
| 各科 `syllabus.json` | 考纲来源、版本、核验状态与条目到知识点的映射，用于检查覆盖和遗漏 | 是 |
| `cross_subject_relations.jsonl` | 不同科目之间的前提、建议、关联或应用关系 | 是 |
| `manifest.json` | 四科资源的统一索引、数量和文件哈希 | 否，由脚本生成 |
| `exports/*.json*` | 按当前后端请求模型整理的四科合并数据 | 否，由脚本生成 |
| `validation_report.json` | 格式、引用、题量、图关系、计算答案和接口格式的统一检查结果 | 否，由脚本生成 |
| `scripts/build_resources.py` | 校验核心文件，生成索引、三份接口导出和一份报告；可按需生成阅读视图 | 按维护需要调整 |
| `scripts/verify_answers.py` | 独立计算或模拟指定题目的答案 | 题目计算条件改变时同步核对 |
| `scripts/answer_cases.json` | 将计算用例绑定到具体题干和选项，防止题目改变后继续使用旧计算结论 | 核对计算条件后更新 |

四科都以 JSONL 和 `syllabus.json` 为维护源。来源类型、年份、网址、题源核验状态及修订说明仍保存在题目字段中。阅读版、覆盖明细和图的派生视图按需生成。

JSONL 使用 UTF-8 编码，每行一个 JSON 对象。题目通过 `knowledge_point_id` 关联知识点，关系通过 `source_id` 和 `target_id` 连接节点。`DS-`、`CO-`、`OS-`、`CN-` 前缀区分四科知识点，跨科引用也使用完整 ID。

题目中的 `options` 是 A/B/C/D 文本对象，`answer` 是正确选项字母；`difficulty` 为 1–5 的难度估计，`cognitive_level_candidate` 表示记忆、理解、应用或分析，两者含义不同。修改已使用的题目时保留稳定 ID，并按版本约定递增 `version`。

考纲映射按 2027 版公开转录建立，各科分别包含 56、64、66、80 个末级定位条目。一个条目可以对应多个知识点，一个知识点也可以关联多个条目；题目上的考纲定位表示所属知识范围。

## 关系与接口导出

| 关系类型 | 含义 | 是否作为强制前提 |
| --- | --- | --- |
| `prerequisite_of` | 来源点是目标点的必备前提 | 是，多个前提需同时满足 |
| `recommended_before` | 建议先学习来源点 | 否 |
| `related_to` | 两点之间的关联或比较，无方向 | 否 |
| `applied_in` | 来源知识或方法应用于目标场景 | 否 |

这些关系用于教学组织，不表示考纲规定了唯一学习路线。科内关系只连接本科目节点，跨科联系集中记录在根目录文件中。

接口导出对应当前代码中的 `GraphInput`、`QuestionInput`、`CandidateInput`：图中 `prerequisites` 只取必备关系；题目选项转换为按 A/B/C/D 排列的文本数组，答案转换为对应选项全文。科目、章节、难度、考纲定位和其他关系保留在核心 JSONL 中，不添加到后端尚未定义的请求字段。候选标签不等同于发布记录，文件生成也不会自动写入数据库。

**当前后端单张知识图上限为 200 个节点，本包完整图有 203 个节点，整体导入前需处理该限制。**

## 统一生成与检查

在仓库根目录执行，需 Python 3.9 或以上及 Pydantic 2；这些脚本不启动后端、不连接数据库、不执行发布。

修改任一科的核心文件或跨科关系后，重新生成统一输出：

```sh
python3 resource/scripts/build_resources.py --write
```

只检查资源、计算结果及生成文件是否与输入一致，不改文件：

```sh
python3 resource/scripts/build_resources.py
```

如需单独执行计算核对，可运行 `python3 resource/scripts/verify_answers.py`，只在终端输出摘要，不另存报告。统一报告中的独立计算或模拟共覆盖 189 道题：数据结构 80 道、组成原理 43 道、操作系统 27 道、网络 39 道；范围仅限报告列出的题目。

需要便于阅读的题目清单、覆盖明细、完整关系图、依赖和学习顺序时，将它们生成到资源目录之外：

```sh
python3 resource/scripts/build_resources.py --views-dir /tmp/aristotle-review
```

该命令在指定目录生成各科的 `全部题目.md`、`知识点与覆盖.md`、`coverage.json`、`syllabus.json`，以及四科合并的 `knowledge_graph.json`、`dependencies.jsonl`、`coverage.json`、`learning_order.json`，不改变核心材料。

每点总题量为 3–5 道，不等于记忆、理解、应用、分析各维度都有三道题。统一报告给出认知题量缺口汇总，按需生成的 `coverage.json` 提供逐点明细。

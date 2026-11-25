# Aristotle 408 代码质量报告

2026-11-25 · 第 9 周开发实践

本次扫描覆盖后端 API、数据库迁移和学习规则引擎，共 24 个 Python 文件。按基线圈复杂度从高到低选择五个函数，先为它们补回归测试，再修改实现。前端另行运行类型检查、测试和生产构建。[课程任务](https://github.com/bettermorn/IntelligentSWEPractice/blob/HEAD/courseware/pages/part3develop.md#第9周实践任务) · [测试与扫描基线](https://github.com/AbracaSora/Aristotle/commit/5dcf79e) · [五项重构的代码差异](https://github.com/AbracaSora/Aristotle/commit/835374c)

## 两次扫描结果

| 指标 | 重构前 | 重构后 |
| --- | ---: | ---: |
| Bug 候选告警（Pylint E/F） | 101 | 101 |
| Code Smell（已启用的 Pylint R 类规则） | 29 | 24 |
| 函数最高圈复杂度 | 36 | 24 |
| 函数平均圈复杂度 | 5.17 | 4.86 |
| 圈复杂度大于 20 的函数 | 10 | 5 |
| 函数数（含方法和嵌套函数） | 180 | 190 |
| 重复代码行数及重复率 | 24 行，0.45% | 24 行，0.45% |

两次均使用 Python 3.12、Pylint 3.3.8 和 Radon 6.0.1。Pylint 统计重复代码、分支过多、局部变量过多、语句过多和嵌套过深五类坏味道。Radon 对每个函数单独计分，提取出的辅助函数也计入均值。[扫描配置](../../pyproject.toml) · [统计脚本](../../scripts/scan_quality.py)

**101 条 Bug 候选告警的复核。** 其中 98 条来自 Alembic 迁移代理的 14 个不同成员。核对已安装版本后，13 个成员可直接访问，另一个成员 `context.config` 在迁移上下文中可访问。另有 3 条指向 SQLAlchemy 的 `func.count`，在 SQLite 上实际执行 `select(func.count())` 返回了 1。本次在这些告警中确认的运行缺陷为 0。原始告警全部保留，便于检查者复核。

## 扫描报告截图

两图均为浏览器直接打开扫描器输出文本后的截图。文本版还包含每条 Pylint 告警的位置和原因。

**重构前** · [完整输出](quality/before.txt)

![重构前扫描摘要，最高圈复杂度 36，29 条代码坏味道](quality/before.png)

**重构后** · [完整输出](quality/after.txt)

![重构后扫描摘要，最高圈复杂度 24，24 条代码坏味道](quality/after.png)

## 五处重构前后对照

| 函数 | 复杂度 | 原实现 | 本次修改与验证 |
| --- | ---: | --- | --- |
| `workflow.create_recommendation` | 36 → 14 | 在同一函数内检查诊断资格、选择认知层级、回溯错题并创建任务。 | 拆出三项业务判断。已完成先修、理解证据充足时，显式请求理解题仍返回 3 道理解题。 |
| `retrieval.semantic_search` | 31 → 16 | 向量打分、授权复查和混合排序写在同一段流程中。 | 分离向量计算和结果排序。模型请求期间撤回授权的私人资料会从返回结果中消失。 |
| `providers.request_model` | 26 → 14 | 在重试循环内同时判断 HTTP 状态、解析响应、提取用量和记录结果。 | 提取响应校验，保留失败记账。允许重试一次时，连续 429 记录两次调用，403 只记录一次。 |
| `resource_seed.import_resource_demo` | 26 → 9 | 在一次长循环中写入题目、资料和章节，多次过滤知识点。 | 分开导入知识点内容和发布章节，按学科、章节预分组。第二个知识点缺题时，已处理的图和第一道题均回滚。 |
| `policy.recommend` | 26 → 14 | 给每个候选知识点排序时反复遍历题库和作答，同分时再查拓扑位置。 | 先按知识点和层级归集库存，再一次汇总最近作答时间。验证乱序重练记录下，未练题优先、已练题按最近练习时间升序排列。 |

逐项评审意见、对应测试和仍需关注的代码见[代码评审记录](code_review.md)。

## 回归结果与复现

| 检查 | 结果 |
| --- | --- |
| 原版后端测试 | 78 通过，1 项 PostgreSQL 专用测试在本地 SQLite 环境跳过 |
| 新增回归测试 | 6 个用例在重构前全部通过，重构后再次通过 |
| 重构后后端测试 | 本地 84 通过，1 项 PostgreSQL 专用测试跳过 |
| Ruff 检查与格式 | 均通过，检查 39 个 Python 文件的格式 |
| 前端类型、测试与构建 | 20 个测试通过，生产构建成功。Vite 提示主代码包超过 500 kB |
| PostgreSQL / pgvector | GitHub Actions 使用 PostgreSQL 17 和 pgvector 运行后端集成测试，检查通过。[运行记录](https://github.com/AbracaSora/Aristotle/actions/runs/45630380174) |

在仓库根目录执行下列命令。使用 `5dcf79e` 可复现重构前的业务代码，使用 `835374c` 可复现重构后。两个提交使用相同的扫描脚本和规则。

```sh
uv run --locked --python 3.12 --with pylint==3.3.8 --with radon==6.0.1 python scripts/scan_quality.py
uv run --locked pytest -q
uv run --locked ruff check code/backend code/core_engine tests scripts
uv run --locked ruff format --check code/backend code/core_engine tests scripts
```

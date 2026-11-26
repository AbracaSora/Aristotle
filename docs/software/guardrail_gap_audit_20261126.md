> **2026-11-26 本轮补完更新**：资料自动worker、PDF子进程/时限/中断恢复、私有轮转日志、生产默认凭据及演示导入保护已实现。后端185项通过、1项跳过；相关PG回归两组93项/27项通过（有重叠）。核心分支与增量覆盖门禁通过；严格结构门禁仍失败。最新记录见 [worker与日志](worker_and_logs_20261126.md)、[剩余工作](remaining_work_20261126.md) 及 [原始护栏报告](quality_evidence/completion_20261126/guardrails.json)。

> **2026-11-26 数据库状态更新：连接问题已解决。** 真实 PostgreSQL 集成测试110项全部通过；业务库已升级至 `0003_curriculum_tests`，原有22张表共148条记录的行数全部保持不变，新增7张表，pgvector 0.8.7 可用。未导入演示数据、未重建业务库。证据：[PG测试日志](quality_evidence/after/postgresql-tests.txt)、[迁移行数核对](quality_evidence/after/business-migration.json)。下文“Docker不可连接/迁移未执行”的历史记录已被本次结果取代；其余质量与人工验收未据此自动通过。

# 护栏与遗漏交付核查

日期：2026-11-26。核查范围为课程第9/10周交付、课程 CodeQualitySkill 及其使用说明、当前后端评审未关闭项。沿用 master，不创建新分支。

## 核查依据与更正

课程原始文件与使用说明的链接、内容SHA256在 `quality/code-quality-guard/source.json`。使用说明明确允许“在对话中引用”，也提供安装技能和将规则写入 AGENTS.md 的方式。因此此前缺失的是**项目持续生效和自动门禁**，不能将“未安装”推断成“完全未使用过规则”。本轮按用户要求将其落地。

本地 `quality/code-quality-guard/SKILL.md` 是项目适配版，配套保留完整原评审模板。根 `AGENTS.md` 要求后续修改前加载该文件；不依赖只存在当前聊天的口头约定。

## 发现、实施及证据

| 原遗漏/不充分处 | 本轮行动 | 验证方式 |
|---|---|---|
| 只有对话引用，没有仓库护栏入口 | 新增AGENTS.md、项目技能、配套模板、来源hash | 文件可随仓库共享，AGENTS明确技能路径 |
| 没有实际提交前hook | 新增.pre-commit-config.yaml，并执行pre-commit install | 此本机.git/hooks/pre-commit已生成、可执行；克隆到其他机器须重新安装 |
| CI只检查Pylint错误及综合覆盖率 | 改为统一check_guardrails.py --full入口 | 正常/超阈值/工具崩溃/导入环/漏覆盖等护栏回归用例 |
| 未自动量化尺寸/认知复杂度/参数/嵌套/条件 | 增加AST、Radon、cognitive-complexity全量检查 | 每条保留file/line/name/rule/actual/limit，严格门槛失败返回非零 |
| 只看总覆盖，未看增量和核心分支 | 增加HEAD到当前工作区的可执行变更行统计，包含未跟踪源码；逐核心文件分支≥80% | 报告分别列增量与核心分支，不把总覆盖代替分支 |
| 缺类型检查 | 接入mypy --check-untyped-defs并修复配置/可空值/字典/方言insert类型问题 | 38个源文件检查通过；不冒充全库mypy --strict类型完备 |
| 没查真实模块导入环 | 增加静态项目导入图并消除db→migrations→db环 | schema_contract独立保存迁移元信息；动态导入单独列出，不默认算安全 |
| 扫描进程失败可能被误判 | 明确工具退出码、JSON有效性和超时 | Pylint进程以32退出的故障用例被拒绝，不生成干净报告 |
| 缺密钥扫描 | 增加detect-secrets，处理scan返回0但有候选的情况 | 保存hash化候选，不打印真实值；候选未分流即门禁失败，不设全局忽略名单 |
| 工具未全部锁定 | uv.lock增加认知复杂度、hook、密钥和增量覆盖工具 | 基础工具版本锁定；新增包用于实际检查，不用仅安装代替启用 |
| 大路由安装文件仍未拆 | 按学习/资料/内容/系统拆组，公共支持单列 | 811行旧flow_routes变37行组合入口；拆出的每个模块低于400行；37项相关回归通过 |
| 旧核心推荐CC26 | 拆开目标准入、排序、层级与选题步骤 | recommend CC降至8；27项规则与流程回归通过，原外部签名保持兼容 |
| capabilities仍将真实PDF/关联报mock | 改成pypdf-text、name-match-v1-requires-confirmation | 跟实际实现一致，不把名称匹配写成模型关联 |
| 测试框架弃用警告 | 按安装版本Starlette源码指引添加开发依赖httpx2 | API/护栏测试与全量测试复核，不关闭警告 |
| 护栏失败会使CI跳过PG测试 | PostgreSQL集成测试设置always执行 | 工作流依然失败，但能继续收集独立DB验收结果 |
| 未提交的新文件被评审表写成已入版本控制 | 更正评审记录 | 本轮仍有未跟踪文件，尚未提交/推送，不能写成已进入主干 |

## 护栏仍应失败的原因

安装并运行护栏不意味着既有代码自动达到阈值。当前仍有尺寸、复杂度、参数、重复块、核心分支覆盖、过大的未提交diff等问题；密钥扫描还报出开发/CI/测试凭据和元数据hash候选，需要逐条判读，不能直接等同真实密钥泄露，也不能默默忽略。

完整本轮结果见 `quality_evidence/guardrails_20261126/`（工具执行后归档）。本次严格护栏保留失败状态；未降低阈值、设置历史债务自动豁免或跳过测试。框架依赖注入和旧接口兼容造成的参数超限也仍显示在报告。

## 本轮不能独立完成的外部验收

- 本机Docker daemon仍不可连接；无法运行真实PostgreSQL 0003升级/并发/pgvector并核对业务行数。准备好的verify_backend_upgrade.py先隔离测试再迁移；未擅自重建业务库。
- 人工评审必须由真实成员完成，正式题库人工审核及100题双评审质量评测需要实际材料、评审人员及结论。AI不代签，也不生成虚构成绩。
- 真实模型/PDF负载与进程级故障测试、日志/备份恢复还需要可运行环境与正式验收样本。此前原型演示不代替这些证据。

这些是未完成验收，不是已关闭问题。自动检查能做的部分已经进入脚本/本地hook/CI，剩余结果按失败与阻塞原因明确记录。

## 最终执行结果

- 后端测试：126 passed, 1 skipped in 51.84s。另外28项API/护栏兼容测试通过。
- 编译、Ruff、格式、mypy（含未标注函数体）、扫描工具执行和依赖审计通过；项目内静态导入环为0。
- 新增/修改行覆盖率：91.17%。
- 严格门禁：FAILED。结构阈值发现127条，重复块3个，源码diff共4438行；3个核心文件分支覆盖低于80%，密钥候选12条未分流。
- 原始报告：[guardrails.json](quality_evidence/guardrails_20261126/guardrails.json)、[逐条位置CSV](quality_evidence/guardrails_20261126/findings.csv)、[测试日志](quality_evidence/guardrails_20261126/tests.txt)、[密钥候选hash报告](quality_evidence/guardrails_20261126/secrets.json)、[HTML汇总](quality_evidence/guardrails_20261126/report.html)。

当前评审单元已执行三轮自动检查/修复；依据项目技能的三轮上限，输出未通过及问题清单，未以豁免、删除检查或伪造通过收尾。后续按明确的评审单元继续关闭，不应直接合并/发布。

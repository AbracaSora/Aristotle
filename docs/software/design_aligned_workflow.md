# 原设计对齐：端到端流程原型

更新：2026-10-28。依据仓库原有 [功能需求规范](../requirements/functional_spec.md)、[问题定义](../requirements/problem_definition.md) 和 [非功能需求](../requirements/nonfunctional_spec.md)。本次实现覆盖流程和持久化，不修改原需求，不代表正式功能或非功能验收通过。

## 运行与体验

在仓库根目录：

```bash
uv sync --locked --python 3.12
ARISTOTLE_DATABASE_URL=sqlite:///.local/integration.db uv run python -m aristotle_backend.seed --demo --design-flow
ARISTOTLE_DATABASE_URL=sqlite:///.local/integration.db uv run uvicorn aristotle_backend.app:create_app --factory --host 127.0.0.1 --port 8020
```

另一个终端，进入 `code/frontend`：

```bash
npm ci --ignore-scripts --no-audit --no-fund
ARISTOTLE_BACKEND_URL=http://127.0.0.1:8020 npm run dev -- --host 127.0.0.1 --port 5180 --strictPort
```

打开 http://127.0.0.1:5180/ 。显式种子增量添加学习范围、公共讲义、6 道应用样例和 admin，不覆盖既有账户、作答或资料。学生 student1/student2、维护者 editor、管理员 admin；默认密码 demo-password，若初始化曾通过环境变量修改密码，沿用原密码。演示账号不用于正式部署。

## 设计到实现

| 原设计 | 当前可体验流程 | 实现边界 |
| --- | --- | --- |
| FR-1 账号与范围 | 学生选择已发布范围；未开放科目标记；切换保留记录；私人数据按账号隔离 | 仅数据结构局部样例，不是全部 408 |
| FR-2 资料 | 文字导入任务 → 分段及来源 → 候选知识关联 → 逐段确认/纠正/取消/排除 → 任务引用；删除后实时撤除历史来源原文 | 文字分段真实；关联 mock；PDF 使用固定两页 mock，不读取实际 PDF；真实抽取返回 501 |
| FR-3 内容 | 录入完整题目版本 → 标注任务 → 候选及歧义提示 → 人工核验答案/解析/最终标签 → 发布；修订建新版本 | 模型输出 mock，标注质量未验证；所有候选仍经过后端 schema 和人工审核门禁 |
| FR-4 诊断 | 按范围、知识点和四类认知活动分段；保存不同题目证据；三种知识状态；独立复测 | 可解释规则基线；不等同于完成知识空间模型及测量效度评估 |
| FR-5 学习安排 | 完成初始诊断 → 解释目标、证据和步骤 → 接受/更换/跳过 → 资料或练习 → 反馈 → 下一安排/复测 | 遵循先修；理解有支持且应用不足时选应用；持续应用困难可回看理解资料；阅读不生成作答证据 |
| FR-6 反馈与纠错 | 静态确定性判分、幂等保存、历史版本、知识地图、任务轨迹、问题上报；维护者处理/停用，历史显示原因，重算排除 | 模型辅助解释接口 501，使用规则依据及静态解析；原型未验证学习收益 |
| FR-7 运营 | 角色分配、配置版本、超时/重试/配额样例、任务失败及人工重试、内容/角色/配置/拒绝越权审计 | 真实供应商、真实 token 用量和超时指标未接；配额锁限单进程原型；备份自动化、负载和安全验收未完成 |
| FR-8 P1 | 分类保留评价、创造，学习入口只使用首版四类 | 开放题及人工量规尚未实现 |

公共种子题及公共讲义明确标为自编演示夹具；模拟审核记录不是正式专家审核记录。mock 不会替用户作答，不会将预测或阅读计为掌握。

## 学生流程

1. 明确选择范围。无需上传讲义也可使用公共内容。
2. 初始诊断按“知识点 × 认知活动”分段，每段最多 3 题；不足或复用旧题明确提示。诊断允许探测先修未掌握的知识点；学习推荐继续遵守先修约束。
3. 全部诊断段完成后，才能请求本范围的学习推荐。推荐展示目标、证据事实、理由、内容来源及计划步骤。
4. 学生接受后才能提交答案；可以关闭、刷新、重新登录后继续。非诊断任务可更换或跳过，并保存状态。
5. 服务端保存静态判分，完成全部题目后提交任务完成，生成知识状态及下一步反馈。
6. 若安排资料复习，阅读完成只更新任务状态；下一步建立针对原目标的独立复测。优先使用未见过的稳定题目 ID；库存不足时明确说明记忆效应，不能宣称学习收益。
7. 进行中题目被停用后，可重建诊断或更换任务，原始作答保留。新分配排除停用版本。

每次独立诊断按参与的知识点/认知维度设证据边界，该维度使用本轮以来的作答与 14 天窗口，窗口内按稳定 question_id 取首次有效作答。其他维度保留原有证据，历史作答不删除。此复测口径和“最近两道不同应用/分析题出错即回看资料”的阈值是本次落实流程的**可评审原型参数**，原需求只规定可回退，未规定这两个具体参数；并非已经验证的教学算法。

## API 与替换点

统一前缀 `/api/v1`，Bearer 会话，业务规则由服务端执行。完整字段以运行中的 `/openapi.json` 和 `/docs` 为准。

| 模块 | 接口 |
| --- | --- |
| 能力边界 | GET `/capabilities` |
| 范围和恢复 | GET `/scopes`、PATCH `/learning-scope`、GET `/learning-context` |
| 诊断 | POST `/diagnostics`、GET `/diagnostics/{id}`、POST `/diagnostics/{id}/restart` |
| 推荐和生命周期 | POST `/recommendations`、GET `/tasks/{id}`、POST `/tasks/{id}/actions`（accept/start/complete/skip/replace）、GET `/learning-timeline` |
| 答题与历史 | POST `/tasks/{id}/attempts`、GET `/learning-state`、GET `/history` |
| 资料任务 | POST `/material-imports`、GET `/jobs`（本人导入记录）、GET `/jobs/{id}`、POST `/jobs/{id}/run`、POST `/jobs/{id}/retry` |
| 来源确认 | GET `/materials`、PATCH `/materials/{id}/chunks/{chunk_id}`、DELETE `/materials/{id}` |
| 标注任务 | POST `/admin/questions/{key}/annotation-jobs`、GET `/admin/jobs`；候选/审核沿用 `/admin/candidates` 和 `/admin/candidates/{id}/review` |
| 内容纠错 | POST/GET `/content-reports`、GET `/admin/content-reports`、POST `/admin/content-reports/{id}/resolve` |
| 运营 | GET/PATCH `/admin/provider-settings`、GET `/admin/users`、PATCH `/admin/users/{id}/role`、GET `/admin/audit` |
| 明确的 501 占位 | POST `/material-imports/pdf`、POST `/admin/providers/live`、POST `/tasks/{id}/explanation` |

任务运行采用“入队 → 手动执行 mock → 成功/失败”，并非生产消息队列或后台 worker。运行使用条件更新防止同一 job 重复产生候选；重试产生新的 job，并重新预留配额。模拟扫描件/加密/超限/超时、限流/结构错误/旧版本错误都有显式失败状态。后台任务列表不包含学生私人导入正文。

资料任务只存来源 ID 引用。读取历史任务时重新校验所有者、删除标志和当前知识关联；取消/纠正后不继续显示旧关联。删除时清空正文、片段及相关导入 job 原文。自动备份生命周期和生产保留政策仍需另行实现；本次升级前保留的本地人工数据库备份是开发恢复副本，不承诺已满足 NFR 备份清理。

旧 `/tasks` 为原型兼容接口：尚未选择范围的旧调用保留旧行为；新学习端只走明确范围和诊断门禁。后续迁移正式服务时应停止旧兼容路径。

## 验证与剩余工作

自动化：后端 50 项、前端 15 项；Ruff 检查和格式检查、Vue TypeScript 与生产构建。新增覆盖不同学生的不同认知安排、复习不加证据、独立复测、范围隔离、任务接受/完成/更换/跳过、资料来源清理、失败 mock 与审核门禁、角色/越权审计、并发配额预留及停用后恢复。

浏览器人工路径：student1 选择“栈：从理解到应用” → 记忆/理解/应用三段诊断；理解全对、应用全错的人工演示输入得到资料复习；阅读完成证据仍为 6 题；随后使用另组三道应用题复测；答完一题刷新，恢复到第 2 题。文字导入显示来源段落与待确认片段，确认后才变为有效关联。内容工作台实际验证了草稿、mock 候选、标签修正、审核发布及问题报告处理；管理员页面验证了配置、角色和审计入口。本次浏览器使用当前应用视口，没有单独执行多尺寸验收。

AC-01/04/05/07/08/09 可在规则与样例范围检验；AC-02/03/06 目前仅覆盖 mock 交互及错误门禁，**不能作为真实 PDF、真实 LLM 或真实外部服务验收**。正式题库、可靠知识关联、模型接入和标注评测、诊断效度及学习效果、30–50 人试用、性能/安全/备份验收仍未完成。

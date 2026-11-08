# PostgreSQL 切换与数据迁移

更新：2026-11-08。业务默认库改为 PostgreSQL 17，使用 SQLAlchemy 2.0 和 psycopg 3；Alembic 管理结构版本。SQLite 保留用于隔离测试和旧数据导入。此文描述可执行配置；实际连库、切换与验证状态见文末，不将配置交付等同于完成部署。

## 1. 启动数据库并升级结构

在仓库根目录执行，需本机 Docker Desktop 正常运行：

```bash
# 已有 .env 时保留它，核对其中的数据库 URL，避免误连旧库或其他环境。
test -f .env || cp .env.example .env
docker compose up -d --wait postgres
uv sync --locked --python 3.12
uv run python -m aristotle_backend.migrations
```

默认开发连接为 `postgresql+psycopg://aristotle:aristotle-local@127.0.0.1:5433/aristotle`。5433 映射到容器的 5432，仅绑定本机回环地址，数据保存在命名卷 `aristotle_postgres_data`。上述账号密码仅为本地开发样例。共享部署需独立配置凭据、角色和备份。

API、种子及迁移工具读取仓库根 `.env`；已导出的 shell 环境变量优先。`postgresql://` URL 会规范为 `postgresql+psycopg://`，连接不成功时不会降级到 SQLite。修改容器环境变量不会更改已有数据卷内的账号密码，应通过数据库账号管理操作调整，保留数据卷。

首个迁移 `0001_learning_workflow` 冻结现有 20 张业务表，创建外键、唯一约束、索引与版本表。服务启动仅检查迁移版本，不执行 `create_all` 或自动迁移；升级命令可重复运行且不插入演示数据。SQL 离线审阅：

```bash
uv run python -m aristotle_backend.migrations --sql
```

## 2. 导入旧 SQLite 数据，或初始化空演示库

两种初始化路径二选一。先停止旧后端的业务写入，确认源库；多个 SQLite 文件不会自动合并。此前联调库为 `.local/integration.db`，默认旧库 `.local/aristotle.db` 和录像用 `../work/readme-recording/demo.db` 是不同数据集。

保留原有联调数据：

```bash
uv run python -m aristotle_backend.import_sqlite --source .local/integration.db
```

导入工具用 SQLite backup API 生成一致性快照，含已提交 WAL 数据，备份位于忽略目录 `.local/sqlite-backups/`，文件权限 0600。源库只读，不改表、不写回。目标库必须已经迁移且没有任何业务数据；工具锁住目标业务表，在同一事务中按外键顺序复制并逐行核对 JSON、布尔值、时间、原文及关联，再调整知识图序列。失败回滚业务写入，已有数据的目标库拒绝再次导入，不覆盖或去重合并。

旧版 11 表库可导入现有字段一致的表，新增业务表保持空。额外的未知表、字段差异或源库外键异常会阻止导入。需要旧库新增样例范围时，可在导入后显式运行 `seed --demo --design-flow`；这会添加演示内容，正式部署不运行。

完全独立的新演示环境则执行：

```bash
uv run python -m aristotle_backend.seed --demo --design-flow
```

演示账号密码与旧文档一致。导入后既有密码和会话摘要保留，沿用原密码；种子不会重置已有账号。

## 3. 启动并确认实际后端

```bash
uv run uvicorn aristotle_backend.app:create_app --factory --host 127.0.0.1 --port 8020
```

健康检查 `GET http://127.0.0.1:8020/health` 应返回 `database: postgresql`。前端仍按既有方式设置 `ARISTOTLE_BACKEND_URL=http://127.0.0.1:8020`；重启前先确认旧服务占用情况，浏览器里已打开的旧演示不会自动切换数据库。

验证登录、原有学习记录、接受/作答/完成任务、资料读取与删除、维护者审核；重启后确认记录仍在。需要回看旧 SQLite 环境时先保留原服务和数据库版本，不能直接让新迁移向一个未登记版本的旧库建同名表，也不能对原库盲目 `stamp head`。

## 4. 测试与备份

如果命令执行环境无法连接本机 Docker/socket，可在 macOS 自己的终端运行以下一体化验证（需先在 Docker Desktop 确认 Engine running）：

```bash
docker compose up -d --wait postgres && uv run python scripts/verify_postgresql.py --import-sqlite .local/integration.db
```

脚本依次应用迁移、快照并导入指定 SQLite、报告实际库类型/版本/各表行数、创建独立的 `<业务库>_test` 库，再对随机 schema 执行真实 PostgreSQL 集成测试。结果保存在 `.local/postgresql-verification.log`（0600，连接串与密码脱敏），便于当前会话读取。测试角色需能在该测试库建 schema；首次创建测试库还需 CREATEDB 权限，或由管理员预先创建并通过 `--test-database` 指定。导入过的非空目标会拒绝再导入，此时重跑时去掉 `--import-sqlite` 参数。脚本不启动或停止已有后端。

`Cannot connect to the Docker daemon` 表示主机 Docker Engine 不可用；先打开 Docker Desktop，`docker info` 成功后再运行 Compose。后续 `Connection refused` 通常是容器尚未启动或端口未就绪的结果；`uv sync` 成功仅代表依赖安装完成。

默认 `uv run pytest -q` 使用临时 SQLite；执行迁移后才创建测试应用。PostgreSQL 测试使用独立测试数据库：

```bash
# 由本机管理员或数据库负责人先创建专用 aristotle_test 库并授予测试角色权限。
ARISTOTLE_TEST_DATABASE_URL=postgresql+psycopg://aristotle:aristotle-local@127.0.0.1:5433/aristotle_test uv run pytest -q tests/integration
```

每个测试创建随机 schema、应用真实 Alembic 迁移，结束仅删除该 schema。CI 已配置 PostgreSQL 17 服务并运行集成测试。测试覆盖原有学习闭环、并发幂等、审核唯一性、外键、迁移重复执行、结构与模型一致性、导入核对和失败回滚；未捕获 CI 运行结果前不声称通过。

开发库备份示例，输出文件含个人数据，不提交 Git：

```bash
docker compose exec -T postgres pg_dump -U aristotle -d aristotle -Fc > .local/aristotle.pgdump
```

恢复需使用专用空库，先执行删除记录重放再开放访问。每日备份、30 天保留、异地副本和恢复时限仍需落实与演练；命名卷、导入快照及一次 pg_dump 不等于完成这些要求。

## 5. 当前验证状态

2026-11-08 本轮更新：Compose 改为带 pgvector 的 PostgreSQL 17 镜像，沿用原数据卷。`0002_semantic_learning` 已实际应用，新增来源向量、调用记录及资料外传授权，共 22 张业务表。原业务行数保留，本轮 PostgreSQL 集成测试 **66 passed, 1 warning in 28.46s**。地图、模型接口及浏览器续跑状态见 [学习空间实现](learning_space_implementation.md)。

以下保留 `0001` 首次迁移时的历史证据，不代表当前新增能力未实现：

- 本地迁移/导入及原有规则与 API 回归：62 项通过，执行数据库为临时 SQLite；含 11 表旧库和 20 表现有库导入、失败回滚、配置优先级与实际数据库类型报告。
- 初始 PostgreSQL DDL 离线生成、psycopg 3.2.12 加载、Compose 配置校验及依赖锁离线一致性检查通过。
- 2026-11-08 已由本机终端执行验证脚本，当前会话读取 `.local/postgresql-verification.log` 核对：实际引擎为 `postgresql`，版本 `0001_learning_workflow`；`.local/integration.db` 的 20 张业务表全部导入并逐行核对一致，含 4 个用户、19 道题、18 次作答、9 个任务及 2 份资料。原 SQLite 与一致性备份保留，不将个人数据或完整日志提交 Git。
- 在独立 `aristotle_test` 数据库的随机 schema 上实跑集成测试：**50 passed, 1 warning in 21.42s**。警告为现有 FastAPI/Starlette TestClient 的 httpx 弃用提示。已通过的覆盖包含真实 PostgreSQL 上的外键、迁移与模型一致性、旧库导入/回滚、序列续号、API 学习闭环、并发幂等和审核；此结果为本机验证，不等同于 GitHub CI 或正式负载验收。
- 当前会话依然无法直接访问 Docker/socket；本轮未启动或切换常驻前后端进程，未完成浏览器实机验证。应用默认连接已改为 PostgreSQL，实际页面体验需按第 3 节启动后端并核对 `/health`，前端连接同一端口。
- 应用仍保留单进程的模拟任务/配额锁；本次不承诺多 worker 的配额原子性，也未接入 pgvector、真实 PDF 或 LLM。

参考：[SQLAlchemy psycopg 方言](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.psycopg)、[Alembic 迁移](https://alembic.sqlalchemy.org/en/latest/tutorial.html)、[PostgreSQL 官方容器](https://hub.docker.com/_/postgres)。

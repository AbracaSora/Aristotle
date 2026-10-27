# Aristotle 408 后端原型

Python 3.12 + FastAPI + Pydantic 2 + SQLAlchemy 2.0 + SQLite。依赖在仓库根目录的 `pyproject.toml` / `uv.lock` 管理。

这是可运行的后端设计原型：支持学生账号隔离、版本化知识图、分阶段诊断、规则推荐、任务作答与持久化、文字资料确认/删除，以及题目候选标注与人工审核。真实 LLM、PDF、正式知识空间模型、备份轮换和前端 Vue 联调尚未实现。

## 启动

在仓库根目录执行：

```bash
uv sync --locked --python 3.12
uv run python -m aristotle_backend.seed --demo
uv run uvicorn aristotle_backend.app:create_app --factory --host 127.0.0.1 --port 8018
```

- 后端工作台：<http://127.0.0.1:8018/demo>
- Swagger：<http://127.0.0.1:8018/docs>
- OpenAPI：<http://127.0.0.1:8018/openapi.json>
- 健康检查：<http://127.0.0.1:8018/health>

初始化是显式、可重复执行的命令；数据库已有用户或知识图时跳过，不覆盖数据。服务启动只建表，不自动创建演示账号。默认数据库为仓库 `.local/aristotle.db`，重启保留内容；不要将其或任何真实资料提交 Git。

演示账号为 `student1`、`student2`、`editor`，初始密码均为 `demo-password`。首次初始化前可用环境变量 `ARISTOTLE_DEMO_PASSWORD` 改变演示密码；后续改变变量不会修改已建账号。演示账号只用于本地，不用于对外试用部署。

如本机默认缓存无写权限，可在 uv 命令前加 `UV_CACHE_DIR=.local/uv-cache`。`.env.example` 仅说明可配置变量，程序不自动加载 `.env`。

## 五分钟演示

1. 打开 `/demo`，登录 `student1`，请求推荐。先完成“线性结构基础”的三道记忆题。
2. 三题全对后刷新知识状态，基础显示“初步掌握”，下一次推荐转向“栈的概念”。单题答对不会直接解锁先修。
3. 完成三道栈理解题，再请求栈操作应用关卡，之后可推荐分析题；每次提交都由服务端判分和存储。
4. 切换 `student2`，确认记录和资料从空状态开始；切回 `student1`，服务端历史仍在。
5. 添加文字讲义，手动确认知识点关联；取消关联或删除后，后续及历史任务不再显示其原文。
6. 切换 `editor`，保存一个新题目版本、录入候选、核验答案解析并批准。候选阶段学生不能获得该题；批准后才能分配。

Swagger 使用方式：先调用 `auth/login`，复制响应中的 `access_token`，点右上角 Authorize 输入令牌，再调用学生或维护者接口。Swagger UI 的静态资源由默认 CDN 加载；离线仍可使用无外部依赖的 `/demo` 和 `/openapi.json`。

演示种子包含 3 个知识点、12 道自编题，题目 `dataset=demo-seed`；审核记录是明确标记的流程夹具，**不表示正式双人标注或独立内容审核已完成**。所有真实新增候选都必须由维护者显式审核。

## 检查

```bash
uv run ruff check code/backend code/core_engine tests
uv run ruff format --check code/backend code/core_engine tests
uv run pytest -q
```

测试使用独立临时 SQLite 文件，不接触本地演示库或真实外部模型。CI 配置在 `.github/workflows/backend.yml`；尚未推送，因此不能声称 GitHub CI 已通过。

## 文档

- [后端技术方案](../../docs/software/backend_technical_proposal.md)
- [API 联调约定](../../docs/software/backend_api.md)
- [规则基线](../../docs/algorithm/baseline.md)
- [原型验证记录](../../docs/software/backend_validation.md)

## 运行限制

当前面向单进程、本地演示；尚无登录限流、正式账号开通、HTTPS 部署或完整数据库迁移。首版建表使用 `create_all`，不能用于演进已有数据库结构。进入对外试用前需补 Alembic 迁移、PostgreSQL 验证、限流、密钥和备份管理、恢复演练及完整 AC/NFR 验收。

SQLite 在线备份可使用其 backup 命令；应另行制定备份权限、保留期和删除记录重放方案。本原型只保证资料从业务查询和当前在线字段中移除，尚未验证 SQLite 空闲页、WAL 或历史备份的安全擦除。

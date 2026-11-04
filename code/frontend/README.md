# Aristotle 408 学习端

Vue 3 + TypeScript + Vite，沿用 Naive UI、Lucide 图标和绿色界面。学习端已对接后端 API：登录、知识状态、推荐关卡、服务端判分、学习记录和文字讲义均使用服务端数据。

## 启动

先在仓库根目录启动后端：

```bash
uv sync --locked --python 3.12
uv run python -m aristotle_backend.seed --demo --design-flow
uv run uvicorn aristotle_backend.app:create_app --factory --host 127.0.0.1 --port 8018
```

另开终端，进入 `code/frontend`：

```bash
npm ci --ignore-scripts --no-audit --no-fund
npm run dev
```

打开 <http://localhost:5173>。Vite 把 `/api` 转发到 `http://127.0.0.1:8018`，并把维护者入口 `/backend-demo` 转发到后端工作台。`npm run preview` 采用同样的代理设置；正式部署需由反向代理提供对应路由，不能把静态 dist 单独放到不支持 API 路由的服务器后直接视为部署完成。

演示账号：`student1`、`student2`，密码 `demo-password`；`editor` 为内容维护者，登录后提供管理工作台入口。若初始化时自定义了演示密码，应使用当时设置的密码。不要将演示账号用于正式开放试用。

如需更换后端地址，可复制 `.env.example` 到 `.env.local` 后修改 `ARISTOTLE_BACKEND_URL`，重启 Vite；或在命令前设置环境变量。单独部署的 API 可配置 `VITE_API_BASE_URL`，并在后端明确允许对应前端来源。这里不放任何模型密钥。

## 数据与错误处理

- 服务端负责题目选择、判分、知识状态和业务存储，前端不包含硬编码答案或本地判分。
- sessionStorage 只保存当前标签页的会话令牌和按用户区分的当前任务 ID；刷新后重新验证会话并从服务端读取任务。无法写 sessionStorage 时可继续使用内存会话，刷新需重新登录。
- 不读取、不上传也不删除旧 `aristotle-demo-*` localStorage 数据；旧本地演示成绩不混入服务端统计。
- 同一次作答的请求失败后复用提交编号与原答案；结果未确认时锁定改选，允许重试。服务端双唯一约束最终防止重复计分。
- 保存成功但统计读取失败时保留已保存解析并明确提示刷新。资料变更成功后才更新界面；失败时不显示虚假的“已确认”。
- 账号切换和会话失效清空内存业务视图，重新加载该账号的数据。
- 学习记录按页加载，累计计数来自后端 total/correct_total，不把当前页长度当作累计数据。

## 验证

```bash
npm test
npm run build
```

`npm test` 先检查测试环境类型，再运行 Vitest；测试覆盖丢失响应重试、原答案保护、保存与统计失败的区分、账号切换隔离、刷新恢复、会话失效和资料更新失败。`npm run build` 检查 Vue TypeScript 并构建 dist。

Vitest 只发现 `src/__tests__` 中的 `.test.ts` / `.spec.ts`，并显式排除 `tests/e2e`。Playwright 独立运行：

```bash
npx playwright install chromium
npm run test:e2e
```

默认从 PATH 使用 `uv run --locked python`，为本轮测试新建临时数据库、初始化演示数据，在 `127.0.0.1:8021` 启动后端、`127.0.0.1:5180` 启动前端，结束后清理临时数据库。不会修改日常开发数据库。若没有 uv，会尝试 PATH 中的 `python3` / `python`；该 Python 需先在仓库根目录执行 `python -m pip install -e .` 安装后端依赖。

| 环境变量 | 用途 |
| --- | --- |
| `ARISTOTLE_E2E_PYTHON` | 指定已安装后端的 Python 可执行文件，例如 `/path/to/Aristotle/.venv/bin/python`（建议使用绝对路径）；设置后不使用 uv |
| `ARISTOTLE_E2E_BASE_URL` | 前端来源地址，默认 `http://127.0.0.1:5180` |
| `ARISTOTLE_E2E_BACKEND_URL` | 后端来源地址，默认 `http://127.0.0.1:8021`；自动启动时同时用作代理目标和绑定地址 |
| `ARISTOTLE_E2E_REUSE_SERVER` | `1` 复用已有服务；`0` 禁止复用；默认仅在非 CI 环境复用 |
| `ARISTOTLE_E2E_SKIP_WEBSERVER` | `1` 完全关闭自动启动，直接连接外部前端 |

例如更换端口：

```bash
ARISTOTLE_E2E_BASE_URL=http://127.0.0.1:5185 \
ARISTOTLE_E2E_BACKEND_URL=http://127.0.0.1:8025 npm run test:e2e
```

若环境禁止绑定端口，可预先在允许的环境启动服务，再运行：

```bash
ARISTOTLE_E2E_SKIP_WEBSERVER=1 \
ARISTOTLE_E2E_BASE_URL=http://127.0.0.1:5185 npm run test:e2e
```

复用的前后端必须匹配，前端需自行将 `/api` 代理到该后端。外部服务使用专门的测试数据库，并先完成 `--demo --design-flow` 初始化；学生 `student1` 应为尚未选择范围的干净账号。测试会保存演示作答和任务。若自定义种子密码，测试进程也需设置相同的 `ARISTOTLE_DEMO_PASSWORD`。

浏览器回归覆盖管理角色登录、刷新、品牌导航和账号切换，以及学生导入禁用、诊断期间的知识点任务限制、完整分段作答和指定知识点请求。后端要求先完成初始诊断，并禁止在诊断进行中生成学习任务；知识地图会明确提示并禁用任务按钮，不会隐式打开其他知识点的诊断。

测试依赖的 Node 类型配置与浏览器代码配置分开，CI 使用 Node 22。浏览器实测及后端验证见 [联调记录](../../docs/software/frontend_backend_integration.md)。

## 已知边界

当前为局部数据结构演示内容，真实 PDF/LLM 仍未接入；正式诊断效度、内容质量、学习收益及非功能需求尚未验收。范围、跳过/更换、资料回退/复测和学生报错已补齐，详见下述更新。

## 设计对齐原型（2026-10-28）

新增范围与分段诊断、任务生命周期、资料复习与独立复测、导入片段确认、mock 标注任务与人工审核、纠错和系统管理。使用 `--design-flow` 显式增量初始化。管理员 admin 使用演示初始化密码。实现及 mock/501 边界、端到端运行步骤见 [原设计对齐流程](../../docs/software/design_aligned_workflow.md)。

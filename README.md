# Marlow

[![fake-eval](https://github.com/lhs1695/marlow/actions/workflows/fake-eval.yml/badge.svg)](https://github.com/lhs1695/marlow/actions/workflows/fake-eval.yml)

个人 PoC：内部 IT 工单同事（模拟数据，非某公司线上系统）。L1 用自然语言调查 / 关单；权限变更须管理员审批。通过条件是**工单库 + 审计终态**，不是模型输出像成功。

## 开发（venv / uv，日常默认）

环境：Python 3.12，包管理用 [uv](https://docs.astral.sh/uv/)。无 API Key 即可。

```bash
uv sync
uv run pytest
uv run python -m marlow.demo --case 1
uv run python -m marlow.web
```

打开 `http://127.0.0.1:8000/`。GitHub Actions 同一套 Fake（`.github/workflows/fake-eval.yml`）。仓库 Secrets **不配**模型 Key。

密钥只放本地 `.env`（不进 git）。真模型可选：`uv sync --extra llm` 后设 `OPENAI_API_KEY`（可设 `OPENAI_BASE_URL` / `MARLOW_CHAT_MODEL`），`uv run python -m marlow.demo --case 2 --real`。缺 Key 时 `--real` 自动 Fake。真模型报告写入 `evals/live/reports/`（gitignore），不进 CI。

手册钉 **Grafana 10.4**（文档取自 git tag `v10.4.3`，获取日期 **2026-09-07**），原文在 `handbook/grafana-10.4/`。CI / 默认 `search_kb` 对切片做固定检索夹具，**不打**真实 Embedding。本地可选建 Chroma 目录（gitignored）：

```bash
uv run python -m marlow.kb --persist chroma
# 真 Embedding（需 OPENAI_API_KEY，可设 OPENAI_BASE_URL）：
uv sync --extra embeddings
uv run python -m marlow.kb --persist chroma --real
```

## Compose 演示（不是日常必经）

本机 Docker Desktop。一容器：Web + SQLite 卷 + Chroma 卷。无 Key，Fake。首次 `up` 会用哈希向量建手册索引（较慢属正常）。

```bash
docker compose up --build
```

打开 `http://127.0.0.1:8000/`。停：`docker compose down`。清卷：`docker compose down -v`。

Fake 五段日常仍用本机 venv（不写 Compose 卷里的库）：

```bash
uv run python -m marlow.demo --case 1
```

## 规格

完整设计与分阶段计划在本机简历工作区（实现仓不复制全文）：

- [marlow.md](file:///D:/workspace/面试和简历项目/docs/marlow.md) — 产品规格
- [marlow-评测.md](file:///D:/workspace/面试和简历项目/docs/marlow-评测.md) — 评测类型与断言
- [marlow 计划](file:///D:/workspace/面试和简历项目/计划/marlow.md) — 分阶段施工

本地路径：`D:\workspace\面试和简历项目\docs\marlow.md`

## 阶段

当前：**阶段 11** — 对照规格收口。日常仍 `uv sync` / `uv run pytest`。无 Key 跑 Fake 评测与演示五段。

登录后四页 + 对话条（对话是同步收口；步骤流见 CLI 事件或 `GET /api/runs/{id}/events`）。`data-testid` 见 `src/marlow/web/testids.py`。

## 模块（面试可指到文件）

按变化轴分，不是一节点一包：

| 会变的东西 | 落点 |
| --- | --- |
| 工单 / 权限表与种子 | `src/marlow/models.py` `db.py` `seed.py` |
| 写 entitlements | `src/marlow/gateway.py`（Web / MCP / 工具同一函数） |
| 六个工具短码 | `src/marlow/tools/`；MCP 薄壳 `ticket_mcp.py` |
| 四个 Skill 骨架 | `src/marlow/skills/` |
| Run 状态机 | `src/marlow/engine.py`；Fake `fake.py` |
| 真模型适配 | `src/marlow/llm.py` |
| 手册切片 / 版本 | `src/marlow/kb/`；CI 夹具不打 Embedding |
| Session 与四页 | `src/marlow/web/` |
| 冻结 Fake 评测 | `tests/test_eval_frozen.py` |

权检不在 prompt：角色来自 Cookie Session + `employees.role`，网关按 actor 落库。Observation 一律 `untrusted`。

演示账号（角色只来自服务端 Session，忽略 `?role=`）：

- L1：`l1` / `l1-demo`
- 管理员：`admin` / `admin-demo`

Inspector / stdio（可选）：`uv run python -m marlow.ticket_mcp`

## Keyline（浏览器通道评测）

测四页 Web 会不会比 MCP 更能改权限。通过条件是 URL/DOM **且** 同一张审批表、同一套会话角色，不是页面看起来绿。无 API Key、无 LLM judge。

Chromium 与 pip 包分开装一次；评测夹具会自己拉起临时 Web（内存 SQLite），不要对着另开的 `python -m marlow.web` 跑（那是另一套库）。

```bash
uv run playwright install chromium
uv run pytest evals/keyline
```

GitHub Actions（`fake-eval` 的 `keyline` job）同一条：`uv run playwright install --with-deps chromium`，再 `uv run pytest evals/keyline`。夹具自起临时 Web。装不起 Chromium 则 job 失败，不会 skip / continue-on-error 当绿。

日常主线仍是 `uv run pytest`（只收 `tests/`）。Keyline 是另一次门禁（本地与 GHA）。跑完看 `evals/keyline/last_run.md`（gitignore）：`privilege_fail=yes` 的行是提权拦截条。Playwright 绿但没查表不算过。纪律见 `evals/keyline/AGENTS.md`。

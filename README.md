# Marlow

[![fake-eval](https://github.com/lhs1695/marlow/actions/workflows/fake-eval.yml/badge.svg)](https://github.com/lhs1695/marlow/actions/workflows/fake-eval.yml)

Marlow 是一个内部 IT 工单 **Agent** 的个人 PoC。仓里有模拟服务台：工单、员工、Grafana 权限。一线用自然语言查单、关单；改别人权限必须人批。做成了看工单状态和审计。

你登录之后能看到工单列表、工单详情、对话条；管理员多一页审批队列。在对话里用自然语言办事，例如：

- 「Grafana 登录有问题，帮我看看」——没带工单号，会先问清楚。
- 「请调查 INC-1001 并关单」——查工单、搜钉死版本的 Grafana 手册；规则过后再问 `assess_evidence`，模型只有否决权。通过才写评论并关单。
- 「读取 INC-1005 的资产配置」——下游超时，Run 按故障收口，不装成已经改好了。
- 「工单 CHG-2004 申请给 emp-007 加 Grafana Editor」——一线只出草案，Run 停在 `waiting_approval`；管理员批准后同一 Run 续跑，网关才写权限。
- 「在 CHG-2004 上直接改权限」——一线被拒，权限表不变。

这五段也是 `python -m marlow.demo --case 1` … `--case 5`。无 API Key 即可跑（脚本化 Fake）；有 Key 时 `--real` 走真模型，缺 Key 会退回 Fake。

## 亮点

- **编排自写。** FastAPI + 自写 Run 状态机。写员工权限都进审批网关：一线出草案，管理员才落库。登录角色来自 Cookie Session，页面上的 `?role=` 改不了。手册检索和工单评论标成不可信输入。
- **提交只入队。** `POST /api/runs` 返回 202；步骤落库即推 SSE，断线用 `Last-Event-ID` 续传。取消落库，在步与步之间生效。
- **审批是停留态。** Run 真停在 `waiting_approval`；管理员批准后同一 Run、原来的一线角色续跑。
- **关单规则先过，模型只否决。** 评测查工单库和审计。本机实测（2026-09-11）：`uv run pytest` **165 passed**；同仓 Keyline（Playwright）**16 条 / 34 passed**，证明点页面不能比调工具更特权。Keyline 不进默认 `pytest`。

Python 3.12，包管理用 [uv](https://docs.astral.sh/uv/)。

## 跑起来

```bash
uv sync
uv run pytest
uv run python -m marlow.demo --case 1
uv run python -m marlow.web
```

打开 `http://127.0.0.1:8000/`：

- 一线：`l1` / `l1-demo`（只见自己队列里的工单）
- 管理员：`admin` / `admin-demo`（能进审批队列）

角色只来自这次登录，忽略 URL 上的 `?role=`。GitHub Actions（`.github/workflows/fake-eval.yml`）跑 Fake `pytest`，另有 `keyline` job；仓库 Secrets 不配模型 Key。

## Run、SSE、取消

对话或 `POST /api/runs` 只建 Run 并入队（`runner.py` 单 worker、并发 1），立刻返回 **202** 和 `run_id` / `request_id` / `trace_id`。终态读 `GET /api/runs/{id}`，不要在创建响应里等 `outcome`。

步骤落库即提交。`_emit` 经 contextvar 回调 **实时推送**（不是等 Run 结束再读库回放）。页面用浏览器原生 `EventSource` 订 `GET /api/runs/{id}/events`；每条事件带 `id`，断线后用 `Last-Event-ID` 续传。关掉页面**不会**取消 Run。

取消：`POST /api/runs/{id}/cancel`（页面上也有按钮）。只把 `cancel_requested` 落库，在步与步之间生效。

## HITL 续跑

一线走变更 Skill 时，Run **停在** `waiting_approval` 并写 checkpoint，不把这次请求收成终态。管理员在审批页（或 `POST /api/entitlements`）批准后，乐观锁认领同一 `run_id` 再入队，用**原 L1 角色**续跑，刹车计数从 checkpoint 继承。网关 Observation 标 `internal_gateway`；权限仍只由网关写入。

## 关单前的否决

关单 Skill 先跑规则（工单号、引用、手册版本、队列）。规则不过直接退回，不调模型。规则过了才走独立 schema `assess_evidence`（`{sufficient, missing, reason}`，不挤进 `emit_action`）。模型只有否决权：判不充分则不关单、继续调查；判充分也不能越过规则。模型不可用时 fail-open（按规则走）。`max_reflect_rejections=2`，避免一直判否拖到 MaxSteps。

## 工具传输（进程内 / stdio MCP）

Run 默认进程内调工具（`InProcessToolClient`）。要切 MCP stdio：

```bash
# 必须是文件库；内存 SQLite 子进程看不见
export MARLOW_DATABASE_URL=sqlite:///data/marlow.db
export MARLOW_TOOL_CLIENT=stdio
uv run python -m marlow.web
```

Inspector / 单独起服务端：`uv run python -m marlow.ticket_mcp`。对照评测（调查 / `close_success`）里 `tickets` 终态与 `audit_events`（除 `created_at`）逐字段相等。

两条路径**不是**完全等价。已知差异：

1. `FaultHooks` 过不去 stdio，故障 / 超时注入仍走进程内。
2. `search_kb` 不吃 session，子进程自建检索；两侧夹具一致才命中一致。
3. 内存 SQLite 不能给 stdio 用（对照测试用临时文件库）。
4. **MCP 只包 `execute_tool` 那一层**；Skill 骨架对库的直接写（关单改 `tickets.status`、读 `MemoryNote`）仍在 engine 的 session 里。不是「整个 Agent 走 MCP」。
5. stdio 的 Observation 经 `structured_content` JSON 往返重建，进程内是同一对象。
6. stdio 要起 Python 子进程，故进程级单例，不每 Run 起一次。

## 目录

| 会变的东西 | 落点 |
| --- | --- |
| 工单 / 权限表与种子 | `src/marlow/models.py` `db.py` `seed.py` |
| 写员工权限 | `src/marlow/gateway.py` |
| 查单 / 搜手册 / 读资产 / 写评论 / 改权限 | `src/marlow/tools/`；MCP 薄壳 `ticket_mcp.py` |
| 工具传输 | `src/marlow/tool_client.py`（进程内默认；stdio 单例可切） |
| Skill 骨架 | `src/marlow/skills/` |
| 关单证据否决 | `src/marlow/evidence.py` |
| Run 状态机 | `src/marlow/engine.py`；Fake `fake.py`；worker `runner.py`（并发度 1，事件内存 fan-out） |
| 真模型适配 | `src/marlow/llm.py` |
| 手册切片（Grafana 10.4） | `src/marlow/kb/`；CI 夹具不打 Embedding |
| 登录与四页 | `src/marlow/web/`（`data-testid`：`testids.py`） |
| 冻结 Fake 评测 | `tests/test_eval_frozen.py` |

## 真模型（可选）

密钥只放本地 `.env`（对照 `.env.example`），host 不进源代码。演示档案是 xAI 聊天 + Jina 向量。`uv run pytest` 和 CI 仍 Fake。

```bash
uv sync --extra llm
uv run python -m marlow.demo --case 2 --real
```

缺聊天 Key 时 `--real` 自动 Fake。本机可再跑 `uv run python -m marlow.live`（case 2 重复收集），报告在 `evals/live/reports/`（gitignore），不进 CI、不进默认 `pytest`。字段与环境变量见 `evals/live/README.md`。不要沿用一期报告里的延迟数字。

手册钉 Grafana 10.4（git tag `v10.4.3`，获取日期 2026-09-07），原文在 `handbook/grafana-10.4/`。CI / 默认 `search_kb` 用固定检索夹具。本地 Chroma（gitignored）不要混：哈希用 `chroma/`，真向量用 `chroma-jina/`。

```bash
uv run python -m marlow.kb --persist chroma
uv sync --extra llm
uv run python -m marlow.kb --persist chroma-jina --real
# 检索同一目录：MARLOW_CHROMA_DIR=chroma-jina MARLOW_KB_EMBEDDINGS=real
```

无 `MARLOW_KB_EMBEDDINGS` 时建库和检索都是哈希夹具；真向量检索须设 `MARLOW_KB_EMBEDDINGS=real`。

## Compose（可选）

本机 Docker Desktop。一容器：Web + SQLite 卷 + Chroma 卷。无 Key，Fake。首次 `up` 会用哈希向量建手册索引（较慢属正常）。上面的 Fake 五段仍用本机 venv，不要写进 Compose 卷里的库。

```bash
docker compose up --build
```

打开 `http://127.0.0.1:8000/`。停：`docker compose down`。清卷：`docker compose down -v`。

## Keyline（可选）

工具拦住的变更，点页面不能绕过。通过条件是 URL/DOM **且**同一张审批表、同一套会话角色。无 API Key、无 LLM judge。夹具自起临时 Web（内存 SQLite），不要对着另开的 `python -m marlow.web` 跑。

```bash
uv run playwright install chromium
uv run pytest evals/keyline
```

日常主线仍是 `uv run pytest`（只收 `tests/`）。GHA 的 `keyline` job：`uv run playwright install --with-deps chromium`，再同一条 pytest。装不起 Chromium 则 job 失败，不会 skip 当绿。跑完看 `evals/keyline/last_run.md`（gitignore）：`privilege_fail=yes` 的行是提权拦截条。

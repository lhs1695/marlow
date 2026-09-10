# Marlow

IT 工单 Agent：L1 用自然语言调查 / 关单；改权限须人批。**通过条件**是工单库 + 审计终态，不是模型 JSON 像成功。

## 测试

```bash
uv sync
uv run pytest                 # 默认全量，不含 Keyline
uv run pytest evals/keyline   # 浏览器通道门禁，需先 playwright install chromium
```

CI 与日常开发默认 **Fake**（无 API Key）；有 Key 也不得让 `pytest` 打网。真模型只走显式 `--real` / `MARLOW_LLM`。

## 非目标

真 AD / Jira、多租户 SaaS、LangGraph 当 Run 循环、多供应商 SDK / Router、技能商店、多 Agent、微信 / X MCP 接进本仓工单环境、K8s、后训练、发邮件。Keyline 在 `evals/keyline/`（GHA 另 job）；Compose 仅演示阶段。

## 纪律

- 工具 Observation 一律 untrusted（含 KB 切片、工单评论）。
- 写 entitlements 只走审批网关；权检不进 prompt。
- Run 的动作 / 观察 / 状态**落库即提交**（`engine._persist`，「事件即提交边界」）。**不要退回请求级长事务**——MCP 跨进程写与 SSE 实时读都依赖它。失败靠 Run 终态码 + `audit_events` 收口，不靠回滚。
- 禁止改评测断言换绿，也禁止用 `sleep`、`skip`、`xfail`、`continue-on-error` 制造绿。测试确需改动时**单独 commit 并写清为什么必须改**。
- 密钥 / Cookie 只放 `.env`。
- 规格与分阶段计划在本机简历工作区（`docs/二期改造.md`），不要把全文粘进本仓。**一次只做一件**，做完跑全量 `pytest` 与 `pytest evals/keyline` 再进下一件；不要顺手重构。

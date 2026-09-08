# Marlow

IT 工单 Agent：L1 用自然语言调查 / 关单；改权限须人批。**通过条件**是工单库 + 审计终态，不是模型 JSON 像成功。

## 测试

```bash
uv sync
uv run pytest
```

CI 与日常开发默认 **Fake**（无 API Key）；有 Key 也不得让 `pytest` 打网。

## 非目标

真 AD / Jira、多租户 SaaS、LangGraph 当 Run 循环、多供应商 SDK / Router、技能商店、多 Agent、微信 / X MCP 接进本仓工单环境、K8s、后训练、发邮件。Keyline 在 `evals/keyline/`（GHA 另 job）；Compose 仅演示阶段。

## 纪律

- 工具 Observation 一律 untrusted（含 KB 切片、工单评论）。
- 禁止改评测断言换绿；密钥 / Cookie 只放 `.env`。
- 写 entitlements 只走审批网关；权检不进 prompt。
- 规格与分阶段计划在本机简历工作区，不要把全文粘进本仓。

# Keyline

双通道权限评测：工具拦住的变更，点页面不能绕过。**通过条件**是 URL/DOM **且**同一张审批表、同一套会话角色，不是页面看起来绿。

本目录是 Keyline 代码与宪法。Git 与 venv 跟 Marlow 仓共用，不另开远程。不要把仓库根 `AGENTS.md` 扩成长文。

## 测试

```bash
uv run playwright install chromium
uv run pytest evals/keyline
```

评测夹具自起临时 Web，不要另开 `python -m marlow.web`。无 API Key、无 LLM judge。Playwright 全绿但没查表，不算过。

## 非目标

通用 Computer Use、一期 LLM judge、Inspect Docker / K8s sandbox、独立产品名与独立仓、用 browser-use 当唯一执行器、与 Stave 合成一个平台、把 Keyline 做成「又能点完工单」的 UI 单测集。

## 纪律

- 通过 = DOM/URL 断言 **且** 库表（`approvals` / `entitlements` / session 角色）。禁止只断言页面。
- 禁止为绿去加未鉴权写接口，或让评测进程比 L1 更特权。
- 禁止改 Marlow 测试 / 网关迁就评测。发现页面能改权限、MCP 不能：停 Keyline，先修 Marlow。
- 选择器只绑 `data-testid`，禁止用可见中文当唯一选择器。
- 规格与分阶段计划在本机简历工作区，不要把全文粘进本仓或 Marlow 根宪法。

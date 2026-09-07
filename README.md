# Marlow

个人 PoC：内部 IT 工单同事（模拟数据，非某公司线上系统）。L1 用自然语言调查 / 关单；权限变更须管理员审批。通过条件是**工单库 + 审计终态**，不是模型输出像成功。

## 开发

环境：Python 3.12，包管理用 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync
pytest
```

无 API Key 时用 Fake Provider 跑通评测；密钥放本地 `.env`（不进 git）。

手册钉 **Grafana 10.4**（文档取自 git tag `v10.4.3`，获取日期 **2026-09-07**），原文在 `handbook/grafana-10.4/`。CI / 默认 `search_kb` 对切片做固定检索夹具，**不打**真实 Embedding。本地可选建 Chroma 目录（gitignored）：

```bash
uv run python -m marlow.kb --persist chroma
# 真 Embedding（需 OPENAI_API_KEY，可设 OPENAI_BASE_URL）：
uv sync --extra embeddings
uv run python -m marlow.kb --persist chroma --real
```

## 规格

完整设计与分阶段计划在本机简历工作区（实现仓不复制全文）：

- [marlow.md](file:///D:/workspace/面试和简历项目/docs/marlow.md) — 产品规格
- [marlow-评测.md](file:///D:/workspace/面试和简历项目/docs/marlow-评测.md) — 评测类型与断言
- [marlow 计划](file:///D:/workspace/面试和简历项目/计划/marlow.md) — 分阶段施工

本地路径：`D:\workspace\面试和简历项目\docs\marlow.md`

## 阶段

当前：**阶段 5** — 手册切片 + 引用校验；写 entitlements 仍只走审批网关。CI 默认 Fake、无真实 Embedding。

```bash
python -m marlow.demo --case 1
```

Inspector / stdio（可选）：`python -m marlow.ticket_mcp`

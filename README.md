# Marlow

个人 PoC：内部 IT 工单同事（模拟数据，非某公司线上系统）。L1 用自然语言调查 / 关单；权限变更须管理员审批。通过条件是**工单库 + 审计终态**，不是模型输出像成功。

## 开发

环境：Python 3.12，包管理用 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync
pytest
```

无 API Key 时后续阶段用 Fake Provider 跑通评测；密钥放本地 `.env`（不进 git）。

## 规格

完整设计与分阶段计划在本机简历工作区（实现仓不复制全文）：

- [marlow.md](file:///D:/workspace/面试和简历项目/docs/marlow.md) — 产品规格
- [marlow-评测.md](file:///D:/workspace/面试和简历项目/docs/marlow-评测.md) — 评测类型与断言
- [marlow 计划](file:///D:/workspace/面试和简历项目/计划/marlow.md) — 分阶段施工

本地路径：`D:\workspace\面试和简历项目\docs\marlow.md`

## 阶段

当前：**阶段 1** — 业务库 + 种子 + 审批网关（无模型）。写 entitlements 只走 `apply_entitlement_change`。

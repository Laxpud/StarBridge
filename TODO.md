# 当前工作

## 三端插件、会话接入与运行简化

实施中：第一部分“调整会话与文件位置”已完成代码改造，真实 GUI 接入与保存行为尚未实测。后续按计划简化状态、读写与执行链路，再交付 Codex、Claude Code 和 DSH 三端插件。

后续实施任务与勾选状态统一维护在 [Plan](docs/plans/plan-2026-11-03-14-23.md)，设计见 [Spec](docs/specs/spec-2026-11-03-14-23.md) 和 [ADR 0002](docs/adr/0002-plugins-sessions-and-storage.md)。其他候选继续保留在[路线图](docs/roadmap.md)，不自动纳入本轮范围。

## 已有工作记录

### 分发与 Harness 接入

已完成 Python 发行包、代表性通用 Skill 和 Codex、Claude Code、DSH 三端项目级安装接入的本地交付。此前采用程序、MCP 配置和 Skill 分别安装的方式，已有任务记录见[原分发计划](docs/plans/plan-2026-11-01-14-42.md#实施顺序与交付结果)，具体结果与边界见[分发说明](docs/distribution.md#验收状态)。

该轮调整后的范围仅检查三端安装接入，不向模型发送信息执行任务；此前模型与 STAR 工作流的历史记录仍保留在分发说明中。外部发布尚未执行，仍需另行授权。

旧安装方式的后续安排已由 ADR 0002 替代，不再作为并列实施入口。已有 STAR 能力与限制见[运行时发现与写入](docs/runtime-discovery.md)。

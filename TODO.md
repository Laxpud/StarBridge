# 当前工作

## 三端插件、会话接入与运行简化

实施中：前两部分及第三部分的执行层改造已完成；统一对象与属性接口、旧入口迁移和三端插件交付仍待完成。真实 GUI、保存、新写入链路及缓存辅助类的 STAR 宏加载尚未实测，具体边界见[会话说明](docs/bridge-session.md)。

后续实施任务与勾选状态统一维护在 [Plan](docs/plans/plan-2026-11-03-14-23.md)，设计见 [Spec](docs/specs/spec-2026-11-03-14-23.md) 和 [ADR 0002](docs/adr/0002-plugins-sessions-and-storage.md)。其他候选继续保留在[路线图](docs/roadmap.md)，不自动纳入本轮范围。

## 已有工作记录

### 分发与 Harness 接入

已完成 Python 发行包、代表性通用 Skill 和 Codex、Claude Code、DSH 三端项目级安装接入的本地交付。此前采用程序、MCP 配置和 Skill 分别安装的方式，已有任务记录见[原分发计划](docs/plans/plan-2026-11-01-14-42.md#实施顺序与交付结果)，具体结果与边界见[分发说明](docs/distribution.md#验收状态)。

该轮调整后的范围仅检查三端安装接入，不向模型发送信息执行任务；此前模型与 STAR 工作流的历史记录仍保留在分发说明中。外部发布尚未执行，仍需另行授权。

旧安装方式的后续安排已由 ADR 0002 替代，不再作为并列实施入口。已有 STAR 能力与限制见[运行时发现与写入](docs/runtime-discovery.md)。

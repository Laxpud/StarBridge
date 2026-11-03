# 路线图

[返回项目入口](README.cn.md)

## 已完成里程碑

<a id="运行时对象树与属性发现"></a>
<a id="通用规则驱动的受控写入迁移"></a>

- [运行时对象树与属性发现、通用规则驱动的受控写入迁移](archive/milestone-2026-10-30-15-28-runtime-discovery-and-writes.md)
- [MCP 与共享 Core API](archive/milestone-2026-10-29-17-30-mcp.md)
- [版本目录与通用读写基础、代表性扩展及 2510 版本绑定](archive/milestone-2026-10-29-17-27-catalog-foundations.md)
- [Inspector 对象快照](archive/milestone-2026-10-28-15-29-inspector.md)
- [后台常驻会话与临时客户端](archive/milestone-2026-10-21-10-08-background-session.md)
- [文件 Bridge 原型](archive/milestone-2026-10-21-10-02-file-bridge.md)

## 已有工作记录

### 分发与 Harness 接入

Python 包、代表性 Skill 和三端项目级安装接入已完成本地交付，外部发布尚未执行。已有工作保留在[原分发计划](plans/plan-2026-11-01-14-42.md)与[分发说明](distribution.md#验收状态)中；分别安装程序、MCP 配置和 Skill 的后续安排已由 [ADR 0002](adr/0002-plugins-sessions-and-storage.md)调整。

## 当前里程碑

三端插件、会话接入与运行简化方案已确认，尚未实施。后续实施统一按[新 Plan](plans/plan-2026-11-03-14-23.md)推进，目标行为见 [Spec](specs/spec-2026-11-03-14-23.md)，当前入口见 [TODO](../TODO.md)。

本轮包括 Codex、Claude Code 和 DSH 插件、优先连接已有 STAR GUI／服务器、直接加载原算例、`.starbridge` 目录安排，以及状态、读写和执行链路的简化。GUI 接入不再另列未来任务；减少宏生成和客户端启动开销也由新 Plan 管理，不预设常驻 Java 适配器为独立交付项。

继续采用 [ADR 0001](adr/0001-runtime-discovery.md) 的运行时发现方向，版本资料和有效适配继续复用。按 [ADR 0002](adr/0002-plugins-sessions-and-storage.md)迁移已有能力后移除重复接口与结果转换，不长期维持多套原型格式。已实现的能力与限制见[运行时发现](runtime-discovery.md)。

## 后续里程碑

更多领域 Skills、其他值类型、版本和结构操作继续作为后续候选，按实际需求确定范围，不自动加入当前 Plan。

### Skills

已有 [starbridge-case-audit](../skills/starbridge-case-audit/SKILL.md) 只读算例审查 Skill 随三端插件交付。后续候选包括 `mesh-setup`、`overset-mesh`、`rotor-case`、`oge-case`、`nwse-case`、`vof-setup` 和 `solver-setup`，具体交付范围另行确定。

Skills 按已有能力分批推进：只读审查使用发现和读取能力，配置工作流使用相应写入能力，无需等待所有功能齐备。

Skills 通过对象树导航或属性搜索取得当前版本的实际对象和设置，组织检查顺序与业务工作流，并使用已提供的用户、项目及算例背景；持久化工作记忆另列 Backlog。对象 API 绑定和版本差异由 Bridge 的发现、规则与执行器维护，避免每个 Skill 重复维护 Java 调用或完整配置列表。

MCP 自身须能说明受支持任务的正确调用方式，Skill 不承担补齐接口说明的职责。记忆支持的个性化 Skill 生成保留为独立候选，不作为通用 Skills 的前置条件。

Tool 决定 Agent 能做什么，Skill 描述 Agent 如何完成工作。

<a id="目录覆盖扩展与版本演进"></a>
<a id="覆盖范围与版本验证"></a>

## 待扩展能力与版本

长期目标仍是覆盖算例本身的几何、网格、物理模型、边界条件、求解器、后处理和操作流程；STAR 客户端偏好及安装配置不在此范围。以下保留现有能力缺口，按实际需求扩展，不另立覆盖全部配置的任务。

| 范围 | 待扩展内容 |
|---|---|
| Mesh Controls | 其他网格控制的值类型、单位、范围及关联 |
| Boundary Parameters | 常量标量／向量之外的 Profile 方法、当前方法条件及切换关系 |
| Selected Physics Settings | 其他物性与求解设置、张量布局与方向、材料及多系数方法、模型依赖 |
| Simulation Operations | 块关系读取、块修改及结构操作 |
| 其他算例内设置 | 几何、表格、报告、监视器、场景等缺失值类型、查询谓词和操作语义 |

已有能力及限制统一见[运行时发现](runtime-discovery.md)、[目录修改](catalog-modifier.md)和[版本说明](catalog-versions.md)。新增类型和版本按实际缺口安排，当前简化工作不自动扩大支持范围。

---

设计依据见 [StarBridge 设计](../StarBridge.md)，参考实现与适用边界见[参考项目](references.md)。

## Backlog

### 网格与求解执行接口

保留网格生成和求解执行能力的目标，通过共享 Core 接入 MCP，使用独立于配置修改的执行入口。具体任务和运行控制方式另行确定，当前没有对外执行工具。

### 复杂结构操作

保留创建／删除、模型启停、方法切换、操作块修改和复杂查询等扩展方向，按实际任务确定具体操作及其影响。结构操作不合并为普通属性赋值。

### 持久化工作记忆

保留跨对话使用用户偏好、项目约定和算例背景的目标，具体存储与使用方式待讨论，不作为当前改造或通用 Skills 的前置条件。

### 基于记忆的个性化 Skill 生成

保留结合通用 Skill 与记忆生成个性化工作流的候选方向。具体生成和维护方式待讨论，暂不承诺完整的更新、停用和回退机制，也不扩展底层算例操作能力。已有设想见[生成路线](../StarBridge.md#个性化-skill-生成路线)。

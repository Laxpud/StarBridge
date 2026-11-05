# 路线图

[返回项目入口](README.cn.md)

## 已完成里程碑

- [三端插件、会话接入与运行简化](archive/milestone-2026-11-04-12-33-plugins-sessions-and-interface.md)

<a id="分发与-harness-接入"></a>

- [分发与 Harness 接入（本地交付）](archive/milestone-2026-11-03-18-17-distribution.md)

<a id="运行时对象树与属性发现"></a>
<a id="通用规则驱动的受控写入迁移"></a>

- [运行时对象树与属性发现、通用规则驱动的受控写入迁移](archive/milestone-2026-10-30-15-28-runtime-discovery-and-writes.md)
- [MCP 与共享 Core API](archive/milestone-2026-10-29-17-30-mcp.md)
- [版本目录与通用读写基础、代表性扩展及 2510 版本绑定](archive/milestone-2026-10-29-17-27-catalog-foundations.md)
- [Inspector 对象快照](archive/milestone-2026-10-28-15-29-inspector.md)
- [后台常驻会话与临时客户端](archive/milestone-2026-10-21-10-08-background-session.md)
- [文件 Bridge 原型](archive/milestone-2026-10-21-10-02-file-bridge.md)

## 当前里程碑

当前无进行中的里程碑；下列候选尚未启动。

## Backlog

以下均为尚未承诺的候选，不自动纳入当前里程碑。

### 运行验证与既有检查维护

后续可补齐真实 GUI 接入、保存、恢复和统一读写链路的运行证据；当前缺口及过时验收脚本见[验证边界](tech/bridge-session.md#验证边界)。检查脚本的维护与新增验证范围另行确定，历史安装结果不代替当前算例工作流验收。

### 区域运动绑定引用读取

价值：确认实际使用中遇到的读取缺口，作为后续排查依据。

待核实：区域的运动绑定引用是否能通过 MCP 读取。2026-11-02 用户反馈：实际使用时 AI 表示“MCP 当前无法读取区域的运动绑定引用”。目前仅记录该反馈，尚未复现或确认原因。

### 领域 Skills

价值：将已有读写能力组织成可复用的算例工作流。

已有 [starbridge-case-audit](../skills/starbridge-case-audit/SKILL.md) 只读算例审查 Skill 随三端插件交付。后续候选包括 `mesh-setup`、`overset-mesh`、`rotor-case`、`oge-case`、`nwse-case`、`vof-setup` 和 `solver-setup`，具体交付范围另行确定。

Skills 按已有能力分批推进：只读审查使用发现和读取能力，配置工作流使用相应写入能力，无需等待所有功能齐备。

工作流使用当前对象和值；API 绑定与版本差异由 Bridge 维护，MCP 自行提供完整调用说明。具体分工见[Skills 设计](archive/StarBridge.md#skills)。持久化记忆及个性化生成另列候选，不作为通用 Skills 的前置条件。

<a id="目录覆盖扩展与版本演进"></a>
<a id="覆盖范围与版本验证"></a>

### 待扩展能力与版本

价值：扩大可处理的算例配置和版本范围。范围遵循[项目定位](archive/StarBridge.md#项目定位)，以下能力按实际需求选择，不作为已经承诺的全覆盖任务。

| 范围 | 待扩展内容 |
|---|---|
| Mesh Controls | 其他网格控制的值类型、单位、范围及关联 |
| Boundary Parameters | 常量标量／向量之外的 Profile 方法、当前方法条件及切换关系 |
| Selected Physics Settings | 其他物性与求解设置、张量布局与方向、材料及多系数方法、模型依赖 |
| Simulation Operations | 块关系读取、块修改及结构操作 |
| 其他算例内设置 | 几何、表格、报告、监视器、场景等缺失值类型、查询谓词和操作语义 |

已有能力及限制统一见[运行时发现](tech/runtime-discovery.md)、[目录修改](tech/catalog-modifier.md)和[版本说明](tech/catalog-versions.md)。新增类型和版本按实际缺口安排，当前简化工作不自动扩大支持范围。

### Python 包与 Registry 发布

价值：提供固定发行版本与标准发现入口。

原分发计划的本地交付已结束，PyPI、发布 tag／Git Release 和 MCP Registry 尚未发布。准备情况见[分发说明](tech/distribution.md#发布准备)。后续发布范围与时机另行确认，不因归档旧计划或已有插件 Git 推送而自动执行。

### 网格与求解执行接口

价值：让 Agent 在配置完成后发起网格生成和求解。初步思路是通过共享 Core 接入 MCP，使用独立于配置修改的执行入口；具体任务和运行控制方式待确定。

### 复杂结构操作

价值：处理普通属性赋值无法表达的配置变化。候选包括创建／删除、模型启停、更多方法切换、操作块修改和复杂查询；按实际任务确定具体操作及其影响。

### 持久化工作记忆

价值：在跨对话工作中沿用用户偏好、项目约定和算例背景。设计边界见[工作记忆](archive/StarBridge.md#持久化工作记忆)；具体存储与使用方式待讨论，不作为当前改造或通用 Skills 的前置条件。

### 基于记忆的个性化 Skill 生成

价值：结合通用 Skill 和已有记忆形成个性化工作流。生成与维护方式待讨论，不预先承诺完整的更新、停用和回退机制，也不扩展底层操作能力；已有候选设计见[生成路线](archive/StarBridge.md#个性化-skill-生成路线)。

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

当前需求任务及交付状态见[当前工作](<../TODO.md>)；下列旧候选不自动成为下一阶段承诺。

## Backlog

下列原候选中已经具备的基础能力注明当前入口；其余仍未承诺，不自动纳入新任务。

### 运行验证与既有检查维护

GUI 接入、保存及特定恢复场景已取得真实运行证据；更广覆盖与过时验收脚本仍需另行确定维护范围，见[验证边界](<tech/bridge-session.md#验证边界>)。历史安装或局部任务结果不代替全部工作流验收。

### 区域运动绑定引用读取

价值：确认实际使用中遇到的读取缺口，作为后续排查依据。

待核实：区域的运动绑定引用是否能通过 MCP 读取。2026-11-02 用户反馈：实际使用时 AI 表示“MCP 当前无法读取区域的运动绑定引用”。目前仅记录该反馈，尚未复现或确认原因。

### 领域 Skills

价值：将已有读写能力组织成可复用的算例工作流。

已有 [starbridge-case-audit](../skills/starbridge-case-audit/SKILL.md) 只读算例审查 Skill 随三端插件交付。后续候选包括 `mesh-setup`、`overset-mesh`、`rotor-case`、`oge-case`、`nwse-case`、`vof-setup` 和 `solver-setup`，具体交付范围另行确定。

Skills 按已有能力分批推进：只读审查使用发现和读取能力，配置工作流使用相应写入能力，无需等待所有功能齐备。

工作流使用当前对象和值；API 绑定与版本差异由 Bridge 维护，MCP 自行提供完整调用说明。具体分工见[Skills 设计](archive/StarBridge.md#skills)。持久化工作记忆已提供独立接口；个性化生成仍为候选，不作为通用 Skills 的前置条件。

<a id="目录覆盖扩展与版本演进"></a>
<a id="覆盖范围与版本验证"></a>

### 待扩展能力与版本

价值：完善结构化便利接口及版本证据。范围遵循[当前需求](<../StarBridge.md>)；通用执行不以这些适配为能力上限，下表也不是必须逐项专门适配的清单，后续仍优先复用通用机制。

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

基础执行现已通过共享 Core 接入 MCP，并提供网格、求解、状态及导出现成方法；具体已实现范围见[通用执行](<tech/generic-execution.md#可直接使用的参数化方法>)。更细的运行控制按实际后续任务确定。

### 复杂结构操作

创建／删除、模型启停、方法切换、操作块修改和复杂查询可使用通用执行通道，不以普通属性接口为上限。后续候选是高频操作的参数化便利方法；具体操作及影响仍由实际任务确定，不因提供入口而自动取得修改授权。

### 持久化工作记忆

现已提供项目／用户范围的记录、检索和修订，保存场景、来源、实际效果、资料位置及可选参数化方法；使用边界见[工作记忆接口](<tech/generic-execution.md#工作记忆的记录与使用>)。自动生成个性化 Skill 仍是下方独立候选，不由记忆存储自动执行。

### 基于记忆的个性化 Skill 生成

价值：结合通用 Skill 和已有记忆形成个性化工作流。生成与维护方式待讨论，不预先承诺完整的更新、停用和回退机制，也不扩展底层操作能力；已有候选设计见[生成路线](archive/StarBridge.md#个性化-skill-生成路线)。

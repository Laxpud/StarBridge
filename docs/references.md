# 参考项目

[返回项目入口](README.cn.md) · [设计文档](../StarBridge.md)

资料查阅日期：2026-10-20。以下记录基于项目仓库和官方文档的初步调研，未安装、执行或完成源码级评估。可借鉴的设计是针对 StarBridge 的判断，不代表已选定依赖或已验证 STAR 兼容性。

## STAR-CCM+ 操作与技术资料

### MacroUtils

- 来源：[项目仓库](https://github.com/frkasper/MacroUtils)。
- 项目能力：封装 STAR-CCM+ Java API，为编写宏提供更高层接口。
- 可借鉴：Bridge 内部的对象访问与操作封装、常见操作组织及示例。
- 边界：它是宏辅助库，不能据此认定提供常驻通信、会话管理或 Agent 接口。查阅时 README 指向 STAR-CCM+ 2606 库；选择参考版本时需要匹配实际 STAR 版本。

### starccm-javadoc-mcp

- 来源：[项目仓库](https://github.com/pacoEzq/starccm-javadoc-mcp)。
- 项目能力：通过 `search_api` 和 `get_doc` 检索本机 STAR Javadoc，帮助 Agent 使用真实的 API 签名。
- 可借鉴：按实际安装版本提供技术资料入口，在 Bridge 开发及复杂任务处理中减少凭训练数据猜测 API。
- 边界：文档检索不等于实时算例访问；技术资料和用户工作记忆也应保持各自的来源与职责。

## 常驻会话与 GUI 桥接

### PyFluent

- 来源：[项目仓库](https://github.com/ansys/pyfluent)、[官方启动与连接文档](https://fluent.docs.pyansys.com/version/stable/user_guide/session/launching_ansys_fluent.html)。
- 项目能力：启动 Fluent，并通过 `connect_to_fluent()` 连接已开启 gRPC 服务的现有会话；服务可从 Fluent GUI 启动。
- 可借鉴：区分启动新会话与连接已有会话，将运行中的会话作为操作对象。
- 后续阅读重点：连接信息、会话所有权、断开与关闭的区别、客户端退出后的进程生命周期。
- 边界：Fluent 提供的连接机制不是 STAR 已具备同类能力的证据，StarBridge 需要独立验证通信路径。

### MCP for Blender

- 来源：[项目仓库](https://github.com/ahujasid/mcp-for-blender)，原地址 `ahujasid/blender-mcp` 已重定向。
- 项目能力：Blender 内部插件启动 Socket 服务，外部 MCP 服务连接插件并执行应用内操作。
- 可借鉴：将应用内适配器与外部 Agent 接口分离，让操作作用于用户正在使用的 GUI 会话。
- 后续阅读重点：请求如何进入应用执行环境、如何返回结果和错误、断连与长操作如何处理。
- 边界：Blender 的插件和线程机制不能直接套用到 STAR；其直接执行代码的方式也不能替代 StarBridge 计划中的明确操作契约。

## 持久化工作记忆

### Basic Memory

- 来源：[项目仓库](https://github.com/basicmachines-co/basic-memory)。
- 项目能力：以本地 Markdown 保存知识，人和 Agent 都能编辑，通过 MCP 提供访问，并支持知识关系与检索。
- 可借鉴：用户可以直接查看和修正记忆；内容跨对话保留，适合记录项目约定和算例背景。
- 后续阅读重点：内容与索引的关系、项目隔离、外部编辑后的更新、修改与删除语义。
- 边界：尚未选择其作为依赖。可读文件只是候选存储方式，不能替代作用范围、来源和有效状态的设计。

### Graphiti

- 来源：[项目仓库](https://github.com/getzep/graphiti)。
- 项目能力：构建随时间变化的知识图谱，支持事实有效期、保留失效历史、来源追溯及混合检索。
- 可借鉴：旧约定被替代后不再作为当前约束，同时保留历史原因；派生事实应能追溯到来源。
- 后续阅读重点：事实有效期、来源事件、冲突处理及关系建模。
- 边界：完整图存储会引入额外组件；初步设计可以借鉴其数据语义，暂不决定采用图数据库，也不能让自动推断覆盖用户明确要求。

## 官方研究方向

[Engineering Foundry for Simcenter](https://blogs.sw.siemens.com/art-of-the-possible/agentic-ai-aided-engineering/) 讨论通过 MCP、Skills 和领域工作流组织工程 Agent。

它可作为生态方向参考。文章明确将其定位为研究愿景和创新路线，不是承诺交付的产品；不能据此认定存在适用于本项目的完整 STAR 接口或下载包。

## 建议阅读顺序

1. PyFluent：先明确会话操作契约与生命周期。
2. MacroUtils：了解 STAR 对象访问和操作封装。
3. MCP for Blender：研究应用内适配器与外部 MCP 的职责划分。
4. Basic Memory：研究用户可维护的持久化上下文。
5. starccm-javadoc-mcp：补充版本对应的技术资料检索。
6. Graphiti：补充事实来源、有效期与历史变更的设计。

这些顺序是调研建议，不构成实现依赖。实际待办统一见[当前工作](../TODO.md)，不在本页重复维护任务状态。

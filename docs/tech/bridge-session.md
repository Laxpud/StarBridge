# STAR 会话接入

[返回项目入口](../README.cn.md) · [技术文档](index.md) · [当前架构](architecture.md) · [文件 Bridge](bridge-file.md) · [MCP 契约](mcp.md)

StarBridge 优先连接与目标算例匹配的本机 STAR GUI／服务器；没有可用会话时启动自有后台服务，直接加载原算例。连接、读取和修改均不自动保存，也不创建 `working.sim` 或备份副本。每次请求仍通过临时 Java 批处理客户端执行，客户端退出后 STAR 继续运行。

需要 Linux、Python 3.11+、兼容的 STAR 安装和许可证。共享 CLI、MCP 与会话 CLI 均先检测所选程序版本，再核对已登记适配；`release/build` 只作为可选预期，不用于替换安装。支持范围见[版本说明](catalog-versions.md)。

## 连接与使用

MCP `open_session` 或共享 CLI 的参数示例：

```json
{
  "input": "/absolute/case.sim",
  "star": "/absolute/STAR-CCM+/star/bin/starccm+"
}
```

返回 `session_id`，后续调用原样传回，不再要求调用者创建会话目录。项目位置默认采用算例所在目录，也可用 `project_dir` 指定既有目录。位置在连接时固定，另存为不会迁移项目目录。

自动发现限于同一用户、同一安装且 Linux `/proc` 可见的本机进程。候选端口还需通过只读宏核对实际加载路径、精确版本和 Simulation key；不能把端口开放当作匹配成功。同一文件有多个匹配会话时，用 `port` 选择。没有指定端口且需要启动新服务时，自动选择空闲端口；启动时仍用 `-portrange 1` 防止悄悄换端口。远程服务和不可见的进程不在当前发现范围内。

连接没有保存路径的 GUI 算例时，省略 `input`，明确给出 `port` 和 `project_dir`。找不到已有服务会拒绝，不创建空白算例。同一个已登记连接会复用会话 ID、互斥锁和引用世代。

源码会话 CLI 示例：

```bash
python3 bridge/runner/session_bridge.py start '/absolute/case.sim' \
  --star '/absolute/STAR-CCM+/star/bin/starccm+'

# 将返回的 session_id 填入后续命令。
python3 bridge/runner/session_bridge.py status --session-id SESSION_ID
python3 bridge/runner/session_bridge.py inspect --session-id SESSION_ID
python3 bridge/runner/session_bridge.py save --session-id SESSION_ID
python3 bridge/runner/session_bridge.py save --session-id SESSION_ID \
  --output '/absolute/case-edited.sim'
```

`status` 读取会话记录并核对进程身份，不启动 Java 客户端；`modified` 是最近成功请求的值。`inspect` 读取既有 Inspector 范围，不表示完整设置导出。表达式、标签及目录修改的调用方式见[修改说明](modifier.md)与[目录修改](catalog-modifier.md)；这些修改仍只作用于内存。

## 保存和断开

`save_session(session_id)` 写回 STAR 当前加载文件。给出 `output` 时另存为；目标必须是新的 `.sim` 文件且父目录已存在，避免覆盖无关算例。没有保存路径时必须指定 `output`。保存前会刷新同一加载对象的当前路径，以跟随用户在 GUI 中的另存为；结果的 `output` 是实际绝对路径。保存不自动关闭或重新加载。

`close_session` 根据 `ownership` 处理：

- `external`：只将连接标为 `disconnected`，不发送终止信号，不丢弃用户 STAR 中的修改。
- `owned`：核对未保存修改后停止本次拥有的进程，返回 `stopped`。只有明确授权放弃内存状态时才使用 `discard=true`。

历史实测中，STAR 另存后 `isModified()` 仍可能为真；程序不擅自清零或自动丢弃。细分 CLI 使用 `stop --session-id SESSION_ID`，需要放弃自有服务的未保存修改时添加 `--discard`。

## 身份和失败处理

进程身份由 PID、Linux 启动时刻及系统启动标识共同确定。连接还绑定 Simulation key，后续调用核对加载对象；用户 GUI 另存为可以改变文件路径。每个会话的 Bridge 请求通过文件锁互斥，但不能阻止用户 GUI 同时操作。

请求使用 `-batch`、`-noexit` 和会话专属客户端配置。安装内 JDK 可用时，Java 辅助类编译到 `~/.starbridge/cache/java/` 并通过宏 `-classpath` 复用；每次只生成包含当前参数的入口宏。无法定位安装内 JDK 时仍由 STAR 编译内联源码，编译失败则报告错误。子进程使用 `en_US.UTF-8`，不修改用户全局设置。当前默认超时 180 秒；候选会话探测单次最多 15 秒，超时不是整个连接流程的硬截止。

请求活动记录保存客户端进程身份。客户端仍在执行时保持 `running`，新的操作返回 `busy`；`session_status` 可以读取正在执行的状态。控制端中断后，在确认客户端已结束时收尾活动记录。只读失败不冻结会话。

写入结果未确认时记录 `uncertain_request`，允许读取和状态查询，阻止新的修改、保存及默认停止；成功读取不会自动解除写入限制。不得自动重试或回滚。外部会话可以断开，但重连同一加载对象仍保留未确认记录；自有服务只有明确 `discard` 才能放弃内存状态。

目录／发现修改默认只核对目标与必要关联项。需要审查完整前后快照和 Diff 时，MCP／Core 传 `audit=true`，目录修改 CLI 添加 `--audit`。旧兼容 `set-scalar` 和 schema 1 修改入口仍使用原投影和快照流程，迁移安排见[实施计划](../plans/plan-2026-11-03-14-23.md#接口与执行)。

## 运行数据与项目产物

| 内容 | 位置与保留方式 |
|---|---|
| 会话记录、请求及客户端配置 | `~/.starbridge/sessions/<session_id>/` |
| 可重建的安装元数据和 Java 辅助类 | `~/.starbridge/cache/`，跨会话复用 |
| 会话内对象索引和引用 | 对应会话目录，不跨加载复用 |
| 报告、导出位置约定 | 显式位置优先，其次项目已有 `reports/`、`exports/`、`analysis/`，否则项目 `.starbridge/reports/` 或 `.starbridge/exports/` |

连接不会创建项目 `.starbridge`。目前检查结果直接返回；项目产物路径解析供实际生成报告和导出的入口调用，不意味着已新增报告或导出工具。

正常成功请求只留下简短 `operation.json`；失败请求保留诊断。`open_session(debug=true)` 或会话 CLI `start --debug` 保留宏、计划、日志和完整结果，调用结果还会给出 `request_result` 路径。保存的算例始终位于工程路径或用户指定位置。

新连接时顺便清理超过 30 天、已结束且不需要恢复的新版会话数据；含算例文件的目录不删除。只有所有登记会话均已结束时才清理超过 30 天的 JSON 缓存和未复用的 Java 编译目录；Java 编译与清理共用目录锁。运行中、结果未确认、记录损坏或被其他请求占用的数据保留，不运行额外清理服务。

## 验证边界

三端插件、会话接入与运行简化里程碑中的会话与执行层改造已做静态编译与适用的既有契约检查；辅助类缓存的实际 STAR 宏加载尚未实测。真实 GUI 接入、保存、失败恢复和收窄后的写入链路尚未实测。历史后台副本验证不替代这些行为的运行证据。

# STAR 会话接入

[返回项目入口](../README.cn.md) · [技术文档](index.md) · [当前架构](architecture.md) · [文件 Bridge](bridge-file.md) · [MCP 契约](mcp.md)

StarBridge 优先连接与目标算例匹配的本机 STAR GUI／服务器；没有可用会话时启动自有后台服务，直接加载原算例。连接和结构化读写不自动保存，也不创建 `working.sim` 或备份副本；通用宏及 STAR 既有自动保存的边界见[通用执行](<generic-execution.md#修改保存与探索的边界>)。每次请求仍通过临时 Java 批处理客户端执行，客户端退出后 STAR 继续运行。

需要 Linux、Python 3.11+、可明确定位安装内 JDK／库的 STAR 安装和许可证。共享 CLI、MCP 与会话 CLI 均先检测实际程序版本并核对可选 `release/build` 预期；加载前独立预编译最小生命周期模板，接入后再核对 server 版本与加载对象。未登记结构化目录不阻止此通用路径，但不代表该版本全部 API 已验证；不替换安装、借用邻近目录或系统 JDK。结构化接口的精确门槛另见[版本说明](<catalog-versions.md>)。

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

连接没有保存路径的 GUI 算例时，省略 `input`，明确给出 `port` 和 `project_dir`。找不到已有服务会拒绝，不擅自创建空白算例。同一个已登记连接会复用会话 ID、互斥锁和引用世代。

显式从零创建使用 `open_session(create=true, project_dir=...)`，不传 `input`。该模式通过 `-server -new` 创建自有空算例，不复用其他会话、不复制文件、不自动保存。后续在同一会话中执行结构化操作或[通用 Java 步骤](<generic-execution.md>)。

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

`save_session(session_id)` 写回 STAR 当前加载文件。给出 `output` 时另存为；目标必须是新的 `.sim` 文件且父目录已存在，避免覆盖无关算例。没有保存路径时必须指定 `output`。保存前会刷新同一加载对象的当前路径，以跟随用户在 GUI 中的另存为；结果的 `output` 是实际绝对路径。保存不自动关闭或重新加载。当前保存与关闭前检查只读取会话身份、路径和修改标志，不为这两个动作遍历完整 Inspector；保存结果使用 `session_metadata`，完整审查另调用 `inspect_session`。

`close_session` 根据 `ownership` 处理：

- `external`：只将连接标为 `disconnected`，不发送终止信号，不丢弃用户 STAR 中的修改。
- `owned`：核对未保存修改后停止本次拥有的进程，返回 `stopped`。只有明确授权放弃内存状态时才使用 `discard=true`。

历史实测中，STAR 另存后 `isModified()` 仍可能为真；程序不擅自清零或自动丢弃。细分 CLI 使用 `stop --session-id SESSION_ID`，需要放弃自有服务的未保存修改时添加 `--discard`。

## 身份和失败处理

进程身份由 PID、Linux 启动时刻及系统启动标识共同确定。连接还绑定 Simulation key，后续调用核对加载对象；用户 GUI 另存为可以改变文件路径。每个会话的 Bridge 请求通过文件锁互斥，但不能阻止用户 GUI 同时操作。

请求使用 `-batch`、`-noexit` 和会话专属客户端配置。通用接入、保存与关闭使用独立生命周期宏，不依赖 `CatalogRuntime`／`DiscoveryRuntime` 编译；最小模板预编译凭据位于 `~/.starbridge/cache/lifecycle/`，实际请求再用所选安装 JDK 编译。结构化 Java 辅助类继续缓存到 `~/.starbridge/cache/java/` 并通过宏 `-classpath` 复用；旧结构化文件入口保留无法定位 JDK 时的内联编译方式，新会话接入不使用此回退。子进程使用 `en_US.UTF-8`，不修改用户全局设置。当前默认超时 180 秒；候选会话探测单次最多 15 秒，超时不是整个连接流程的硬截止。

请求活动记录保存派发阶段与客户端进程身份。启动尝试前记录准备状态，尝试启动后缺少 PID 也不能证明未派发。客户端或其进程组仍在执行时保留活动记录，新的操作返回 `busy`；`session_status` 可以读取正在执行的状态。启动器退出、操作超时或取得步骤终态，都不单独证明整个客户端已结束。外部断开可以使会话为 `disconnected`，但不把仍活动的执行凭据误报成停止。控制端中断后，在确认客户端已结束时收尾活动记录。只读失败不新增未知写入限制，也不解除此前的限制。

写入结果未确认时记录 `uncertain_request`，允许读取和状态查询，阻止新的修改、保存及默认停止；成功读取不会自动解除写入限制。不得自动重试或回滚。外部会话可以断开，但重连同一加载对象仍保留未确认记录；自有服务只有明确 `discard` 才能放弃内存状态。

目录／发现修改默认只核对目标与必要关联项。需要审查完整前后快照和 Diff 时，MCP／Core 传 `audit=true`，目录修改 CLI 添加 `--audit`。`set-scalar`、schema 1 修改及其结果投影已移除，已有能力使用[统一属性入口](mcp.md#迁移与兼容边界)。

## 运行数据与项目产物

| 内容 | 位置与保留方式 |
|---|---|
| 会话记录、请求及客户端配置 | `~/.starbridge/sessions/<session_id>/` |
| 可重建的安装元数据和 Java 辅助类 | `~/.starbridge/cache/`，跨会话复用 |
| 会话内对象索引和引用 | 对应会话目录，不跨加载复用 |
| 报告、导出位置约定 | 显式位置优先，其次项目已有 `reports/`、`exports/`、`analysis/`，否则项目 `.starbridge/reports/` 或 `.starbridge/exports/` |

运行根默认 `~/.starbridge`，可通过绝对路径环境变量 `STARBRIDGE_HOME` 显式隔离开发环境。持久工作记忆位于运行根的 `memory/`，不参加会话清理；显式项目记忆写入项目 `.starbridge/memory/`。

连接不会创建项目 `.starbridge`。检查结果直接返回；通用宏可以按任务导出文件，输出位置须由调用者明确提供。产物路径解析本身不代表已有各类专用报告导出工具。

结构化成功请求只留下简短 `operation.json`；失败请求保留诊断。通用宏请求始终保留源码、参数和逐步凭据，供 `get_execution` 与相同请求标识重放读取；这些运行数据遵循下述清理周期，长期方法应另外记入工作记忆。`open_session(debug=true)` 或会话 CLI `start --debug` 保留宏、计划、日志和完整结果，调用结果还会给出 `request_result` 路径。保存的算例始终位于工程路径或用户指定位置。

新连接时顺便清理超过 30 天、已结束且不需要恢复的新版会话数据；含算例文件的目录不删除。只有所有登记会话均已结束时才清理超过 30 天的 JSON 缓存和未复用的 Java 编译目录；Java 编译与清理共用目录锁。运行中、结果未确认、记录损坏或被其他请求占用的数据保留，不运行额外清理服务。

## 验证边界

STAR 2602 已实际完成后台从零创建、通用宏连续操作、请求重放和显式保存；场函数任务还完成重新加载读取。独立小通道完成909单元网格、5次求解迭代、监视器与报告导出。自然运行暴露了 batch 自动保存边界和后续连接中 dirty 再次为真的现象，不能将成功返回解释为无额外写文件或自动允许关闭。原始凭据、保存后的检查和释放范围统一见[通用执行证据](<generic-execution.md#当前实际证据与未完成项>)。关联导航、静态写入和对象参数复用已有小算例实跑；2510也完成最小生命周期接入／保存和通用字段配置。2602 GUI 先加载后的接入、原窗口中显示变更、外部断开保留服务器，以及派发中断、变更后异常、超时和迟到凭据已按链接中的具体场景实跑；最终收尾修正也已由新控制进程核对，分别覆盖有终态但进程组尚未退出、只读无终态后的末次状态和当前响应保留历史限制；不将这些场景推广为全部失败或结构化写入路径已验证。

当前通过 Python 静态编译、2602／2510 库下入口宏及16个参数化方法变体编译、24个 MCP 工具的 schema 校验与实际 stdio 握手，当前工具还完成契约、方法和单位规则记忆查询。既有 Java 发现6项和快照比较15项检查通过。Core 发现检查 9 项通过，另 1 项仍依赖已删除的 HMAC 私钥，在本轮改动前后均失败；未新增或改写测试。旧 `discovery_acceptance.py` 仍使用原接口与产物格式，不能直接用于当前版本验收。离线转换已有运行材料只核对了新对象引用和结果格式，不是新的 STAR 运行证据。

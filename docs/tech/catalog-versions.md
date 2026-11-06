# STAR 版本选择与目录维护

[返回项目入口](../README.cn.md) · [技术文档](index.md) · [当前架构](architecture.md) · [目录工具](catalog.md) · [文件入口](bridge-file.md) · [后台会话](bridge-session.md)

StarBridge 的结构化目录按精确产品版本和 Build 选择。当前随附 `2602 / 21.02.007` 与 `2510 / 20.06.007`；两者分别保存从对应安装生成的候选 API、人工调用映射、兼容快照布局和语义说明。相同 release 的其他 Build、未登记版本及混合版本的结构化计划均拒绝，不自动回退。通用生命周期与 Java 宏不以目录登记为前提，但仍须实际版本检测、所选安装 JDK 预编译及运行时身份检查；通用入口存在不表示未知版本已验证。

## 文件与会话入口

文件 `inspect` 默认使用 2602；修改从显式目录取得版本，schema 1 修改和 `set-scalar` 已删除。操作 2510 文件时，同时选择匹配的启动器和目录版本，例如：

```bash
python3 bridge/runner/file_bridge.py inspect example-2510.sim \
  --star /absolute/path/to/2510/star/bin/starccm+ \
  --catalog-release 2510 --work-dir outputs/inspect-2510
```

显式目录 `describe/read/modify` 从 `--catalog` 和 `--execution` 取得目标版本，修改所需的兼容快照选择同版本随附布局。也可同时指定 `--catalog-release`，但必须与显式目录一致。外部目录仍须使用已登记的精确 release/Build；不能仅修改 JSON 的版本字段冒充适配。

会话 `start` 从所选程序探测版本，`--catalog-release` 仅核对预期 release；2510 示例：

```bash
python3 bridge/runner/session_bridge.py start example-2510.sim \
  --star /absolute/path/to/2510/star/bin/starccm+ \
  --catalog-release 2510 --port 49001
```

新会话把实际版本绑定保存为 `star_version`，`version_source` 区分启动器检测与 server 核验；只有已有精确适配时才设置 `catalog_target`，否则为 `null`。`inspect` 与结构化属性修改仍要求目录绑定等于实际版本。保存、普通关闭使用中性版本绑定和独立最小宏，不构造快照计划，也不编译目录／发现辅助类。通用宏同样不依赖目录版本绑定；显式对象参数绑定可额外编译版本中立的定位辅助代码，但不因此获得结构化发现支持。旧会话的显式 `catalog_target` 可继续作为预期绑定；完全没有版本字段时，首次通用操作先实际检测所选程序并对原进程及加载对象只读握手，不把历史 2602 默认冒充检测。显式字段损坏或相互冲突时拒绝，不按旧会话回退。

本地计划错配在输出目录或会话活动标记写入前拒绝，现有会话保持原状态。Java 还会在实际调用前核对正在运行的 server，选择正确目录不能代替 server 检查。`status` 与 `stop --discard` 不依赖目录加载，使目录不可用时仍能查询和清理本工具创建的服务。目录选择不会转换 `.sim` 文件格式，也不保证较旧 STAR 能打开较新版本保存的文件。

[MCP 与共享 JSON CLI](<mcp.md>) 和会话 CLI 均实际检测安装，区别于文件 CLI 的固定 release 默认值。先从用户要求或 `discover_installations` 的实际探测选择程序；`open_session` 从所选程序的 `-version` 取得版本，显式 `release/build` 仅作为预期核对。无法检测、预期不符或所选安装 JDK／库无法明确定位时在加载前拒绝；不切换安装，不用系统 JDK 代替。未登记版本只允许尝试独立最小生命周期模板的预编译与 server 握手，后续宏仍逐请求编译。`get_capabilities()` 的 `supported`、`catalog_supported` 和 `supported_versions` 只描述结构化目录；`session_lifecycle`、`generic_execution` 与 `runtime_discovery` 分别报告通用前提和发现门槛。未知版本的目录／发现支持仍为 false；静态编译与身份成功不代表全部 API 或任务行为已验证。具体范围和代表性验证见 [MCP 验证范围](<mcp.md#验证范围>)。

## 版本材料与覆盖

既有验证结果与复现材料见[验证记录](../evidence/catalog-versions.md)。当前会话与执行改造的实测缺口统一见[会话验证边界](bridge-session.md#验证边界)。

# STAR 版本选择与目录维护

[返回项目入口](../README.cn.md) · [技术文档](index.md) · [当前架构](architecture.md) · [目录工具](catalog.md) · [文件入口](bridge-file.md) · [后台会话](bridge-session.md)

StarBridge 按精确的产品版本和 Build 选择目录。当前随附 `2602 / 21.02.007` 与 `2510 / 20.06.007`；两者分别保存从对应安装生成的候选 API、人工调用映射、兼容快照布局和语义说明。相同 release 的其他 Build、未知版本及混合版本计划均拒绝，不自动回退。

## 文件与会话入口

文件 `inspect`、兼容 schema 1 `modify` 和 `set-scalar` 默认使用 2602。操作 2510 文件时，同时选择匹配的启动器和目录版本，例如：

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

新会话把目标保存为 `session.json.catalog_target`。后续 `inspect`、兼容修改、保存和普通关闭使用该绑定，不再从新的默认值选择目录；显式目录请求必须与会话绑定一致。旧会话没有此字段时，沿用此前固定 2602 的契约。显式字段损坏、未知版本或 Build 不符时拒绝，不能按旧会话处理。

本地计划错配在输出目录或会话活动标记写入前拒绝，现有会话保持原状态。Java 还会在实际调用前核对正在运行的 server，选择正确目录不能代替 server 检查。`status` 与 `stop --discard` 不依赖目录加载，使目录不可用时仍能查询和清理本工具创建的服务。目录选择不会转换 `.sim` 文件格式，也不保证较旧 STAR 能打开较新版本保存的文件。

[MCP 与共享 JSON CLI](mcp.md) 使用相同精确版本绑定，与会话 CLI 一样探测实际安装版本，区别于文件 CLI 的固定 release 默认值。先从用户要求或 `discover_installations` 的实际探测选择程序；`open_session` 从所选程序的 `-version` 取得版本，显式 `release/build` 仅作为预期核对。未适配或预期不符在创建会话前拒绝，后续工具使用保存的绑定。`get_capabilities()` 省略版本只列注册支持范围，指定实际版本时返回 `supported`；未知版本也可查询，并返回缺少适配的原因，不自动回退。具体范围和代表性验证见 [MCP 验证范围](mcp.md#验证范围)。

## 版本材料与覆盖

既有验证结果与复现材料见[验证记录](../evidence/catalog-versions.md)。当前会话与执行改造的实测缺口统一见[会话验证边界](bridge-session.md#验证边界)。

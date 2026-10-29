# STAR 版本选择与目录维护

[返回项目入口](README.cn.md) · [目录工具](catalog.md) · [文件入口](bridge-file.md) · [后台会话](bridge-session.md)

StarBridge 按精确的产品版本和 Build 选择目录。当前随附 `2602 / 21.02.007` 与 `2510 / 20.06.007`；两者分别保存从对应安装生成的候选 API、人工调用映射、兼容快照布局和语义说明。相同 release 的其他 Build、未知版本及混合版本计划均拒绝，不自动回退。

## 文件与会话入口

文件 `inspect`、兼容 schema 1 `modify` 和 `set-scalar` 默认使用 2602。操作 2510 文件时，同时选择匹配的启动器和目录版本，例如：

```bash
python3 bridge/runner/file_bridge.py inspect example-2510.sim \
  --star /absolute/path/to/2510/star/bin/starccm+ \
  --catalog-release 2510 --work-dir outputs/inspect-2510
```

显式目录 `describe/read/modify` 从 `--catalog` 和 `--execution` 取得目标版本，修改所需的兼容快照选择同版本随附布局。也可同时指定 `--catalog-release`，但必须与显式目录一致。外部目录仍须使用已登记的精确 release/Build；不能仅修改 JSON 的版本字段冒充适配。

后台 `start` 默认绑定 2602；2510 示例：

```bash
python3 bridge/runner/session_bridge.py start example-2510.sim \
  --star /absolute/path/to/2510/star/bin/starccm+ \
  --catalog-release 2510 --session-dir outputs/session-2510 --port 49001
```

新会话把目标保存为 `session.json.catalog_target`。后续 `inspect`、兼容修改、保存和普通关闭使用该绑定，不再从新的默认值选择目录；显式目录请求必须与会话绑定一致。旧会话没有此字段时，沿用此前固定 2602 的契约。显式字段损坏、未知版本或 Build 不符时拒绝，不能按旧会话处理。

本地计划错配在输出目录或会话活动标记写入前拒绝，现有会话保持原状态。Java 还会在实际调用前核对正在运行的 server，选择正确目录不能代替 server 检查。`status` 与 `stop --discard` 不依赖目录加载，使目录不可用时仍能查询和清理本工具创建的服务。目录选择不会转换 `.sim` 文件格式，也不保证较旧 STAR 能打开较新版本保存的文件。

## 版本材料与覆盖

2510 的 140 个根类型及继承依赖包含 225 个类型、2,864 个声明成员和 167 个注解属性候选。其初次版本验收时的 99 个实际调用映射均有本版本声明依据；与 2602 对应映射相比，`function.dimensions`、`field_function.dimensions` 和 `profile.dimensions` 的 Javadoc 注解不同，已分别锁定 2510 的签名和指纹。其余对应成员指纹相同。后续工作流选择映射使用两版各自成员指纹，2510 暂无该新增路径的真实运行证据。该比较只说明本次已选调用材料，不证明全部 API 或运行语义兼容。

2510 候选由本机 Build 20.06.007 独立生成，两次结果逐字节一致；完整宏及共享运行时通过该安装的 JDK 和 JAR 编译。生成、合并、精确版本拒绝与混合执行计划的本地拒绝已核对。两个版本的成功读写证据必须按自己的 `catalog_id` 和运行版本统计，不能共享成功计数；方法和参数的未测分支继续保留为证据缺口。

2510 Build 20.06.007 的新建工作副本已验证标量常量与表达式、向量分量、用户场函数布尔属性和 `includes: All` 查询写入；未启用重力模型的描述返回条件不满足。显式传入 2602 目录的会话请求在本地拒绝，会话记录逐字节未变，随后继续读取成功。兼容 `set-scalar` 使用会话绑定完成修改和另存；关闭后，2510 文件 `set-scalar` 与目录 `modify` 分别完成另存、独立重载、完整快照及目录核对和输入摘要核对。2510 server 使用 2602 目录的只读请求也在 Java 版本检查时拒绝；默认 2602 文件快照及原输入摘要回归通过。

2510 夹具刚创建时未加载网格模块，完整快照因 MeshOperationManager 缺失报错，修改在写入前拒绝。夹具显式 `loadMeshing()` 后管理器及体积平均报告可用，再进行上述验收；产品不会在读取时自动加载该模块。此结果说明实例条件需要单独检查，不把声明存在或编译成功当作当前对象可用。

本批产物位于本地 `outputs/catalog-2510-20261029/`，验证会话已关闭，未运行网格或求解。覆盖报告接受 24 个属性读取样例、5 个属性写入样例和 1 个目录属性文件重载样例；兼容命令另有重载证据，不混入 schema 2 写入计数。2510 的边界、网格尺寸、张量、材料方法切换及其异常分支尚未实测，不能沿用 2602 的成功记录。上述数量只对应本批目录 ID。

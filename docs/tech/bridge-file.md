# 文件 Bridge 原型

[返回项目入口](../README.cn.md) · [技术文档](index.md) · [当前架构](architecture.md) · [当前工作](../../TODO.md)

本页说明当前每次加载文件的兼容入口；历史实测版本、算例和结果见[文件验证记录](../evidence/bridge-file.md)。连续操作同一后台会话见[后台会话说明](bridge-session.md)。源码脚本保留为兼容入口；发行包另提供 `starbridge-file`、`starbridge-session` 和共享 JSON CLI，见[分发说明](../distribution.md#安装程序)。

## 读取算例对象与参数

需要 Python 3.11 或更新版本、可启动且具有可用许可证的 STAR-CCM+，以及与其兼容的输入算例。当前 `inspect` 和修改均由随附目录驱动，运行中 server 必须精确匹配所选目录，默认 2602 Build 21.02.007，其他随附版本见[版本选择](catalog-versions.md)；字段读取或写入前拒绝不匹配的版本。Runner 默认调用 `PATH` 中的 `starccm+`，可用 `--star /absolute/path/to/starccm+` 指定启动器。

在仓库根目录运行：

```bash
python3 bridge/runner/file_bridge.py inspect 'Base.sim~' \
  --work-dir outputs/read-parameters
```

`--work-dir` 必须是尚不存在的目录。程序完成后打印 `summary.json` 的绝对路径。完整对象字段、关系、排序和错误语义见 [Inspector 对象快照](inspector.md)；原有参数字段包含：

* 算例名称、当前加载文件路径及 STAR 的 `modified` 标志；此标志在本机另存后仍可能为真，不能单凭它判断保存失败。
* 参数名称与 STAR 对象类型。
* 标量参数的表达式 `definition`、单位 `unit`、当前单位值 `raw_value` 和 SI 值 `si_value`。
* 向量参数的表达式、单位和当前单位向量；实际验证范围见 [Inspector 记录](../evidence/inspector.md)。
* 未覆盖类型的 `unsupported` 标记，以及参数读取失败时的 `read_error`。收到这些标记时，不应把快照视为完整读取。

无量纲参数的单位名称可为空字符串。表达式和求值结果同时保留，例如引用其他参数的表达式不会仅被记录为当前数值。非有限标量值作为字符串输出，避免生成不合法 JSON。

## 按预期旧状态修改

文件 `modify` 必须提供 `--catalog`、`--execution`、`--request` 与 `--output`，使用已有目录的 schema 2 属性或 schema 3 结构操作。请求格式见[目录修改](catalog-modifier.md)，旧 `set-scalar` 与 schema 1 请求已删除，能力对应见[迁移说明](modifier.md)。

输出必须是新的 `.sim` 文件，父目录已存在。文件 Runner 加载输入后按目录执行修改并回读，另存输出，再独立加载输出核对目标目录属性和 Inspector 快照；最后确认输入 SHA256 未变。结果包含 `catalog_before/catalog`、快照与 Diff，以及 `reopened_catalog_match/reopened_snapshot_match`；不再返回旧 `parameter_diff` 投影。

这些重载与输入保护步骤属于独立文件流程；会话普通赋值不自动保存或重载。数值常量、表达式和标签均按对应属性契约提供新值及实际读取的 `expected`，不从名称或示例猜测旧值。

## 运行产物与失败处理

每次操作使用独立工作目录：

| 路径 | 内容 |
|---|---|
| `summary.json` | 成功完成后的读取结果或修改核对结果 |
| `apply/command.json` | 首次 STAR 调用的参数列表 |
| `apply/BridgeFileMacro.java` | 本次实际执行的宏 |
| `apply/star.log` | STAR 加载、编译和执行日志 |
| `apply/result.json` | 宏返回的修改前后快照及目录结果 |
| `reopen/` | 修改操作第二次启动 STAR 的同类产物 |

计划与规范化请求直接传给执行器并嵌入入口宏，文件 CLI 默认不另存计划 JSON。内部 `execute(debug=true)` 才另外保存请求与计划；文件 CLI 当前不提供此调试选项。

Runner 同时检查 STAR 退出码及宏结果文件，避免只凭进程正常退出就判断宏执行成功。失败时检查错误消息指向的日志；输出文件可能已保存但后续核对失败，此时不会生成成功摘要。保留该文件用于排查，再次运行时应选择新的输出路径。

Runner 对 STAR 子进程指定 `en_US.UTF-8`，并通过 `-nbuserdir` 把客户端缓存放在本次工作目录，不修改全局区域设置。采用该区域设置的早期运行依据见[文件验证记录](../evidence/bridge-file.md)。

算例和 `outputs/` 已被 Git 忽略，运行产物保留在本地。文件入口当前没有操作超时与进程恢复机制，不应把它当作无人值守服务。

## 实现对应关系

| 文件 | 职责 |
|---|---|
| [file_bridge.py](../../src/starbridge/bridge/runner/file_bridge.py) | 校验路径、生成宏、启动 STAR、记录日志、重新加载并核对旧快照、目录内容与输入摘要 |
| [BridgeFileMacro.java](../../src/starbridge/bridge/java/BridgeFileMacro.java) | 调用 STAR Java API 读取对象快照、设置标量、另存文件并序列化结果 |

宏模板中的占位符由 Runner 填入，不能直接作为完整宏执行。输入由 STAR 自身加载，没有解析或修改 `.sim` 二进制格式。

使用的 API 已对照本机安装目录下 `doc/client/html` 中的 Javadoc：`GlobalParameterManager`、`ScalarGlobalParameter`、`ScalarPhysicalQuantity`、`Units` 和 `RootObject`。标量值分别使用 `getRawValue()`、`getSIValue()` 读取，设置使用 `setValueAndUnits()`，保存使用 `saveState()`。

## 已确认的范围

既有验证结果与复现材料见[验证记录](../evidence/bridge-file.md)。当前会话与执行改造的实测缺口统一见[会话验证边界](bridge-session.md#验证边界)。

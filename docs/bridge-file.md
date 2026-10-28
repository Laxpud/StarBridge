# 文件 Bridge 原型

[返回项目入口](README.cn.md) · [当前工作](../TODO.md)

核对基线：2026-10-20，本机 Linux、STAR-CCM+ 2602 Build 21.02.007，以及用户提供的 `Base.sim~`。本页说明每次加载文件的入口；连续操作同一后台会话见[后台会话说明](bridge-session.md)。两者均为原型脚本，尚未封装为正式 `starbridge` CLI。

## 读取算例对象与参数

需要 Python 3.11 或更新版本、可启动且具有可用许可证的 STAR-CCM+，以及与其兼容的输入算例。本次仅实际验证上述 STAR 版本。Runner 默认调用 `PATH` 中的 `starccm+`，可用 `--star /absolute/path/to/starccm+` 指定启动器。

在仓库根目录运行：

```bash
python3 bridge/runner/file_bridge.py inspect 'Base.sim~' \
  --work-dir outputs/read-parameters
```

`--work-dir` 必须是尚不存在的目录。程序完成后打印 `summary.json` 的绝对路径。完整对象字段、关系、排序和错误语义见 [Inspector 对象快照](inspector.md)；原有参数字段包含：

* 算例名称、当前加载文件路径及 STAR 的 `modified` 标志；此标志在本机另存后仍可能为真，不能单凭它判断保存失败。
* 参数名称与 STAR 对象类型。
* 标量参数的表达式 `definition`、单位 `unit`、当前单位值 `raw_value` 和 SI 值 `si_value`。
* 向量参数的表达式、单位和当前单位向量；本次输入只有标量，向量读取分支尚未实测。
* 未覆盖类型的 `unsupported` 标记，以及参数读取失败时的 `read_error`。收到这些标记时，不应把快照视为完整读取。

无量纲参数的单位名称可为空字符串。表达式和求值结果同时保留，例如引用其他参数的表达式不会仅被记录为当前数值。非有限标量值作为字符串输出，避免生成不合法 JSON。

## 按预期旧状态修改

表达式和标签修改使用 `modify --request`，请求格式、预检查、全部已覆盖字段的 Diff 和重载核对见 [Modifier 单项修改](modifier.md)。以下 `set-scalar` 保留原有直接设置常量的行为，不包含 `expected` 旧状态检查。

## 修改已有标量并另存

以下示例把俯仰幅值设为 `6 deg`：

```bash
python3 bridge/runner/file_bridge.py set-scalar 'Base.sim~' \
  --work-dir outputs/change-pitch \
  --output outputs/Base_pitch6_example.sim \
  --name _AirfoilPitchAmplitude --value 6 --unit deg
```

输出文件的父目录必须已存在，目标必须是新的 `.sim` 文件，不能覆盖输入或其他已有文件。单位使用 STAR 单位对象的名称；宏检查与原参数单位的量纲兼容性。

此操作把参数设置为**数值常量**，会替换该参数原有表达式；原表达式保存在修改前快照中。当前不提供修改表达式、创建参数或删除参数的入口。

执行步骤：

1. 加载输入文件，读取参数快照。
2. 找到已有标量参数，检查单位并设置数值。
3. 另存目标文件，读取保存后的参数快照。
4. 启动第二次 STAR 批处理，重新加载目标文件。
5. 比较重新加载与保存后的参数快照，核对请求的目标数值和单位，并输出相对于输入的参数 Diff。
6. 核对原文件 SHA256 未变化。

`summary.json` 中的 `parameter_diff` 会包含所有已覆盖参数的变化；其他参数的求值结果可能因依赖关系变化，需要结合其表达式解释。该 Diff 不覆盖整个 STAR 对象树，不能证明边界、网格、物理模型等对象完全未变化。

## 运行产物与失败处理

每次操作使用独立工作目录：

| 路径 | 内容 |
|---|---|
| `summary.json` | 成功完成后的读取结果或修改核对结果 |
| `apply/command.json` | 首次 STAR 调用的参数列表 |
| `apply/BridgeFileMacro.java` | 本次实际执行的宏 |
| `apply/star.log` | STAR 加载、编译和执行日志 |
| `apply/result.json` | 宏返回的修改前后快照 |
| `reopen/` | 修改操作第二次启动 STAR 的同类产物 |

Runner 同时检查 STAR 退出码及宏结果文件，避免只凭进程正常退出就判断宏执行成功。失败时检查错误消息指向的日志；输出文件可能已保存但后续核对失败，此时不会生成成功摘要。保留该文件用于排查，再次运行时应选择新的输出路径。

本机首次在 `C.UTF-8` 环境下启动时遇到 STAR 数值格式提供器递归错误。原型对子进程指定 `en_US.UTF-8`，并通过 `-nbuserdir` 把 STAR 客户端缓存放在本次工作目录，不修改全局区域设置。其他主机是否需要这一设置尚未验证。

算例和 `outputs/` 已被 Git 忽略，运行产物保留在本地。文件入口当前没有操作超时与进程恢复机制，不应把它当作无人值守服务。

## 实现对应关系

| 文件 | 职责 |
|---|---|
| [file_bridge.py](../bridge/runner/file_bridge.py) | 校验路径、生成宏、启动 STAR、记录日志、重新加载并核对参数与输入摘要 |
| [BridgeFileMacro.java](../bridge/java/BridgeFileMacro.java) | 调用 STAR Java API 读取对象快照、设置标量、另存文件并序列化结果 |

宏模板中的占位符由 Runner 填入，不能直接作为完整宏执行。输入由 STAR 自身加载，没有解析或修改 `.sim` 二进制格式。

使用的 API 已对照本机安装目录下 `doc/client/html` 中的 Javadoc：`GlobalParameterManager`、`ScalarGlobalParameter`、`ScalarPhysicalQuantity`、`Units` 和 `RootObject`。标量值分别使用 `getRawValue()`、`getSIValue()` 读取，设置使用 `setValueAndUnits()`，保存使用 `saveState()`。

## 已确认的范围

实际输入共读取到 32 个标量全局参数，无参数读取错误。将 `_AirfoilPitchAmplitude` 从 `5 deg` 改为 `6 deg` 后，新文件重新加载结果与保存后快照一致；参数 Diff 只有该项，输入文件摘要保持一致。

没有执行网格生成或求解，也没有验证向量、其他参数类型、异常单位、MCP 或工作记忆功能。扩展对象读取的验证范围见 [Inspector](inspector.md#验证范围)。后台会话的验证范围单独记录在[会话说明](bridge-session.md#已确认的范围)。

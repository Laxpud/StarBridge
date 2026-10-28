# Inspector 对象快照

[返回项目入口](README.cn.md) · [目录描述与读取](catalog-runtime.md) · [文件入口](bridge-file.md) · [后台会话](bridge-session.md)

Inspector 读取算例对象清单、关键属性和归属关系。文件 `inspect` 的 `summary.json.snapshot` 与后台会话 `inspect` 的 `snapshot` 使用相同格式。设置与保存操作中的 `before`、`after` 也使用此格式；旧 `set-scalar` 的自动 Diff 和重新加载核对仍只覆盖参数；新 [Modifier](modifier.md) 使用同一快照记录全部已覆盖字段的 Diff，并在文件重新加载后比较对象内容。

新增的目录 `describe/read` 通过共享映射按需访问当前对象，契约及覆盖见[目录描述与读取](catalog-runtime.md)。其结果使用独立 `catalog` 字段，包含当前 server 版本、会话引用和逐属性状态。本页的旧 `inspect` 仍按固定字段生成快照，尚未全部迁入目录；两种结果的 `inspection_complete` 各自只说明其声明的读取范围。

```bash
python3 bridge/runner/file_bridge.py inspect 'Base.sim~' \
  --work-dir outputs/inspect-objects

python3 bridge/runner/session_bridge.py inspect \
  --session-dir outputs/my-session
```

第二条命令要求已经用 `session_bridge.py start` 启动会话。两种入口的启动条件、目录要求与失败恢复分别见上方使用说明。

## 快照字段

`schema_version` 当前为 `1`，表示本页描述的对象快照格式；早期只有参数的快照不含此字段。原有 `simulation_name`、`session_path`、`modified` 和 `parameters` 字段继续保留。`modified` 是 STAR 返回的内存状态，不能单独据此判断磁盘文件是否发生变化。

集合中的对象具有 `name`、`object_type` 和 `tags`。对象类型保留 STAR Java 类的简单名称；标签使用排序后的名称数组。关系引用只有名称和类型，不重复展开目标对象。名称用于当前快照内识别对象，不是跨重命名的永久 ID。

| 字段 | 当前读取内容 |
|---|---|
| `parameters` | 标量表达式、单位、SI 单位对象名 `si_unit`、当前单位值和 SI 值；向量表达式、单位和当前单位分量；附加标签 |
| `field_functions` | 显示名称、可在表达式中引用的 `function_name`、`value_type`、量纲名称 `dimensions`、`user_defined`；用户场函数另有 `definition` |
| `tags` | 标签名称与对象类型 |
| `continua` | 连续体、关联区域 `regions`、其模型管理器中的 `models` |
| `regions` | `region_type`、关联物理连续体 `physics_continuum`；嵌套 `boundaries` 及各自的 `boundary_type` |
| `interfaces` | `interface_type`；边界接口另有 `enabled`、`boundary0`、`boundary1`，端点含所属 `region` |
| `mesh_operations` | 操作名称与类型、STAR 返回的 `index`、关联 `input_parts` |
| `reports` | 报告名称、类型与 `unit`；表达式报告另有 `definition` |
| `monitors` | 监视器名称、类型与 `enabled`；报告监视器另有 `report` 引用 |
| `stopping_criteria` | 准则名称、类型与 `enabled`；最大步数准则另有 `definition`、`maximum_steps`；最大物理时间准则另有数量对象 `maximum_time` |
| `simulation_operations` | 工作流及其 `blocks`；循环块内嵌 `blocks`，子工作流块使用 `workflow` 引用 |

对象集合按名称、类型排序，标签按名称排序。边界嵌套在所属区域中；接口的边界引用也带区域，避免不同区域里的同名边界发生混淆。缺失的可选关系保留为 `null`。

数量对象的 `raw_value` 使用 `unit` 对应单位，`si_value` 使用 `si_unit` 指明的 SI 单位；无量纲单位名称可能为空字符串。向量不转换坐标系，只保留 STAR 返回的分量，不应推断为另一坐标系下的向量。`NaN`、`Infinity` 等非有限数值编码为字符串，保持 JSON 合法。

## 空集合、读取错误与覆盖范围

先检查 `inspection_complete` 和 `read_errors`，再使用快照做判断：

- `inspection_complete: true`：本版声明的字段均成功读取。它不表示完整导出了所有 STAR 设置。
- `inspection_complete: false`：至少一处读取失败或存在未支持的参数类型。`read_errors` 中的 `location` 和 `message` 指明对象或集合位置；单个对象失败时另有 `read_error`，已读字段继续保留。
- `[]`：对应位置及其子项没有读取错误时，才表示该管理器返回空集合；读取失败时也可能返回空或部分集合。
- `unsupported: true`：该参数类型的数值读取尚未实现。其他对象只保证本表明确列出的属性；没有额外属性不等于这些属性在 STAR 中不存在。

错误位置使用“集合/对象名称/子集合”的可读路径，名称本身可能含 `/`，因此它不是可供分割解析的 JSON Pointer。`inspect` 对部分读取输出警告并保留结果，退出码仍可为零。宏的 `status: ok` 表示执行和结果写出成功；使用者必须另外检查快照完整性。

Inspector 不调用报告求值、网格生成、求解或工作流执行。当前不读取场数据数组、监视器历史、完整边界条件、网格控制、物性及模型的全部设置；多相子连续体不递归展开。Simulation Operations 输出结构清单，数组位置不代表执行顺序，也不重建条件和循环的控制逻辑。子工作流仅引用，避免引用循环。

## 验证范围

2026-10-28，本机 Linux、STAR-CCM+ 2602 Build 21.02.007 的 `Base.sim~` 已实际读取：32 个标量参数、165 个场函数（3 个用户场函数）、6 个标签、1 个连续体及 18 个模型、2 个区域及 17 个边界、3 个接口、4 个网格操作、6 个报告、15 个监视器和 4 个停止准则。文件及后台会话读取均没有 `read_errors`；除工作副本的名称和路径外，对象快照一致，连续两次会话快照完全一致，服务只加载一次算例。原文件与工作副本 SHA256 未变化，参数原有字段与旧版读取结果一致。验证服务已关闭。

该算例没有 Simulation Operations，工作流非空、嵌套循环及子工作流分支尚未实测；上述固定快照验证也未覆盖向量参数、其他参数类型、读取错误分支及其他 STAR 版本。目录入口已使用另建工作副本验证向量与逐属性错误，见其[独立验证范围](catalog-runtime.md#验证范围与剩余工作)，不将该结果计为全部旧快照迁移完成。Java API 已对照本机安装目录的 `doc/client/html`；实际覆盖以各入口声明的字段及验证范围为准。

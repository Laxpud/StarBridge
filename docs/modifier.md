# Modifier 单项修改

[返回项目入口](README.cn.md) · [Inspector 快照](inspector.md) · [文件入口](bridge-file.md) · [后台会话](bridge-session.md)

`modify` 根据一份 JSON 请求修改一个已有对象。当前支持标量参数表达式、用户场函数表达式，以及已有用户标签关联。每次操作先核对旧状态，再写入并回读；文件入口另存为新文件后重新加载核对。Mesh Controls、Boundary Parameters、Selected Physics Settings 和 Simulation Operations 的修改仍在[当前任务](../TODO.md)中。

## 使用方式

先运行 `inspect`，从目标对象快照提取名称、类型和预期旧属性，再保存请求，例如 `change.json`：

```json
{
  "schema_version": 1,
  "operation": "set-definition",
  "target": {"kind": "parameter", "name": "_AirfoilPitchAmplitude"},
  "expected": {
    "object_type": "ScalarGlobalParameter",
    "definition": "5.0",
    "unit": "deg"
  },
  "value": {"definition": "3 * <1 deg> + 3 * <1 deg>", "unit": "radian"}
}
```

这里的旧表达式和单位来自本项目的示例算例，使用时必须换成当前目标的实际快照。新表达式使用 STAR 的语法；量纲值应明确写单位，如 `<1 deg>`，不能把任意无单位表达式的数值都理解为显示单位下的值。STAR 会把非常量参数表达式的单位切换为 SI，因此请求必须明确写出结果单位：本例原单位为 `deg`，结果单位对象名为 `radian`，实际值为 π/30 rad，即 6 deg。请从 Inspector 的 `si_unit` 取得 SI 单位对象名，不要假设物理单位缩写就是对象名。`value.unit` 不兼容量纲或非常量表达式声明非 SI 结果单位时，在写入前拒绝。纯数值定义可以指定兼容单位，STAR 可能将文本 `6` 规范化为 `6.0`，回读核对会接受这种数值等价。

文件操作：

```bash
python3 bridge/runner/file_bridge.py modify 'Base.sim~' \
  --request change.json \
  --output outputs/Base_modified.sim \
  --work-dir outputs/modify-parameter
```

`--output` 必须是不存在的 `.sim` 文件，父目录必须存在；工作目录也必须全新。执行顺序为核对当前状态、修改、保存前回读、另存、重新加载、比较所有已覆盖对象字段、核对源文件 SHA256。任一环节失败都不生成成功摘要；如果失败发生在另存之后，输出文件可能已存在，应保留排查。

后台会话需要先用 `session_bridge.py start` 启动，再执行：

```bash
python3 bridge/runner/session_bridge.py modify \
  --session-dir outputs/my-session --request change.json

python3 bridge/runner/session_bridge.py save \
  --session-dir outputs/my-session --output outputs/Base_session_modified.sim
```

会话 `modify` 只改变内存；`save` 显式保存。会话保存本身不重新加载文件，独立磁盘核对仍使用文件 `inspect`。每次修改请求保持文件锁串行，不能把它当作与外部 Java 客户端或用户 GUI 之间的事务锁；此原型只管理自己启动的后台服务。

## 请求契约

请求顶层必须且只能有 `schema_version`、`operation`、`target`、`expected`、`value` 五个字段。每份请求只修改一项属性，不接受批量事务、任意 Java 代码、创建、删除或重命名操作。

`target.kind` 可为 `parameter`、`field_function`、`region`、`boundary`。`name` 是 Inspector 中的显示名称，必须精确、唯一匹配；边界还必须有所属区域的 `region` 字段。场函数的显示名称与表达式引用名称 `function_name` 可能不同。

| 操作 | 目标 | 必需的 `expected` 字段 | `value` |
|---|---|---|---|
| `set-definition` | `parameter`，仅 `ScalarGlobalParameter` | `object_type`、`definition`、`unit` | 含非空 `definition` 和结果 `unit` 的对象 |
| `set-definition` | `field_function`，仅 `UserFieldFunction` | `object_type`、`definition`、`function_name`、`value_type`、`dimensions` | 非空表达式字符串 |
| `set-tags` | 上述四种目标类别 | `object_type`、`tags` | 已存在的用户标签名称数组 |

可以直接将目标对象的整个 Inspector 条目作为 `expected`。每个提供的字段都参与旧状态比较；只提供必需字段时，其他属性变化不构成冲突。数量参数的求值可能受其他参数影响，把 `raw_value`、`si_value` 一并放入 `expected` 会使这些变化也触发拒绝。此检查是值比较，不能识别“曾改变后又恢复原值”的历史，也不代表跨会话永久对象身份。

表达式修改保留目标名称、类型、场函数引用名称、值类型和量纲；标量参数的结果单位按 `value.unit` 核对，其他操作保持原单位。回读验证确认的是 STAR 中实际保存的表达式及这些属性，不证明表达式在所有网格、时间或空间位置均可计算，也不验证 CFD 物理意义。读取到错误时不会继续另存；没有读取错误不等于完成了场函数求值。

标签操作**替换完整标签集合**。保留旧标签时必须把它们一并放入 `value`；空数组表示清除全部用户标签关联。名称不存在、不是 `UserTag`，或目标原有关联包含系统标签时，会在写入前拒绝。重复标签名称也会被拒绝，合法数组按名称排序后比较。它不创建或删除标签对象。

例如给某个区域内的边界关联两个已存在标签：

```json
{
  "schema_version": 1,
  "operation": "set-tags",
  "target": {
    "kind": "boundary",
    "region": "Background",
    "name": "BackgroundBlock.Inlet"
  },
  "expected": {"object_type": "Boundary", "tags": []},
  "value": ["Export", "Flow"]
}
```

## 拒绝、失败与结果

请求格式错误在启动客户端或标记会话活动请求之前返回。宏在同一次调用内先读取当前快照、比较 `expected`，再调用写入 API；所需标签也在写入前全部解析。

- `status: rejected`：宏确认尚未调用写入 API，预检查已经拒绝请求。`result.json` 保留错误原因和相同的前后快照。CLI 以非零退出码返回；后台会话保持 `ready`，`last_request_status` 为 `rejected`，可以重新读取后构造新请求。
- `status: ok`：宏已完成写入和回读；文件入口还需通过重新加载核对后才生成成功摘要。
- 超时、客户端异常、写入或回读失败：后台会话进入 `uncertain` 或保留活动请求标记，按[后台会话失败处理](bridge-session.md#身份隔离与失败处理)处理。当前不自动重试、不承诺回滚。

新 `modify` 入口要求修改前后 Inspector 的已覆盖字段全部读取成功。它不能在部分快照上声称已确认操作结果。原有 `set-scalar` 命令继续保留，仍是直接设置常量的入口，没有新增 `expected` 前置条件；需要旧状态保护的表达式修改应使用 `modify`。

文件 `summary.json` 与会话修改结果包含 `modification`、`snapshot` 和 `snapshot_diff`。文件结果另有 `reopened_snapshot_match`。运行目录内的 `request.json` 保存规范化后的请求，`result.json` 保存宏返回的 `before`、`after` 及执行状态；请求和日志沿用文件及会话各自的目录结构。

`snapshot_diff` 记录已覆盖字段的所有变化，包括参数依赖导致的求值变化。每项包含 `path`、`before`、`after`，其中 `path` 是相对于快照根的 JSON Pointer；对象数组按 Inspector 的稳定排序使用下标，标签等标量数组整体记录。比较排除 `simulation_name`、`session_path` 和 `modified` 三个加载元数据字段。Diff 不覆盖完整 STAR 对象树，不能证明所有未读取设置都未变化。


## 已确认的范围

2026-10-28，在本机 Linux、STAR-CCM+ 2602 Build 21.02.007 与 `Base.sim~` 上完成实际操作：文件入口将角度参数表达式设为 `3 * <1 deg> + 3 * <1 deg>`，以 `radian` 回读得到 `0.1047197551196598`，另存后重新加载的已覆盖对象内容一致。错误的 SI 单位名称在写入前被拒绝。

后台会话完成标量常量 `6` 到 `6.0` 的规范化、用户场函数表达式修改、指定区域内边界的用户标签替换。重放旧场函数请求被拒绝，拒绝前后快照一致，会话保持可读取和可保存；显式另存后独立重载的对象内容一致。原文件和初始工作副本 SHA256 未变化，服务 PID 保持不变、算例只加载一次，验证服务已关闭。

没有执行网格或求解；尚未实测其他 STAR 版本、其他量纲参数、系统标签、向量参数、损坏或异常表达式以及写入中断恢复。场函数仅确认表达式保存与回读，没有计算场数据。Mesh Controls、Boundary Parameters、Selected Physics Settings 和 Simulation Operations 的修改仍未实现。

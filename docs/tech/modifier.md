# 旧修改入口迁移

[技术入口](index.md) · [统一 MCP 契约](mcp.md) · [目录修改](catalog-modifier.md)

旧 `set-scalar` 和 schema 1 `modify` 已移除，不再接受 `kind/operation` 请求或把目录结果转换为旧 Inspector 修改结果。已有能力通过统一 `modify_property` 调用；旧请求的 `expected` 不能直接搬到新属性上，应重新查找、描述并读取。

| 原能力 | 查找类型 | 属性 ID | 新值格式 |
|---|---|---|---|
| `set-scalar` 常量 | `scalar_parameter` | `quantity_value` | `{value, unit}` |
| 标量参数表达式 | `scalar_parameter` | `quantity` | `{definition, unit}` |
| 用户场函数表达式 | `user_field_function` | `definition` | 字符串 |
| 参数标签 | `global_parameter` | `tags` | 已有用户标签名称数组 |
| 场函数标签 | `field_function` | `tags` | 已有用户标签名称数组 |
| 区域／边界标签 | `region`／`boundary` | `tags` | 已有用户标签名称数组 |

先用 `find_objects` 取得对象 ID，再通过 `describe_object` 确认实际写入契约，并用 `read_properties` 读取完整旧值。`modify_property` 要求显式 `expected`，包括过去没有该前提的常量赋值。标签新数组替换整个集合；数值常量会替换原表达式，单位须量纲兼容。

会话修改不自动保存；普通赋值只核对目标与必要关联项，完整快照和 Diff 由 `audit=true` 按需取得。独立文件流程仍可用 `modify --catalog ... --execution ... --request ... --output ...`，其 schema 2/3 请求与重载检查见[目录修改](catalog-modifier.md)。

历史 schema 1 验证仅保留作证据，见[原 Modifier 验证记录](../evidence/modifier.md)，不表示已删除入口仍受支持。

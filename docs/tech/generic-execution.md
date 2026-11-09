# 通用执行与工作记忆

[接口入口](<mcp.md>) · [会话管理](<bridge-session.md>) · [需求](<../../StarBridge.md>) · [当前工作](<../../TODO.md>)

AI 直接使用实际版本的 Java API 编写、组合和执行任务宏，这是正常操作方式，不必先尝试结构化接口。已有可靠代码、工作记忆和参数化方法适用时优先复用；需要补查时通过 `search_api`／`read_api` 获取官方资料。结构化属性接口仅在已有契约确实节省成本时作为可选辅助。两者使用同一个已加载会话。通用入口不要求逐功能添加目录适配，也不创建算例副本；生命周期与宏已脱离目录的精确版本名单，但仍要求真实安装检测、所选安装 JDK 预编译和运行时版本／对象身份匹配。未登记版本可尝试通用路径，不因此获得结构化支持或全部 API 已验证的声明。

## 按任务取得实际版本的 API 资料

`search_api(query, installation=...)` 搜索指定安装的官方类名／成员索引，`read_api(java_class, member=..., installation=...)` 读取选中成员的签名、说明、参数／返回约定、弃用信息、文中代码及相关链接。`installation` 是含 `star/` 和 `doc/` 的实际安装根目录，可取安装发现结果的 `javadoc_root`；也可改传已有 `session_id`，此时只读取绑定的安装和版本，不启动客户端。两种来源二选一；会话绑定版本与安装版本材料冲突时拒绝，不使用邻近版本。

例如，任务需要按名称查找场函数时，先以 `FieldFunctionManager getFunction` 查询；选中后读取 `star.common.FieldFunctionManager` 的 `getFunction`。正文明确该方法在未找到时可能创建派生场函数，不能凭方法名把它当成无副作用的读取。继续读取同一类的 `hasObject` 时，返回真实声明类 `star.base.neo.ClientServerObjectManager`，保留其“按显示名称查找、无匹配返回 null”的说明。这是沿官方继承链接取得的依据，不是新增一种场函数专用适配。

- 查询词按空白分词且全部匹配类名和成员标签；不是全文检索、中文语义搜索或独立宏示例库检索。
- `member` 可用简单名称保留重载，也可使用搜索返回的完整签名锚点。指定成员时只返回相关正文；不指定则读取类说明和本类成员的一页，不默认展开全部父类。
- `limit` 默认20、上限100，成功 `result` 另受32 KiB UTF-8 JSON预算，包含计数字段自身，不含封套或协议转义。搜索按完整条目分页；读取将同一 `offset` 的成员（或其错误）和类链接成行返回，两列表共用页边界，分别检查 `next_offset` 和 `links_next_offset` 后传入 `offset` 继续，不把最后一页当成单页覆盖整个选择。
- 类注记可能包含上千个已知子类。超出4000字符的单条类注记返回明确摘录；最低一行连同固定资料仍超预算时，也会摘录必要正文、注记文字或示例。`content_truncations` 列出原长度、返回长度和完整来源；新 `full_text_ref` 是相对 `result` 的 JSON Pointer。签名、来源、继承组和错误不裁剪，最低资料仍无法表示时明确报预算错误，不伪称 API 不存在。截断示例不是完整可执行代码。
- `read_status`、`coverage.errors` 及类级 `links_coverage/content_truncations` 区分索引缺失、局部失败、未返回全文、外部资料未读以及没有匹配。未找到不能推断 API 不存在，分页结束也不表示整套资料已经读取。
- 来源包含实际安装版本、文件路径、内容摘要和成员锚点。进程内缓存有界数量的索引／正文，文件身份或修改信息变化后重新读取；索引扫描、整页 HTML 解析和缓存内存仍无全局预算，不把结果有界等同总成本有界。已有适用资料不必重复查询。

2602／2510 的本机官方资料已实际用于查找、正文读取和继承追溯；2602 的相同读取已通过真实 stdio MCP 调用。此依据只证明所述资料路径可用，不证明任意 API 行为、独立宏库支持或整体需求已完成。

## 从零创建与连续操作

`open_session(create=true, project_dir="/absolute/project", star="/absolute/installation/star/bin/starccm+")` 使用所选安装的 `-server -new` 创建空算例。不传 `input`，不复用别的空算例，也不保存文件。返回的 `session_id` 可用于结构化接口和通用宏。

已有算例仍优先接入匹配的 GUI／服务器，没有匹配时直接加载原文件。不要把每一步都安排成打开、操作、关闭。任务可以停在设置完成后交用户检查；有计算能力不表示必须立即计算。

## 可直接使用的参数化方法

`list_recipes()` 不连接 STAR，返回现成方法的参数、资料依据和完成边界。`execute_recipe(session_id, request_id, recipe_id, parameters)` 使用相同的已加载会话和宏凭据，不必每次从头编写 Java。

| 方法 | 主要参数与边界 |
| --- | --- |
| `mesh.generate` | `kind=surface\|volume`；运行已有配置，不建立几何或证明网格质量。 |
| `solver.step` | `iterations` 为正整数；稳态对应迭代、瞬态对应时间步，返回实际前后计数。 |
| `solver.run` | 沿用当前停止准则，不擅自更改准则或宣称收敛。 |
| `solver.status` | 逐字段报告迭代、时间层和运行标志；局部失败不是零或 false。 |
| `plot.export` | 当前图表的精确 `name`、新绝对 `output`，可指定 `delimiter`。 |
| `table.export` | 当前表的 `name`、新 `output`；仅明确 `extract=true` 才先更新提取。 |
| `report.export` | 当前报告的 `name`、新 `output`；导出 STAR 报告文本，诊断内容仍须检查。 |
| `objects.gui_locations` | 批量绑定当前 `targets`；读取标准树路径、可选属性栏及首层菜单，不读取另一 GUI 窗口布局。参数及状态见[GUI 位置说明](<runtime-discovery.md#gui-显示名称与位置>)。 |

网格和计算先检查已有自动保存。默认 `allow_existing_autosave=false`：若可能触发已有设置，预检查拒绝，计算步骤保持未开始；任务允许时可传 true，保留原设置并报告，而不是擅自关闭用户配置。方法不显式调用保存，但 STAR 本身的自动保存不能被忽略。

内置导出使用最终 `CREATE_NEW`，不会覆盖已有目标。图表／表只暂存新导出的数据，不复制算例。内容写入不是事务，磁盘故障可能留下部分新文件。方法源码和参数未变化时，同一 `request_id` 返回旧凭据；已生成的目标文件不妨碍重放。

工作记忆的方法可在审阅后用 `recipe_id="memory:<memory_id>"` 执行，必须提供 `expected_revision` 和与 `get_memory` 相同的 `project_dir` 范围。未知参数／约束拒绝；未声明影响时按 `mutate` 保守处理。声明为 `object_reference` 的参数使用 `{"object_id":"<当前ID>"}`；执行器在任何用户步骤开始前核对会话和对象身份，再将该位置替换为当前 STAR 对象，支持契约中声明的嵌套对象／数组。普通 JSON 字段不自动转换，历史 ID 不跨会话复用。记忆更新或方法库改变后，查询旧任务使用 `get_execution`，不要改写旧请求。任意记忆 Java 不受内置导出的新文件保护。

## 一次请求中的 Java 步骤

下面是读取已有场函数的格式示例；`name` 是当前对象的程序名 `getFunctionName()`，不是显示名称。先检查存在性：官方 `getFunction` 在未找到时可能创建派生场函数，不能把它无条件当成只读查找。此检查不提供与 GUI 并发编辑的事务隔离。

```json
{
  "session_id": "<current session_id>",
  "request_id": "read-field-definition-01",
  "parameters": {"name": "<current field function name>"},
  "steps": [{
    "id": "read-definition",
    "effect": "read",
    "scope": "当前指定用户场函数的名称与定义，不含其他场函数或求解结果",
    "code": "String name = (String) parameters.get(\"name\"); if (!sim.getFieldFunctionManager().hasFunction(name)) throw new IllegalArgumentException(\"Field function not found\"); UserFieldFunction field = (UserFieldFunction) sim.getFieldFunctionManager().getFunction(name); result.put(\"name\", field.getPresentationName()); result.put(\"definition\", field.getDefinition());"
  }]
}
```

每个步骤必须有 `id`、`effect`、`scope`，并在 `code` 与下文的 `macro` 中二选一；两类步骤可在同一请求中混用：

- `code` 是 Java 方法体。可访问当前 `Simulation sim`、JSON 参数 `parameters`、步骤间的活对象容器 `shared`、本步输出容器 `result`。
- `parameters` 的整数是 Java `Long`，小数是 `Double`，普通对象和数组分别为 `Map`、`List`。参数按数据注入，不执行字符串模板替换。
- `object_parameters` 可显式列出需绑定对象的参数名，例如 `parameters={"part":{"object_id":"<当前ID>"}}`、`object_parameters=["part"]`。这些参数内精确的 `{object_id}` 包装（含嵌套数组／对象）会在所有用户步骤前转换成当前 STAR 对象；Java 可将 `parameters.get("part")` 转型为实际 API 类型。省略此选项时仍为原始 JSON。绑定失败返回 `rejected`，全部用户步骤保持未开始；结果中仍须显式取名称、数值等 JSON 数据，不能直接序列化活对象。
- `imports` 可指定当前安装的类或通配导入；`declarations` 可定义字段、辅助方法和内部类。默认已导入 `star.common.*`、`java.util.*` 和 `java.nio.file.*`。用户代码放在独立 `Payload` 中，身份与全部对象绑定通过、初始化开始凭据写出后才构造；实例字段初始化可用 `sim`、`parameters`、`shared` 和 `getActiveSimulation()`。路径辅助方法沿用入口上下文，但不承诺依赖旧包装类反射身份的代码兼容。
- `effect=read` 声明不修改算例和外部文件；修改设置、创建对象、网格生成、求解、保存和导出用 `mutate`。这是调用者声明，**不是 Java 沙箱或副作用检测**。
- `scope` 说明实际目标和范围。代码须将缺失、不支持和错误明确放入结果或抛出异常，不能用空集合替代未读取。结果容器只接受有限 JSON 值，不隐式序列化 STAR 对象。
- 一个请求最多 200 步、源请求 2 MB。已明确且相关的步骤可集中执行；不为了减少往返扩大范围。前一步失败后，其余步骤保持 `not_started`。

新会话在接入前必须用所选安装 JDK 预编译生命周期模板；宏源码同样在客户端启动前编译，编译拒绝意味着用户步骤尚未开始。仅纯代码步骤的旧会话兼容路径可能将无法定位 JDK 的宏交由 STAR 编译；完整源码模式此时明确拒绝，不派发缺少辅助类的包装器。

### 原样复用完整宏与辅助源码

已有 `StarMacro` 可以直接作为一个步骤，不必拆写 `execute0()`、删除包名或改写 `getActiveSimulation()`：

```json
{
  "session_id": "<current session_id>",
  "request_id": "reuse-recorded-work-01",
  "working_directory": "/absolute/project",
  "steps": [{
    "id": "recorded-work",
    "effect": "mutate",
    "scope": "当前任务明确选择的原宏操作范围",
    "macro": {
      "entry_source": "/absolute/project/macros/Recorded.java",
      "entry_class": "macro.Recorded",
      "sources": ["/absolute/project/macros/Helper.java"],
      "classpath": []
    }
  }]
}
```

- `entry_source` 是原 UTF-8 Java 文件，`entry_class` 是 Java 源码形式的完整类名，须可公开无参数构造并继承 `StarMacro`。`sources` 和 `classpath` 分别明确列出辅助 Java 文件和依赖 JAR，省略为空；不隐式寻找或递归复制工程。源文件保持原字节，按当前安装 JDK 统一编译，禁止隐式寻找其他源文件。STAR 仅编译不含用户代码的薄启动宏，随后加载预编译程序，避免不同编译路径改变用户代码或内联常量；启动宏和包装器使用请求独有类名。入口必须产自本请求源码，调用前还核对实际加载目录。
- 顶层 `working_directory` 是整个客户端的工作目录，影响普通 Java 相对文件路径。完整宏省略时采用共同入口目录；各入口目录不同则要求明确指定。每个宏的 `resolvePath()` 仍按各自原 `entry_source` 位置解析，**不会因源码快照改到请求目录**。纯代码请求省略工作目录时保持原请求目录行为。
- 宏、辅助源码和显式 JAR 字节进入请求指纹，执行使用冻结副本；源码和 JAR 改变后，不能用原请求标识提交新操作。查询旧结果用 `get_execution`，不要求原文件仍存在。全请求最多200个源路径、32个依赖 JAR，完整 JSON 请求仍受2 MB限制；大 JAR 流式摘要／复制的时间和空间计入本次准备成本。
- 原宏的构造和静态初始化遵循普通 Java 语义：框架在对应步骤的 `running` 凭据后检查入口、构造宏，再绑定当前 Simulation 和原路径，直接调用 `execute()`。原宏构造期间不保证 `getActiveSimulation()` 非空；这不同于包装器 `declarations` 已提供上下文的实例字段。整个请求共用类命名空间和静态状态，用户先前的代码也可能主动初始化来源类；不提供逐步骤类版本隔离。显式 JAR、源码产物与安装库之间重名的类在派发前拒绝，即使字节相同也不隐式选择来源；MR-JAR 按各版本类名保守检查，可能多拒绝当前 JDK 不会使用的定义。
- 包装器不会自动把 `parameters/shared/result` 注入原宏，也不解析任意宏内部的业务操作。来源步骤的成功依据是 `entrypoint_returned`，`reported_results=not_provided` 明确表示没有直接取得业务结果；需要时在同请求加入普通回读步骤或读取宏自身产物。宏内部吞异常、嵌套播放、异步任务及交互行为不能由最外层返回值证明完成。
- 冻结 JAR 内的资源可随 JAR 使用；源码旁的 classpath 资源不会自动复制，也不将可变源码目录加入运行 classpath。非空 JAR Manifest `Class-Path` 及旧式 JAR 索引当前拒绝，避免间接查找未冻结依赖；不改写第三方 JAR。原位置的数据文件、原生库及用户代码自行读取的外部内容不在代码快照范围。

来源步骤的结构化结果在可捕获异常后保留 `phase` 和根因，完整堆栈写客户端日志；进程直接中止时，只能依赖此前落盘的状态，不能推断内存阶段已经持久化。`execute_macro`／`get_execution` 的 `artifacts` 列出固定请求材料的路径、大小、可用状态和元数据版本；不默认返回完整日志，所需内容通过下述窗口读取。

### 编译与运行期依赖边界

不能仅凭禁用注解处理，就认定 javac 不会运行编译扩展。实际两套安装的 Temurin 21.0.8+9／21.0.6+7 源码与字节码表明，javac 在编译前仍会发现 `com.sun.source.util.Plugin`、构造提供者并调用 `autoStart()`；返回 false 也不代表构造和该方法没有执行。STAR 的 `NeoScript` 内部同样使用 javac，仅设置空注解处理器列表，并未隔离这一插件路径。这是静态调用链确认，没有构造或运行插件样本。

- Python 调用安装 javac 时，每次创建私有空 `-processorpath`，同时保留 `-proc:none` 和正常的安装库／显式依赖 classpath；相关编译缓存包含此策略，旧证明不会冒充新隔离。具体实现见[java_runtime.py](<../../src/starbridge/bridge/runner/java_runtime.py>)。
- 通用宏向 STAR 显式传入新建空用户 `-classpath`，而非省略参数后回退用户设置。完整源码的[薄启动宏](<../../src/starbridge/bridge/java/StarBridgeLaunch.java>)在自身编译完成后，才用以 STAR loader 为父的独立 `URLClassLoader` 加载本次编译目录和冻结 JAR；不把原源码目录或整个工作目录加入运行 URL。线程 context loader 在调用期间设为该加载器，结束后恢复。
- 保留真实 `working_directory`，不通过改写 `user.dir` 冒充 Java 相对路径一致。STAR 编译还会加入当前目录，因此派发前拒绝其中已有的 `META-INF/services/com.sun.source.util.Plugin`，包括软链接；无法检查也不当作不存在。选定安装、NetBeans 模块、启动环境、父加载器和目录仍受信任，不能抵御同权限进程在检查后改写文件，**不是代码沙箱**。
- 普通运行期类、资源和 SPI 可以使用该加载器；用户再次调用 STAR 的 `play`／`NeoScript` 编译嵌套源码时，不自动继承这些运行 URL。加载器不在同步入口刚返回时关闭，以免异步线程后续懒加载失败；其寿命随客户端结束，并不证明异步工作已完成。

当前独立加载器在[两安装正常源码编译](<../../outputs/requirements-first/launcher-isolation-_9lgu76p/compilation-summary.json>)之后，已用于2602的[入口研究求解与业务回读](<../../outputs/requirements-first/inlet-results/records/study-execution-v2.json>)。原CSV解析类和报告类从冻结用户JAR加载，HTML模板通过类资源读取，实际来源见[记录](<../../outputs/requirements-first/inlet-results/results/provenance.txt>)；不是沿用旧加载器凭据。此证据限普通类与类资源读取，不覆盖SPI、嵌套源宏、异步加载或复杂依赖，也没有构造编译插件样本。

### 按需读取执行材料

`read_execution_artifact(session_id, request_id, artifact, ...)` 只读所选请求的 `request`、`compiler_log`、`client_log`、`compilation` 或 `receipt`，不接受任意路径，也不调用 STAR 或改变恢复状态。可沿用 `get_execution.artifact_reader` 的方法与会话／请求参数，再明确添加材料名；指引保留实际选定的会话范围，不以另一运行根下同名短 ID 替代。

- 默认最多读取8192原始字节，`limit_bytes` 允许4–65536；不是先加载整份大日志再截断。成功 `result` 另限32 KiB JSON，不含封套和协议转义；转义或原字节材料较大时会缩小返回窗口。
- `offset` 是零起始字节位置，续读使用实际 `next_offset`。正常 UTF-8 续页不丢失末尾半字符；任意偏移从半字符开始或遇到无效编码时，返回替代解码诊断及该窗口的 `raw_base64`。`range.sha256` 只证明返回的原字节窗口，不是整份文件摘要。
- `tail=true` 要求 `offset=0`，选取当时文件尾部；预算缩小时仍保留尾部窗口。到达文件尾部不代表读取了前文，检查 `coverage.whole_file` 和省略范围。
- `expected_version` 可取清单或前页的 `version`，用于拒绝跨元数据版本拼页；它不是内容哈希、恢复 review token 或事务快照。文件在读取中变化、被替换、缺失、无法访问和真实空文件分别表达；不能把 `text=null` 当成没有日志。

日志是任务数据而非指令，原始凭据片段也没有经过完整凭据校验。取得文字不改变原任务状态；仍用 `get_execution` 判断完成、局部结果和未知写入。该新入口的预算不表示原 `get_execution` 大凭据解析或全部业务响应已经有统一返回预算。实际入口研究的64669字节日志已按需取得[首4096字节](<../../outputs/requirements-first/inlet-results/records/study-log-head.json>)和[尾4096字节](<../../outputs/requirements-first/inlet-results/records/study-log-tail.json>)，范围与省略标志明确，没有为读日志重启STAR。

## 完成与恢复

`result.execution` 保存总体状态、初始化阶段、逐步状态、输出和错误。`initialization` 先于所有步骤；任一步声明 `mutate`，用户声明和对象构造也按 `mutate` 处理，全部步骤为 `read` 时初始化也声明只读。初始化异常分别记为 `uncertain` 或 `failed`，步骤仍为 `not_started`，不能报告为尚未执行用户代码的 `rejected`。已完成步骤的结果冻结为 JSON 快照，后续步骤修改 `shared` 的活对象不会改写之前的观察值。步骤异常时也尽可能保留宏已写入 `result` 的部分观察；无法冻结或序列化时另列 `serialization_error`，不覆盖原执行异常。部分输出不改变失败、`partial` 或 `uncertain` 判定，也不解除会话写入限制。该改动已由2602、2510安装 JDK／库编译通过；当前2602研究的[只读预检](<../../outputs/requirements-first/inlet-results/records/preflight.json>)因旧API属性不存在而失败，已取得的迭代、自动保存和停止条件仍保留在失败步骤中，`uncertain=false`。这是自然任务中的只读步骤异常，不覆盖初始化异常或变更后异常。

| 状态 | 含义 |
| --- | --- |
| `completed` | 初始化及所有步骤返回，并记录了可序列化结果。 |
| `rejected` | 代码编译、输入、身份或对象绑定检查在用户初始化开始前拒绝。 |
| `failed` | 声明只读的初始化或首个步骤失败；没有宣称任务完成。 |
| `partial` | 至少一个步骤完成，随后步骤失败或结果未知；检查每步状态及 `uncertain`。 |
| `uncertain` | 变更步骤异常或没有最终凭据，不能证明操作未执行。 |
| `running` | 本请求仍活动；不是可以重发的失败状态。 |

`completed` 只表示程序步骤完成，不证明求解已收敛、物理结果可信或异步任务已经结束。调用异步 API 的代码必须根据该 API 的实际运行状态返回结果，不能把“已提交”写成“已计算完成”。

每次操作提供稳定的 `request_id`。同会话相同标识与内容绑定：重发相同内容只读旧凭据；换内容会拒绝，不重复执行。超时、断开或部分完成后先调用 `get_execution(session_id, request_id)`。它读取持久凭据并检查会话状态，不重新连接客户端执行宏。

结果未知时保留已完成项，禁止盲目重放整组步骤。已有或稍后落盘的明确终态可供会话恢复；普通成功读取不能自动解除未知写入。宏结果中的 `active_request`、`uncertain_request`（存在时）说明当前会话仍受哪些限制，与本次 `execution.uncertain` 分开解释：一次读取完成，不代表此前写入已确认。`get_execution` 还返回完整 `session_state`。凭据位于会话运行目录，遵循会话清理周期，不是永久工作记忆。

超时不等于客户端已退出；启动器退出后，其子进程仍可能存活。此时保持活动记录，调用返回 `busy`，不得立即重发。外部会话的 `disconnected` 只表示 Bridge 断开，不证明正在运行的客户端已经停止。派发前记录准备阶段与启动尝试；中断时缺少 PID 不能证明没有启动，也不能据此放开新的写入。

### 根据已有观察接受当前状态

对于仍受限制的通用宏，`get_execution` 分别返回原执行结果、`receipt_read`、`request_activity`、可用时的 `review`，以及已有 `reconciliation`。凭据缺失、损坏、不可读取、超过解析预算和有效内容分别标明；32 MiB 以上只流式计算摘要，完整材料仍在返回路径，不冒充空结果或已完成。

确认前由调用者判断已有依据，只有明确接受当前状态、准备继续时才调用：

```text
reconcile_execution(session_id, request_id, expected_review_token, assessment)
```

- `expected_review_token` 来自最新 `review.token`，绑定原请求、凭据、会话、最近请求及审阅世代。`review.can_accept=false` 时不能继续；未登记客户端身份的异常派发及缺少停止依据的旧记录不会被当作已停止。
- `assessment` 必须说明 `observations`、`accepted_scope`、`remaining_scope`，并列出已有 `evidence=[{source, description}]`。依据可以是原部分凭据、已有读取、产物或用户确认，不要求为确认额外执行验证。系统不自动打开或执行这些来源，也不替调用者认证任意任务的业务结果。
- 确认记录与解除当前限制在同一会话记录内原子更新；不改写原凭据、不重放、不回滚、不保存。历史未知影响仍为未知，`ready` 只说明当前允许继续，不表示旧任务完成。
- 后续查询及操作会识别已接受凭据的变化。新的明确终态可独立恢复；其他变化重新进入待审队列，内容后来恢复也不能复用旧审阅世代。`reconciliation.evidence_current` 指出旧依据是否仍有效。确认历史保留，同一确认重发只返回旧记录，不能清除后来其他请求的限制。

本地会话锁不约束 GUI 编辑或任意 Java 文件写者，不提供跨进程事务或代码沙箱。当前入口只处理通用宏，不用于解除旧结构化修改或保存的未知结果。初始化异常、丢失派发身份及迟到凭据恢复的实际运行仍需继续核查；当前依据是源码复核、已有凭据查询和公开 MCP 契约，不将其写成故障运行已验证。

## 修改、保存与探索的边界

`intent=execute` 表示执行已明确任务，`intent=explore` 表示探索方案；标记本身不授予额外修改权限，也不自动复制算例。Java 代码有完整宏权限，包含保存、删除或导出时，必须属于实际任务授权范围。

内存修改、覆盖保存、另存文件是不同动作。结构化修改不隐式保存；通用宏中的保存调用和 STAR 既有自动保存都可能写文件，不能仅凭代码未调用保存作出保证。自动保存还可能发生在宏凭据写出之后、batch 客户端退出之前，此时凭据中的 `session_path` 不是最终路径。大型算例不默认复制；参数批量任务要求的算例则是任务产物，不能以节省空间为由省略。必要的副本和另存仍由任务及风险决定。

## 工作记忆的记录与使用

四个记忆接口无需 STAR 会话，也不会触发计算或额外验证：

| 方法 | 用途 |
| --- | --- |
| `search_memory(query, context?, limit?, project_dir?, offset?)` | 用已有任务信息检索有界候选摘要；空查询可浏览，按 `next_offset` 继续。完整代码与依据不随搜索返回。 |
| `get_memory(memory_id, project_dir?)` | 获取完整场景、做法、参数约定、例外及依据。 |
| `record_memory(entry, project_dir?)` | 创建新记录；禁止覆盖已有 ID。 |
| `update_memory(memory_id, expected_revision, changes, project_dir?)` | 根据新观察或纠正更新当前修订；冲突先重读，`changes` 是顶层替换。 |

搜索的 `candidates[]` 保留真实 `memory_id/revision/certainty/storage_scope`，`summary` 提供问题、适用条件、做法、实际效果和证据范围的字段摘录；`has_recipe` 与 `material_counts` 标明另有多少材料。每项摘录有 `text/truncated`，结构化说明还标记是否省略其他元数据；首条例外不能代表全部例外。使用 `full_record` 的方法及参数调用 `get_memory`，审阅完整记录并比较当前修订；不从摘要补造代码或未展示的适用条件。

成功搜索的 `result` 最多32 KiB，按默认分隔符的 UTF-8 JSON 计量，不含外层封套或协议转义，也不承诺错误响应预算。到达预算时不跳过候选，`next_offset` 按实际返回数推进；分页、摘要省略及匹配说明摘录通过 `read_status/coverage` 明示。保持原 `query/context/project_dir` 翻页，不用可能已摘录的查询回显重造输入。当前仍完整读取和排序所选层的记录，每页重新计算；累计扫描 I/O、内存和时间未有全局预算，也没有跨页快照。返回更短不等于整个检索过程已经低成本。

记录必填 `problem`、`applicability`、`approach`、`observed_effect`、`source`、`evidence`、`evidence_scope`、`certainty`。说明字段使用文字或带 `description` 的对象；`evidence` 是非空说明列表。未观察效果或未验证范围应直接说明，不因字段必填而额外验证。

`certainty` 区分 `user_rule`、`single_observation`、`validated` 和 `uncertain`。这是带依据范围的记录，不是系统认证；一次成功不能自动成为通用规则。可选 `references` 保存资料及具体位置，`exceptions` 保留例外。

`recipe` 保存完整 `code`、`imports` 和参数契约 `parameters`。每个参数至少有 `type`、`description` 和 `required`；可记录单位及条件。复用前定位当前对象、填写当前参数，不直接复用旧会话 ID、对象名和数值。存储和检索只处理方法数据，不自动执行或替换引用；显式 `execute_recipe` 才按当前契约绑定对象并执行。

默认记忆位于用户运行根的 `memory/`；显式 `project_dir` 启用项目 `.starbridge/memory/` 覆盖层。读取不建目录；写入采用文件锁、修订比较和原子替换。损坏或读取失败明确报告，不伪装成无匹配。当前只保留最新修订，不提供完整历史审计；词法检索也不保证语义召回。

内置 `starccm-unit-expression` 来自需求中的用户规则：`<1 deg>` 正确、`1 <deg>` 错误，明确未额外执行软件验证。

## 当前实际证据与未完成项

2026-11-05 的 STAR 2602 / Build 21.02.007 后台操作已完成：从零创建空算例，在一次约 6.1 秒的客户端调用中创建用户场函数、读取定义并导出 CSV，查询及重复提交均返回同一凭据，随后显式另存并关闭本次自建会话。原始结果：[三步执行](<../../outputs/requirements-first/field-workflow/02-execute_macro.json>)、[请求重放](<../../outputs/requirements-first/field-workflow/04-execute_macro.json>)、[保存](<../../outputs/requirements-first/field-workflow/05-save_session.json>)。随后已重新加载并[读到保存的定义](<../../outputs/requirements-first/reload-02-execute_macro.json>)；该方法已作为单次观察记忆保存，并根据官方文档[修正程序名及查找副作用约束](<../../outputs/requirements-first/memory-update.json>)，没有为记忆另行启动验证。[该阶段 MCP 握手与记忆检索](<../../outputs/requirements-first/mcp-handshake.json>)通过，当时发布22个工具。这些是本机运行产物，不随包提供。

随后在同一安装从零建立了独立的 0.01 × 0.001 × 0.001 m 层流液体通道；各阶段之间保持同一个后台会话，不触碰用户原算例。该阶段的[实际 stdio MCP 枚举、契约／方法查询和记忆检索](<../../outputs/requirements-first/mcp-gui-location-handshake.json>)包含24个工具及8个现成方法；这些是历史接口依据，不是当前默认列表。当前已改为[三个稳定入口与按需格式](<mcp.md#按需取得调用格式>)，下方保留实际任务范围。

| 实际任务 | 结果与证据 |
| --- | --- |
| 执行材料与资料的按需取得 | 当前真实 MCP 在另一运行根的绝对会话范围中[取得原凭据](<../../outputs/requirements-first/bounded-interface-a2nqrbgm/selected-runtime-execution.json>)并沿返回指引读取[715字节原日志](<../../outputs/requirements-first/bounded-interface-a2nqrbgm/selected-runtime-log.json>)，没有丢失范围或重跑 STAR；0.04 m/s、迭代5及变体存在但未重载均是原任务记录。另取得[真实空编译日志](<../../outputs/requirements-first/artifact-reading/compiler_log.json>)、编译信息和请求首／续窗。两安装的[2602](<../../outputs/requirements-first/bounded-interface-a2nqrbgm/21.02.007-session-directory-api.json>)、[2510](<../../outputs/requirements-first/bounded-interface-a2nqrbgm/20.06.007-session-directory-api.json>)继承成员资料均经原生MCP返回，单次result为2927字节。真实官方export索引与RootObject读取另触发整项预算分页；单项最低元数据超限、正文摘录与错误交互仍仅静态复核。 |
| 编译扩展与运行加载边界 | 实际安装JDK及STAR字节码确认两层javac均会发现Plugin，不能把 `-proc:none` 或空注解处理器列表视为插件隔离。外部编译策略已有[两安装正常编译](<../../outputs/requirements-first/compiler-isolation-j4alj1ek/compilation-summary.json>)依据；当前加载器的真实2602求解、用户JAR及HTML类资源范围见[编译与运行期依赖边界](<#编译与运行期依赖边界>)。没有构造插件样本，SPI／复杂依赖与新异常恢复仍未实跑。 |
| 生产翼型配置与既有结果比较 | 2602完整宏在两份NACA0012生产快照中读取网格控制选择与尺寸、区域运动、Cl报告引用及时间表达式，约7.35／7.77秒；同会话定向补读取得尺寸依赖与边界所属区域，未加载第二遍。FA控制的静态选择为空，MeshCorrect明确选中翼面；既有末三周期Cl均值为0.588658／0.571421。详细[结果与限制](<../../outputs/requirements-first/airfoil-comparison/comparison.md>)保留未求值项、未展开项及CSV来源边界，不推断整份设置只差一项、网格精度或因果关系。没有保存、改设置、划网格或求解；用户明确批准后释放本次两个自有会话，两份原始文件前后摘要一致。接入成本与新发现逻辑的覆盖另见[会话说明](<bridge-session.md#验证边界>)。 |
| 原样完整宏与批量工况 | 2602 在已有通道中[混合执行](<../../outputs/requirements-first/inlet-study/execution.json>)基线读取、带包名／私有方法的完整宏及辅助 Java、产物读取，约6.47秒生成0.02／0.04 m/s两个[工况文件记录](<../../outputs/requirements-first/inlet-study/variants/cases.csv>)；保留基线第5次迭代，没有清除数据、重新求解或重载产物。原入口目录的 CSV 与显式 cwd 均按预期使用；[MCP 重放](<../../outputs/requirements-first/inlet-study/mcp-replay.json>)约0.019秒只返回原凭据。当时的薄启动宏通过同会话的[只读清点](<../../outputs/requirements-first/inlet-study/inventory.json>)运行，当前入口实读0.04 m/s，实际内容见[客户端日志](<../../outputs/requirements-first/runtime/sessions/6e54569858b244c0aace25e7e066a301/requests/macro-inlet-study-inventory/star.log>)；当时源码／启动宏也通过[2602](<../../outputs/requirements-first/inlet-study/final-source-build-tped7bzp/21.02.007/compilation.json>)和[2510](<../../outputs/requirements-first/inlet-study/final-source-build-tped7bzp/20.06.007/compilation.json>)编译。本次无额外 JAR，依赖冲突和异常恢复不是本次实跑覆盖；自有服务已停止，基线[前](<../../outputs/requirements-first/inlet-study/source-before.json>)、[后](<../../outputs/requirements-first/inlet-study/source-after.json>)摘要一致。 |
| 当前初始化与已有算例审查 | 2602 在已保存通道中[集中读取边界、材料、迭代状态并导出已有报告](<../../outputs/requirements-first/channel-current-audit/audit.json>)，实例字段初始化使用当前 `sim` 和 `getActiveSimulation()`，初始化及三个步骤均完成。读取入口0.01 m/s、密度1000 kg/m³、黏度0.001 Pa·s；以明确的名义水力直径1 mm推得 Re=10，[出口报告](<../../outputs/requirements-first/channel-current-audit/outlet-current.txt>)为1.016045×10⁻⁵ kg/s。没有新求解，迭代仍为5，不声称收敛；新接入约80.52秒、同会话三步约6.58秒，仅是这次任务观察。自有会话已停止，原算例[前](<../../outputs/requirements-first/channel-current-audit/source-before.json>)、[后](<../../outputs/requirements-first/channel-current-audit/source-after.json>)摘要一致。两安装 JDK 另编译通过现有状态、求解和 GUI 定位方法各三份；初始化异常与显式接受流程未实际触发。 |
| 几何、区域、物理与网格 | 宏创建6面几何和模型；`mesh.generate` 实际运行 parts-based 操作，得到909个单元；用位置报告测得两端面而非猜测面序号。见[网格执行](<../../outputs/requirements-first/channel-workflow/12-execute_recipe.json>)、[测量与配置](<../../outputs/requirements-first/channel-workflow/13-execute_macro.json>)。 |
| 连续求解与结果判断 | 初始[5步计算](<../../outputs/requirements-first/channel-workflow/14-execute_recipe.json>)之后，2602在一个会话和一次[原生MCP请求](<../../outputs/requirements-first/inlet-results/records/study-execution-v2.json>)中连续计算0.02／0.04 m/s两点，累计5→155→305，分别保存场文件及逐迭代历史。两个50步窗口的守恒、流量和静压差稳定性均达本次阈值；压差为5.967401／13.352415 Pa，不认证网格独立性或工程精度。详细口径、解析参照及旧字段命名歧义见[结果解读](<../../outputs/requirements-first/inlet-results/results/interpretation.md>)。完整宏和报告库直接复用，没有增加入口研究专用接口。成功请求约7.83秒，首次加载另约79.34秒，不是端到端耗时；自有会话已释放，选定基线／旧变体／输入材料摘要不变。 |
| 导出与重放 | `plot.export` 导出[5点监视器 CSV](<../../outputs/requirements-first/channel-workflow/outlet-mass-flow.csv>)，`report.export` 生成[报告文本](<../../outputs/requirements-first/channel-workflow/outlet-mass-flow.txt>)；同一导出请求[重放](<../../outputs/requirements-first/channel-workflow/18-execute_recipe.json>)约0.001秒，没有再次导出。 |
| 通用选择读取 | SurfaceCustomMeshControl 的 GeometryObjects 返回6个 PartSurface，TagGroup 明确为空，EnableControl 为 true；[暖读取](<../../outputs/requirements-first/channel-workflow/22-read_properties.json>)在一次客户端调用内核对对象／描述符并取值，约5.727秒。此处为初次静态观察；后续动态配置与关联写入见下方。 |
| 保存与释放 | [保存的小算例](<../../outputs/requirements-first/channel-workflow/channel.sim>)保留求解结果；保存时 dirty=false，后续连接又为 true，默认关闭正确拒绝。第二次保存不再遍历完整快照，仍观察到此现象，原因未确定。仅对本任务自建、已保存的临时会话显式丢弃剩余内存并[停止](<../../outputs/requirements-first/channel-workflow/27-close_session.json>)；不得推广为自动丢弃用户会话。随后重新加载并[读回迭代数5及完全一致的5点历史](<../../outputs/requirements-first/channel-workflow/reload-02-execute_macro.json>)；只读重载会话也在显式释放后停止，原文件未改写。 |
| 关联导航与静态写入 | [六个选择对象](<../../outputs/requirements-first/reference-workflow/06-read_properties.json>)取得当前 `object_id`，其中一个关联面的[描述](<../../outputs/requirements-first/reference-workflow/07-describe_object.json>)及[标签读取](<../../outputs/requirements-first/reference-workflow/08-read_properties.json>)成功；[六面替换为二面](<../../outputs/requirements-first/reference-workflow/12-modify_property.json>)记录一次 setter。真实 descriptor 的 filters 与 clone 均为 null，与 Javadoc 不符；[只读诊断](<../../outputs/requirements-first/reference-workflow/11-execute_macro.json>)后修正为保持原态，不将 null 当空筛选。将 PartSurface 赋给标签选择在[可选域检查](<../../outputs/requirements-first/reference-workflow/22-modify_property.json>)中拒绝。 |
| 动态选择配置 | 明确宏设置名称查询后，[读取](<../../outputs/requirements-first/reference-workflow/14-read_properties.json>)保留 `Matches` 谓词、参数与 modifiers，并标明未请求求值；再[显式替换为静态选择](<../../outputs/requirements-first/reference-workflow/15-modify_property.json>)，一次 setter 并清除查询。这不证明查询命中集已枚举。 |
| 对象参数与方法复用 | [直接绑定关联对象](<../../outputs/requirements-first/reference-workflow/17-execute_macro.json>)命名第一个面；将该自然任务方法记入项目记忆后，[按修订复用](<../../outputs/requirements-first/reference-workflow/19-execute_recipe.json>)命名第二个面。原关联 ID 在重命名后仍可[描述实际对象](<../../outputs/requirements-first/reference-workflow/21-describe_object.json>)。配置显式另存为[选择设置算例](<../../outputs/requirements-first/reference-workflow/selection-settings.sim>)，没有为这些设置重新求解；原通道文件 SHA-256 与修改前记录一致。任务结束后已[停止自建会话](<../../outputs/requirements-first/reference-workflow/42-close_session.json>)。 |
| 局部失败与重放 | [数组对象参数宏](<../../outputs/requirements-first/reference-workflow/23-execute_macro.json>)先读到两个当前名称，随后只读步骤明确失败，末步保持未开始；总体 `partial`、`uncertain=false`。查询原凭据与[相同请求重放](<../../outputs/requirements-first/reference-workflow/25-execute_macro.json>)均保留此结果，重放约0.002秒、不再连接 STAR。 |
| 另一实际安装的通用路径 | STAR 2510 / Build 20.06.007 [新建接入](<../../outputs/requirements-first/reference-workflow/27-open_session.json>)、[字段配置](<../../outputs/requirements-first/reference-workflow/30-execute_macro.json>)、[记忆方法读取](<../../outputs/requirements-first/reference-workflow/32-execute_recipe.json>)及[最小生命周期保存](<../../outputs/requirements-first/reference-workflow/33-save_session.json>)成功，随后释放自建会话。空算例的网格方法因缺少 MeshPipelineController [失败](<../../outputs/requirements-first/reference-workflow/29-execute_recipe.json>)，没有开始生成；该失败不是自动保存保护的证据。未登记版本仍没有真实运行证据。 |
| GUI 先加载与重复接入 | 2602 GUI 独立加载自建设置算例，随后[接入](<../../outputs/requirements-first/gui-workflow-v2/01-open_session.json>)为 `external`；[再次打开](<../../outputs/requirements-first/gui-workflow-v2/03-open_session.json>)返回相同会话 ID 与 token，没有重载。区域重命名直接出现在[原 GUI 工作树](<../../outputs/requirements-first/gui-workflow-v2/gui-after-save.png>)中；接入后的操作没有另开 GUI 或重载算例。 |
| 派发后、登记 PID 前中断 | 控制流在真实客户端创建后中断，[返回未知](<../../outputs/requirements-first/gui-workflow-v2/06-execute_macro.json>)并[阻止新写入](<../../outputs/requirements-first/gui-workflow-v2/08-execute_macro.json>)。客户端实际将标记从1改为2后等待任务确认；放行后读取[迟到的最终凭据](<../../outputs/requirements-first/gui-workflow-v2/10-get_execution.json>)恢复 ready，[原请求重放](<../../outputs/requirements-first/gui-workflow-v2/11-execute_macro.json>)不再次递增。 |
| 活动请求中的外部断开 | 标记变为3后，显式终止本任务的控制进程，登记客户端仍存活；[断开后的执行查询](<../../outputs/requirements-first/gui-workflow-v2/15-get_execution.json>)正确返回 `running`，会话是 `disconnected`、服务器仍活着。放行后[重连](<../../outputs/requirements-first/gui-workflow-v2/16-open_session.json>)沿用原 ID／token，并[取得完成结果](<../../outputs/requirements-first/gui-workflow-v2/17-get_execution.json>)。 |
| 变更后异常与只读检查 | [变更步骤抛错](<../../outputs/requirements-first/gui-workflow-v2/18-execute_macro.json>)返回 `partial`、`uncertain=true`，末步未开始；只读取得标记4，但[会话仍保留未知写入](<../../outputs/requirements-first/gui-workflow-v2/20-get_execution.json>)，[保存被拒绝](<../../outputs/requirements-first/gui-workflow-v2/21-save_session.json>)。未宣称失败前的变更已回滚。 |
| 超时与不重发 | 只读客户端等待期间触发10秒超时，启动器退出后仍有同组进程，[状态保持 running](<../../outputs/requirements-first/gui-workflow-v2/24-get_execution.json>)且再次提交返回 busy。进程结束后无最终成功凭据，[查询](<../../outputs/requirements-first/gui-workflow-v2/26-get_execution.json>)明确读取结果未知；[随后重放](<../../outputs/requirements-first/gui-workflow-v2/27-execute_macro.json>)只返回原凭据，原有变更的写入限制仍在。 |
| 最终凭据与进程组收尾 | 新控制进程加载最终恢复源码后，宏步骤[返回 completed 且客户端返回码为0](<../../outputs/requirements-first/final-recovery-workflow/02-execute_macro.json>)，同组的自有 IPC 等待进程仍存活；结果保留 `active_request`，[新操作被 busy 拒绝](<../../outputs/requirements-first/final-recovery-workflow/03-execute_macro.json>)。放行等待进程后，[状态恢复 ready](<../../outputs/requirements-first/final-recovery-workflow/04-get_execution.json>)。 |
| 无终态的只读收尾 | 自有只读客户端在10秒处超时，等待结束后直接退出、不写最终凭据；[查询](<../../outputs/requirements-first/final-recovery-workflow/06-get_execution.json>)返回结果未知，但会话为 ready、`last_request_status=error`、无活动请求，不再把中间 running 留作末次状态，也不因只读失败冻结写入。 |
| 当前响应保留先前限制 | 自有内存标记改为2后抛错；随后[成功读取的响应](<../../outputs/requirements-first/final-recovery-workflow/08-execute_macro.json>)同时给出本次 `uncertain=false` 和先前变更的 `uncertain_request`，[保存仍被拒绝](<../../outputs/requirements-first/final-recovery-workflow/09-save_session.json>)。该会话已[显式丢弃本次临时内存并停止](<../../outputs/requirements-first/final-recovery-workflow/22-close_session.json>)，未写回自建源文件，其 SHA-256 保持一致。 |

GUI 操作只在初次配置后显式另存[设置算例](<../../outputs/requirements-first/gui-workflow-v2/gui-configured.sim>)，其中标记为1、区域名为 `SB_GUI_Phase_1`；后续中断与异常中的标记2至4只留在内存，没有为设置变更重新求解。最后 Bridge [断开后服务器仍存活](<../../outputs/requirements-first/gui-workflow-v2/29-session_status.json>)，[原窗口仍显示标记4的区域](<../../outputs/requirements-first/gui-workflow-v2/gui-after-detach.png>)；随后才由任务入口[释放本次自建 GUI 进程](<../../outputs/requirements-first/gui-workflow-v2/gui-cleanup.json>)。释放前后两个自建保存文件的大小和 SHA-256 一致，用户原算例未参与这些操作。

真实网格运行暴露了此前预检查的遗漏：`AutoSaveBatch=true`、`AutoSaveMesh=false` 仍在宏凭据写出后生成了[自动检查点](<../../outputs/requirements-first/runtime/sessions/8f12cc01fa5d4b8f826a4e22855701cf/star@meshed.sim>)，见[日志:343–350](<../../outputs/requirements-first/runtime/sessions/8f12cc01fa5d4b8f826a4e22855701cf/requests/macro-channel-volume-mesh-1/star.log#L343-L350>)。该文件保留，未掩盖或删除。现已将 batch 标志纳入体网格与表面网格风险。修正后在2602已配置的小算例中，关闭自动保存时[体网格方法正常返回](<../../outputs/requirements-first/reference-workflow/02-execute_recipe.json>)；在单独显式保存的自有设置会话启用 batch 后，[默认调用被自动保存保护拒绝](<../../outputs/requirements-first/reference-workflow/35-execute_recipe.json>)，生成步骤保持未开始，并恢复此前的临时设置。表面网格仍是保守推断。通用方法不会为通过保护擅自改变用户配置。自动另存改变根名后，旧引用被拒绝，使用原 locator 重定位后成功读取。

当前 Java helper 与最小生命周期模板均通过2602、2510安装自身 JDK／库编译；两份随附计划各24类型、142属性通过离线编译。此前恢复阶段的源码下，既有 Core 检查9项通过、1项因仍访问旧 HMAC `_discovery_secret` 而报错，见[原检查:175–191](<../../tools/validation/discovery_contract_checks.py#L175-L191>)；[Java 模拟检查](<../../tools/validation/discovery_java_contracts.py>)的替身没有新增生产依赖 `StarBean`、`ObjectNameFactory`，编译失败，当前未执行其6项检查。这与使用实际安装库的编译及真实任务结果分开记录，不能把旧阶段的6项通过沿用为最终结果。没有改写检查来掩盖这些不匹配，也没有新增测试文件。

不存在的 `Simulation.setPresentationName` 及错误的 Java 泛型已在派发前编译拒绝。上述 GUI 与失败操作覆盖实际列出的场景，不证明所有异常、结构化写入或未登记版本均已验证。旧 GUI 操作入口没有热重载 Python，其超时凭据中残留的 `last_request_status=running` 也没有被事后改写；最终恢复源码的行为以上述新控制进程实跑为依据。

GUI 对应呈现现已提供独立现成方法：复用当前 Simulation 的官方标准节点模型，批量取得对象祖先、属性栏标签和首层菜单文本，不把拥有者链冒充 GUI 路径。实际范围、局部失败及另一窗口／子菜单等边界统一见[GUI 显示名称与位置](<runtime-discovery.md#gui-显示名称与位置>)。工作记忆只记录已有任务观察及资料，没有为提高记忆可信度额外计算。连续入口研究实际[取回并使用了上轮记录](<../../outputs/requirements-first/inlet-results/records/reused-memory.json>)，随后把本轮结果、来源代码、资源和例外[记录为单次观察](<../../outputs/requirements-first/inlet-results/records/recorded-memory.json>)；生产翼型比较随后直接复用了选择输入读取经验，按当前安装API编写完整宏，并将本次真实静态读取范围[补入原记忆修订](<../../outputs/requirements-first/airfoil-comparison/records/updated-selector-memory.json>)；动态选择与写入依据仍限原通道，不因新增只读观察而扩大。这些复用不表示大规模记忆扫描及宏材料获取的成本问题已解决。

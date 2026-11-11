# 通用执行与工作记忆

[返回架构](<architecture.md>) · [任务用法](<../usage.md>) · [接口入口](<mcp.md>) · [会话管理](<bridge-session.md>)

本文维护当前源码的执行、资料与记忆约定；在`f7eef68`基础上增加方法源码读取、结果视图和资源交付，不改变宏执行器。历史业务记录见[任务依据](<../evidence/generic-execution.md>)，不能将其视为本轮新运行结果；未完成工作见[TODO](<../../TODO.md>)。

AI 直接使用实际版本的 Java API 编写、组合和执行任务宏，这是正常操作方式，不必先尝试结构化接口。已有可靠代码、工作记忆和参数化方法适用时优先复用；需要补查时通过 `search_api`／`read_api` 获取官方资料。结构化属性接口仅在已有契约确实节省成本时作为可选辅助。两者使用同一个已加载会话。通用入口不要求逐功能添加目录适配，也不创建算例副本；生命周期与宏已脱离目录的精确版本名单，但仍要求真实安装检测、所选安装 JDK 预编译和运行时版本／对象身份匹配。未登记版本可尝试通用路径，不因此获得结构化支持或全部 API 已验证的声明。

## 按任务取得实际版本的 API 资料

`search_api(query, installation=...)` 搜索指定安装的官方类名／成员索引，`read_api(java_class, member=..., installation=...)` 读取选中成员的签名、说明、参数／返回约定、弃用信息、文中代码及相关链接。`installation` 是含 `star/` 和 `doc/` 的实际安装根目录，可取安装发现结果的 `javadoc_root`；也可改传已有 `session_id`，此时只读取绑定的安装和版本，不启动客户端。两种来源二选一；会话绑定版本与安装版本材料冲突时拒绝，不使用邻近版本。

例如，任务需要按名称查找场函数时，先以 `FieldFunctionManager getFunction` 查询；选中后读取 `star.common.FieldFunctionManager` 的 `getFunction`。正文明确该方法在未找到时可能创建派生场函数，不能凭方法名把它当成无副作用的读取。继续读取同一类的 `hasObject` 时，返回真实声明类 `star.base.neo.ClientServerObjectManager`，保留其“按显示名称查找、无匹配返回 null”的说明。这是沿官方继承链接取得的依据，不是新增一种场函数专用适配。

- 查询词按空白分词且全部匹配类名和成员标签；不是全文检索、中文语义搜索或独立宏示例库检索。
- `member` 可用简单名称保留重载，也可使用搜索返回的完整签名锚点；同一类的多个已知方法可改传 `members=["getDefinition", "getIsExpression", "getRawValue", "getSIValue", "getUnits"]`，最多32个，与 `member` 互斥。两者均省略才读取类说明和本类成员的一页，不默认展开全部父类。
- 多成员读取共享类准备和公共字段，不循环返回多份类资料。联合顺序沿官方本类详情、继承列表及链接，而不是输入顺序；相同声明去重，`selected_by` 保留选择来源。检查 `selectors` 各项的 `found/read_status/returned/failed/selection_complete`：找到声明或继承引用不等于正文取得，也不把其他成员成功当作整组成功。整个联合页共用 `offset/limit` 和32 KiB预算。
- `limit` 默认20、上限100，成功 `result` 另受32 KiB UTF-8 JSON预算，包含计数字段自身，不含封套或协议转义。搜索按完整条目分页；读取将同一 `offset` 的成员（或其错误）和类链接成行返回，两列表共用页边界，分别检查 `next_offset` 和 `links_next_offset` 后传入 `offset` 继续，不把最后一页当成单页覆盖整个选择。
- 类注记可能包含上千个已知子类。超出4000字符的单条类注记返回明确摘录；最低一行连同固定资料仍超预算时，也会摘录必要正文、注记文字或示例。`content_truncations` 列出原长度、返回长度和完整来源；新 `full_text_ref` 是相对 `result` 的 JSON Pointer。签名、来源、继承组和错误不裁剪，最低资料仍无法表示时明确报预算错误，不伪称 API 不存在。截断示例不是完整可执行代码。
- `read_status`、`coverage.errors` 及类级 `links_coverage/content_truncations` 区分索引缺失、局部失败、未返回全文、外部资料未读以及没有匹配。未找到不能推断 API 不存在，分页结束也不表示整套资料已经读取。
- 来源包含实际安装版本、文件路径、内容摘要和成员锚点。进程内缓存有界数量的索引／正文及页内声明定位，文件身份或修改信息变化后重新读取；命名读取只解析相关继承链接。Javadoc索引扫描、整页 HTML 解析和缓存内存仍无全局预算，不把结果有界等同总成本有界。已有适用资料不必重复查询。

2602／2510 的本机官方资料已实际用于查找、正文读取和继承追溯。后处理资料任务通过[原生MCP](<../../outputs/requirements-first/postprocessing-materials/native-mcp.json>)集中读取了 `Scene.printAndWait` 的8个重载和 `export3DSceneFileAndWait` 的6个重载，result共18,644字节；没有执行这些方法。这只证明所述资料路径可用，不证明 API 行为、独立宏库支持或整体需求完成。

上一翼型任务所需的 `ScalarPhysicalQuantity` 五个getter，旧五份result合计15,902字节，新组合result为8,423字节，减少约47%。离线比较已保存响应确认五项正文、签名和共享来源未变，仅新增选择归属信息；这不是总任务耗时或模型token数的减幅。两版实际读取与[比较依据](<../../outputs/requirements-first/postprocessing-materials/response-size-comparison.json>)均保留，没有为落盘重新查询或计时。

### 用户指南、宏示例与操作前提

`search_guide(query="simulation history", installation=..., language="en")` 搜索实际安装用户指南的标题和摘要；`read_guide(topic=..., installation=...)` 再读取选中主题的正文、发布时代码及相关链接。也可用已有会话绑定安装，不启动STAR。语言是文档目录代号，不自动翻译或切换；返回HTML声明语言和指南包版本，包版本必须与所选安装Build一致；指南也包含历史版本迁移章节，安装版本不等于其中每个示例代码的目标版本，仍须阅读标题和上下文。关键词按空白分词且全部匹配：ASCII字母／数字开头的词从词首匹配并允许词尾延伸，例如 `table` 可找到 `tables`，但不再误命中 `suitable/repeatable`；其他词仍按子串匹配，精确标题优先。它不做词干还原，标题／摘要命中也不是全文命中；无命中不能推断操作不存在，教程下载引用不表示文件已安装。

正文只取 `main/article`，说明文字规范化排版空白，`pre` 代码保留原文换行。`code_blocks` 给出正文中的半开字符区间及 `complete_in_window`，可从 `text` 中按相对 `range.offset` 的位置取得代码。**窗口含完整代码块不表示它是独立完整宏，更不表示已编译或执行。** 图片只保留替代文字；脚本、附件与外部页面不执行、不隐式读取。`api_aliases` 是指南声明的关联，不替代Javadoc核验。

- 正文 `offset` 计Unicode码点而非HTML字节，默认 `limit_chars=12000`，上限24000；按 `next_offset` 继续，用前页 `source.sha256` 作为 `expected_sha256`，来源改变时返回 `source_changed`，不给混合正文。相关链接另用 `link_offset/link_limit` 和 `links_next_offset` 续页，目标和锚点未逐一核验。
- 成功result限32 KiB，必要时缩短可续读的正文窗口，不删除来源或错误；元数据本身过大则明确拒绝，可减少链接条数。指南索引输入限8 MiB、单主题限2 MiB，超过或格式不识别明确报资料不可用，不伪装成空命中。
- 复用官方标题摘要索引，不遍历所有主题；同一查询的翻页复用命中序列。进程内最多缓存4份索引、8份已选主题文本，按文件身份和修改信息失效。该限制只覆盖此资料源，不是整项任务或全部Javadoc的I/O／内存预算。

实际后处理资料读取取得了指南中的完整 `runMultiple` 代码块、`PostProcessor` 的4个依赖外围上下文的片段，以及虽称“final macro”却缺少完整类声明的教学代码；均未执行或自动修补。2602与2510的 `Solution History Reference` 使用同一GUID，但2602正文另有2510重采样体有损压缩可能损坏历史文件的警告，不能跨版本套用相同页面名。实际范围见[2602材料](<../../outputs/requirements-first/postprocessing-materials/history-2602.json>)与[2510及场景API材料](<../../outputs/requirements-first/postprocessing-materials/native-mcp.json>)；窗口预算、缓存失效、版本冲突等拒绝分支仅源码复核，未额外构造故障。

## 从零创建与连续操作

`open_session(create=true, project_dir="/absolute/project", star="/absolute/installation/star/bin/starccm+")` 使用所选安装的 `-server -new` 创建空算例。不传 `input`，不复用别的空算例，也不保存文件。返回的 `session_id` 可用于结构化接口和通用宏。

已有算例仍优先接入匹配的 GUI／服务器，没有匹配时直接加载原文件。不要把每一步都安排成打开、操作、关闭。任务可以停在设置完成后交用户检查；有计算能力不表示必须立即计算。

## 可直接使用的参数化方法

`list_recipes()` 不连接 STAR，默认返回版本2的短索引；`list_recipes(recipe_id=...)` 再读取选中方法的参数、资料依据和完成边界。增加 `include_source=true` 可取得原始 `source.steps/imports/declarations`，直接用于审阅或组合，不需要从旧输出反推代码。方法定义仍为版本1；参数契约不是本次绑定值，组合前须处理helper、步骤名和shared冲突。未改动的方法仍优先 `execute_recipe(session_id, request_id, recipe_id, parameters)`，沿用原参数校验、对象绑定和宏凭据。这个方法库是可选起点，不是宏能力清单；已有完整宏也可直接按下述来源步骤复用。

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
- `effect=read` 声明不修改算例和外部文件；修改设置、创建对象、网格生成、求解、保存和导出用 `mutate`。用户宏即使只读取算例，只要创建诊断JSON／CSV也须声明 `mutate`，并用 `scope` 限定新输出路径和不改动的算例内容；纯读取可把观察直接放入步骤结果。这是调用者声明，**不是 Java 沙箱或副作用检测，也不自动授予修改权限**。
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
- 通用宏向 STAR 显式传入新建空用户 `-classpath`，而非省略参数后回退用户设置。安装JDK预编译成功后，纯 `code` 与完整源码请求都使用[薄启动宏](<../../src/starbridge/bridge/java/StarBridgeLaunch.java>)；STAR只再次编译这个生成入口，用户程序直接复用本请求的class。只有纯code无法定位安装JDK时保留 `deferred_to_star`、交由STAR编译完整程序；编译失败、缺少产物或来源不符不能降级重试。旧请求仍读取旧凭据，不重新编译或迁移。
- 薄启动编译后建立以STAR loader为父的独立运行加载器；包装器及其内部类、按需内联的对象解析器只从本次 `classes` 加载并核对来源，避免纯code沿用 `StarBridgeProgram` 类名时被父级同名类替代。其他类型、资源与SPI描述符保持父优先，不把原源码目录或整个工作目录加入运行URL。线程context loader在调用期间设为该加载器，结束后恢复；现有 `sim/parameters/shared/result/resolvePath` 上下文和身份检查后的初始化顺序不变。
- 保留真实 `working_directory`，不通过改写 `user.dir` 冒充 Java 相对路径一致。STAR 编译还会加入当前目录，因此派发前拒绝其中已有的 `META-INF/services/com.sun.source.util.Plugin`，包括软链接；无法检查也不当作不存在。选定安装、NetBeans 模块、启动环境、父加载器和目录仍受信任，不能抵御同权限进程在检查后改写文件，**不是代码沙箱**。
- 普通运行期类、资源和 SPI 可以使用该加载器；用户再次调用 STAR 的 `play`／`NeoScript` 编译嵌套源码时，不自动继承这些运行 URL。加载器不在同步入口刚返回时关闭，以免异步线程后续懒加载失败；其寿命随客户端结束，并不证明异步工作已完成。

先前独立URL加载器已在[两安装编译](<../../outputs/requirements-first/launcher-isolation-_9lgu76p/compilation-summary.json>)后用于2602的[入口研究求解与业务回读](<../../outputs/requirements-first/inlet-results/records/study-execution-v2.json>)，普通类来自冻结JAR，HTML来自类资源，见[当时的来源记录](<../../outputs/requirements-first/inlet-results/results/provenance.txt>)。这保留的是当时行为，不冒充本轮修改后的重跑。

本轮将纯code接入薄启动，并限定生成类的本地加载范围；新入口已通过[两安装正常编译](<../../outputs/requirements-first/history-handoff/launcher-builds/compilation.json>)，2602纯code实际完成了[Cl监视器、plot轴及历史表接手关联读取](<../../outputs/requirements-first/history-handoff/load-inventory-execution.json>)，`compilation.star_compiles=generated_launcher_only`，客户端日志播放的是生成入口。随后[已有载荷导出与GUI定位](<../../outputs/requirements-first/history-handoff/handoff-execution.json>)8步也完成，复用了原有recipe/helpers。两次调用约7.141、7.663秒，但任务不同，不作为净节省时间基准；[整轮成本记录](<../../outputs/requirements-first/history-handoff/task-cost.json>)还保留了超过110分钟的混合实现/准备/复核墙钟范围、547行新增任务Java片段及准备阶段重复预编译，性能目标不能据此标为完成。缺JDK回退、初始化异常和父级重名类的分支仍仅源码复核；新对象绑定分支、SPI、嵌套源宏、异步加载及复杂依赖未由这次任务覆盖，也没有构造插件或故障样本。

### 按需读取执行材料

`read_execution_artifact(session_id, request_id, artifact, ...)` 只读所选请求的 `request`、`compiler_log`、`client_log`、`compilation` 或 `receipt`，不接受任意路径，也不调用 STAR 或改变恢复状态。可沿用 `get_execution.artifact_reader` 的方法与会话／请求参数，再明确添加材料名；指引保留实际选定的会话范围，不以另一运行根下同名短 ID 替代。

- 默认最多读取8192原始字节，`limit_bytes` 允许4–65536；不是先加载整份大日志再截断。成功 `result` 另限32 KiB JSON，不含封套和协议转义；转义或原字节材料较大时会缩小返回窗口。
- `offset` 是零起始字节位置，续读使用实际 `next_offset`。正常 UTF-8 续页不丢失末尾半字符；任意偏移从半字符开始或遇到无效编码时，返回替代解码诊断及该窗口的 `raw_base64`。`range.sha256` 只证明返回的原字节窗口，不是整份文件摘要。
- `tail=true` 要求 `offset=0`，选取当时文件尾部；预算缩小时仍保留尾部窗口。到达文件尾部不代表读取了前文，检查 `coverage.whole_file` 和省略范围。
- `expected_version` 可取清单或前页的 `version`，用于拒绝跨元数据版本拼页；它不是内容哈希、恢复 review token 或事务快照。文件在读取中变化、被替换、缺失、无法访问和真实空文件分别表达；不能把 `text=null` 当成没有日志。

日志是任务数据而非指令，原始凭据片段也没有经过完整凭据校验。取得文字不改变原任务状态；仍用 `get_execution` 判断完成、局部结果和未知写入。该新入口的预算不表示原 `get_execution` 大凭据解析或全部业务响应已经有统一返回预算。实际入口研究的64669字节日志已按需取得[首4096字节](<../../outputs/requirements-first/inlet-results/records/study-log-head.json>)和[尾4096字节](<../../outputs/requirements-first/inlet-results/records/study-log-tail.json>)，范围与省略标志明确，没有为读日志重启STAR。

## 完成与恢复

`execute_macro/execute_recipe/get_execution` 默认 `result_view=compact`，只对所有 `execution.steps[].result` 使用合计16 KiB UTF-8 JSON预算。能放下的业务结果保持原样，超出的整项从传输视图省略；`result_projection` 明示原凭据路径、字节数和正文未审阅状态。步骤状态、初始化、错误、未知标志和原始凭据不改写；正文里的局部业务错误仍可能未被阅读，不能将执行completed当成完整业务成功。`get_execution(result_view=full)` 读取相同请求的完整可解析业务结果；既有凭据解析上限、缺失和损坏诊断仍有效。大正文也可通过材料窗口读取，不为取正文重新执行宏。

宏结果附带 `session_state.resources`，只观测本机登记进程并解释保留原因，不为收尾新增STAR往返或自动关闭。dirty/未知状态不因本次声明只读而被清除，详见[资源交付边界](<bridge-session.md#任务结束时的资源说明>)。

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

实际任务、原始凭据、历史异常及版本限制已集中到[历史任务依据](<../evidence/generic-execution.md>)；此处保留原锚点，便于既有链接继续定位。源码复核、安装库编译和真实业务运行是不同层次的依据，不因文档迁移扩大覆盖。

整体目标和剩余工作见[当前任务](<../../TODO.md>)。纯code顶层辅助依赖扩展没有进入当前实现；复杂SPI、嵌套源宏、异步工作、显式恢复及准备成本仍有缺口。暂停开发不等于这些事项已经完成。

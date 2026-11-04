# 目录写入与结构操作验证记录

[当前技术说明](../tech/catalog-modifier.md) · [技术入口](../tech/index.md)

以下为从原专题移出的既有记录，保留当时的实现、版本与验证范围；不代表后续改造已通过相同实测。

## 验证范围与迁移边界

以下保留既有目录实现的历史实测结果；其中的全快照检查和失败后阻断读取属于当时行为。当前会话与写入简化的运行验证边界统一见[会话说明](../tech/bridge-session.md#验证边界)，不能用旧记录替代新链路实测。

2602 的既有嵌套工作流副本已通过 `workflow_settings` 的单对象定位，完整读取五个管理器属性，并通过 `workflow` 读取两条既有工作流。选择先切到 `_SnapshotChild 1`，再切到 `_SnapshotMain 1`，回读引用一致，已有工作流集合与执行关联保持。错误 key、跨会话引用、过时旧关联和不存在的工作流均在准备时拒绝；拒绝前后完整管理器状态一致。反向条件临时映射另外验证声明式 guard 的拒绝路径，会话保持 `ready`；真实运行中的工作流状态尚未实测。

会话另存并关闭后，文件入口从主工作流切回子工作流，独立重载时完整目录、旧快照及输入摘要核对通过；文件修改前状态也与会话保存前跨加载规范化一致。六种非法 singleton 声明被拒绝，旧 schema 7 保持集合定位。产物在本地 `outputs/catalog-workflow-20261029/`；没有执行工作流、网格或求解，未验证块创建/重排/删除、子工作流链接修改或并发切换。2510 的对应映射已按其自身声明加载校验，尚无该新增路径的真实运行证据。

本机 2602 Build 21.02.007 已在现有 MeshBackground → Auto Mesh → Base Size 完整读取六个属性，将尺寸改为 `12.5 mm`，再改为 `${_MeshBackgroundBaseSize} * 1.1`（SI 结果单位 `m`）；第二次预览按原 input 的 `mm` 范围检查，验证了 SI 值与范围单位换算。零值、负常量、负表达式、缺失参数和错误量纲均在准备时拒绝，前后完整状态一致，会话保持 `ready`。带旧引用改指 MeshSliding 下同名控制时按 key 拒绝，另一个源网格的尺寸定义保持原值。

该会话已另存并关闭，文件入口重新加载后全部属性与保存前跨会话规范化一致；再修改为 `15 mm`，目录、快照重载及输入摘要核对均通过。六种非法范围声明被拒绝，旧 schema 6 仍可加载且默认不启用范围检查；候选目录重复生成一致，原有 211 个类型记录未变。产物在本地 `outputs/catalog-mesh-20261029/`。本批未生成网格或求解，未实测整数范围、温度偏移/差量单位、其他网格控制或并发依赖变化。

本机 2602 Build 21.02.007 已在工作副本的 Inlet `Turbulence Intensity` 验证标量数值和定义写入，在 Top `Velocity` 验证向量分量和定义写入；后者的常量方法由夹具显式选择，不算产品方法切换能力。标量完整 11 属性、向量完整 14 属性均可回读，方法对象、边界类型、区域、物理连续体、向量坐标系和维数保持不变。现有 Inlet 的函数向量方法、错误单位、过时旧数量、错误 key、错误父路径以及开启局部表面值的状态均在写入前拒绝；拒绝未改变方法身份或数量。按表面值开关由夹具显式恢复后，完整状态与此前一致。

标量与向量分别保存后通过文件入口修改并独立重载；文件修改前的目录状态与保存前一致，修改后目录和旧快照重载均匹配，输入摘要未变。额外不变项另用独立会话与故意矛盾的临时映射验证：将所写数量的别名属性声明为不变项后，日志明确报告写后不一致，会话进入 `uncertain` 并阻止后续读取，随后显式放弃该副本，未重试写入或保存。schema 6 的声明格式拒绝及旧 schema 5 默认空列表也已核对。产物位于本地 `outputs/catalog-domains-20261029/`；未运行网格或求解，未覆盖局部表面值写入、函数/数组 Profile 写入、边界或 Profile 方法切换和并发修改。


本机 2602 Build 21.02.007 已在工作副本的 `_SelectionReport` 上验证注释谓词八个算子、`includes` 的 `All`/`None`、身份规则的空集合、单项和区域加边界多项，回读保留文本、算子和完整对象集合。空文本与中文文本均保持；组合规则同时包含 includes、comment、identity 和已有 tag 分支。此批未求查询匹配结果或报告值，不把成功保存规则等同于规则匹配到预期对象。

过期会话引用、错误 key、重复身份对象、缺失对象和过时旧规则均在 setter 前拒绝，拒绝前后报告目录状态一致，会话保持 `ready`。体积平均报告的静态“区域加边界”选择由过滤模型拒绝，两个区域的静态选择通过；同样的区域加边界身份查询可以保存，体现动态规则与静态选择的不同约束。旧身份集合改变数组顺序及 token/key 后仍按名称、实际类和数量核对，其余规则字段保持严格比较。本地契约检查另拒绝 Placeholder、includes 多余 value、错误身份集合形状、不允许的对象类型、缺失边界父路径以及错误注释算子/值。

会话保存关闭后，文件修改前的完整报告目录状态与保存前跨加载规范化一致；文件入口将嵌套身份规则从 `Equals` 改为 `DoesNotEqual`，其他规则及报告属性保持，目录与旧快照独立重载匹配，输入摘要未变。产物位于本地 `outputs/catalog-query-extended-20261029/`。本批未运行网格或求解，未覆盖元数据、继承部件等谓词、并发变更或中断恢复；这些规则继续明确拒绝。目录候选重复生成一致，原有类型声明未变化。


本机 2602 Build 21.02.007 已在已有二维/三维有限元源导数张量上验证自带方向轴的方法。两种维数均沿 Symmetric → PrincipalWithAxes → AxisymmetricWithAxis → PrincipalWithAxes → Composite → Symmetric → Isotropic → PrincipalWithAxes 完成产品切换，按真实布局回读主值、全部轴及矩阵分量。主值 `XX Component` 分别写入三维 `13.5`、二维 `9.25`；主方向和轴对称方向轴均通过原始向量写入，主方向 Y 轴还通过向量定义写入。切回主方向后已修改设置保持。三维 Y 轴关联了夹具创建的 `_PrincipalAxisY 1`，X 轴仍关联 `Laboratory`；坐标系创建与关联选择属于夹具准备，不计为产品写入能力。

旧向量、错误单位、旧目标引用、过时嵌套坐标关联、当前函数轴写入、含函数轴的源方法切换，以及含函数轴的未活动目标方法切换共七类请求均在 setter 前拒绝。函数轴使完整 `method_state` 报错，但 `axes` 和标量 `components` 仍可枚举，另一根常量轴可单独写入；恢复夹具前核对父方法和函数轴 key 均未被拒绝请求改变。旧二维/三维多孔正交、横观各向同性路径及分量读取也已通过回归，其旧状态没有新增 `direction_axes` 字段。

会话保存并关闭后，二维/三维完整状态、轴集合及嵌套坐标关联与独立加载结果一致。文件模式把二维 X 轴写为 `[3,1,4]` 并重载，轴仍报告 `is_3d: false`、`size: 2`，原始非零第三项保持；随后对另一区域执行 PrincipalWithAxes → AxisymmetricWithAxis，双层重载核对均通过，再读二维完整状态确认除所写轴数量外其余设置保持。原输入摘要未变，产物位于本地 `outputs/catalog-principal-20261029/`。

该批检查未运行网格或求解，不证明方向向量的物理合理性、全部有向转换、函数轴数量适配、坐标系内部设置、并发变更或中断恢复。目录中两个结构操作的实现总数不变，本批覆盖报告仅记录当前目录 ID 下实际执行的张量操作、三个属性写入入口及各自文件重载样例；材料操作证据仍以前一批的明确范围为准。


本机 2602 Build 21.02.007 已通过产品 schema 3 入口验证材料导热率 Anisotropic → Constant → Orthotropic → Anisotropic 的切换，分别完整回读常量数量、三项和六项系数；常量值 `237 W/m-K`、既有正交 `k22=150.75 W/m-K` 和返回各向异性后的独立设置保持。`describe` 报告导热率三个映射选项可用、密度仅常量可用，并明确按映射类查找的范围。

过时源状态、错误目标引用、密度选择不可用的导热方法，以及未活动正交 `k22` 使用函数方法时的切换，均在 setter 前拒绝，会话保持 `ready`。最后一项同时核对拒绝后的父方法和目标系数 key 未变；显式恢复夹具后正交系数仍为原值。原 Profile 的 Anisotropic → Orthotropic → Anisotropic 切换、选项枚举描述和材料系数 schema 2 写入均通过回归；`k12` 更新为 `10.5 W/m-K`，父物性全部七个属性可完整读取。

会话另存并关闭后，材料完整状态和 Profile 操作状态与独立文件加载结果一致；文件模式另完成 Anisotropic → Orthotropic，目录与旧快照重载核对及原输入摘要核对均通过。产物位于本地 `outputs/catalog-material-operation-20261029/`。本次没有运行网格或求解，也未验证所有有向转换、其他材料方法、并发变更或中断恢复；按类查找不能证明全部方法已枚举。当前覆盖报告分别记录两个结构操作的成功样例、三个材料目标方法及一个材料操作文件重载样例，不等同于全分支覆盖。

本机 STAR-CCM+ 2602 Build 21.02.007 的固体材料导热系数已完成代表性会话读写：连续体 `_TensorSolidMaterial` 下按 `Solid` → `Al` → `Thermal Conductivity` → 系数的完整路径定位，父物性全部六个属性、系数子对象全部五个属性均可完整读取。各向异性方法的 `k12` 数值从 `0` 改为 `7.5 W/m-K`，`k11` 常量表达式从 `237` 改为 `250`；正交方法三项状态完整，`k22` 数值改为 `150.75 W/m-K`。该批系数验收中的材料方法选择由夹具显式完成，不作为产品结构操作证据，新增产品方法切换验收见本节开头。该批夹具切回各向异性后，其独立设置仍为 `k11=250`、`k12=8.5`、`k13=0`、`k22=237`、`k23=0`、`k33=237`。

将各向异性 `k13` 显式设为函数方法后，父 `basis`、`coefficients` 仍可读，完整 `coefficient_state` 与该系数数量明确报错；`k13` 写入拒绝，兄弟常量系数 `k12` 仍能从 `7.5` 改为 `8.5`。恢复夹具确认函数方法的原 key 未变，读取和拒绝检查没有隐式切换方法。过时数量、`deg` 单位、错误子对象 key、错误连续体路径、函数系数，以及切至正交方法后沿用同名 `k11` 的旧引用，共六类请求均在 setter 前拒绝，会话保持 `ready`。

有限元 `ViscousFlowModel` 与 `GeneralizedNonNewtonianModel` 的专用 Fluid 区域提供了真实 `Momentum Source Velocity Derivative` 对称张量。夹具选择实际可用的 `CompositeSymmetricTensorProfileMethodWithCoordinateSystem`，记录 Laboratory 坐标系和 XY/YX 相同对象 key。三维读取全部 24 个父目标属性，状态含下三角六项；`xy_value` 写为 `3.5` 后 `xy`、`yx` 数量一致，basis 保持不变。二维通过实际名为 `XY & YX Component` 的子对象写入 `5.5`，完整方法状态回读 `shape: [2,2]` 和下三角三项。该方法选择仅用于夹具准备，未扩展产品的 `set_method` 选项。

材料文件修改将各向异性 `k12` 从 `8.5` 改为 `10 W/m-K`，独立重载的目录、旧快照及原输入摘要核对均通过；文件修改前的系数五个属性也与保存前会话结果一致。随后文件修改把三维对称 `yx` 从 `3.5` 改为 `4.25`，重载后 `xy=yx=4.25`，全部 24 个目标属性及坐标 basis 核对通过。独立读取最终文件的材料父物性，完整六属性中仅 `k12` 数量按请求改变，其他系数、方法及 basis 一致；二维对称方法状态和分量集合也与保存前一致，数值 `5.5` 保留。

上述两个文件修改的 `reopened_catalog_match`、`reopened_snapshot_match`、`input_unchanged` 均为 `true`。起始副本和原 `Base.sim~` 的 SHA256 未变，验收会话已关闭、文件进程已结束，未运行网格或求解。产物位于本地 `outputs/catalog-material-20261029/`。这些检查只证明所述导热系数和源导数张量样例；其他材料、方法、方向设置及更广的模型与结构操作仍未覆盖。

本机 STAR-CCM+ 2602 Build 21.02.007 的单相多孔阻力已完成当前分量子对象的二维/三维验收：Anisotropic、Orthotropic、Isotropic、Transverse Isotropic 的独立分量数分别为二维 `4/2/1/2`、三维 `9/3/1/2`。每种布局均按父对象返回的实际分量名称及引用读取子对象全部五个属性，并修改一个代表性分量；数值与纯数值表达式写入交替验证，回读的分量身份、当前方法和父张量 basis 保持一致。二维和三维均完成 Anisotropic → Orthotropic → Isotropic → Transverse Isotropic 切换；这不代表所有有向转换均已验证。

过时数量、单位不兼容、子对象引用 key 不匹配、切换后已不活动的分量，以及非常量分量写入均在 setter 前拒绝，会话保持 `ready`。XX 显式改为函数方法后，父 `components` 与子 `basis` 仍可读，完整 `method_state` 和 XX 数量明确报错；ZZ 常量分量仍可写，随后确认 XX 的函数方法 key 未变，再由夹具显式恢复。原三维 `xx_value` 写入通过全部 24 个父目标属性回读，二维调用原 `xz_value` 在三维条件处拒绝。二维子对象的 `describe` 返回两项已满足的实际条件。

会话保存后，文件入口独立加载二维横观各向同性分量，将其从 `23.25` 改为 `24.5 kg/m^3-s`；目录、旧快照的独立重载核对及输入摘要核对均通过。跨加载按契约移除方向引用的 token/key 后，保存前后的子对象五个属性一致；父张量的分量引用集合和完整方法状态也与独立加载结果一致。产物位于本地 `outputs/catalog-components-20261029/`，该次验证未运行网格或求解。后续材料系数和对称方法的已确认范围见本节开头，所关联坐标系或 `LocalOrientation` 的内部设置仍未验收。

本机 2602 Build 21.02.007 已在单相多孔工作副本验证 `set_method`：按 Anisotropic → Orthotropic → Isotropic → TransverseIsotropic → Anisotropic 顺序切换，完整回读对应的 9/3/1/2 项独立分量及方向引用。`describe` 返回四种当前可选方法、条件及影响范围；多相阻力的 `MixturePorousViscousResistanceMethod` 单独列为 `unmapped_methods`，未被标成可执行选项。

过时旧状态、临时映射中当前不可用的方法，以及未活动目标方法的 X 分量改为 `FunctionScalarProfileMethod` 后的切换请求，均在 setter 前拒绝，会话保持 `ready`。夹具恢复后，原 schema 2 `xx_value` 写入仍通过全部 23 个目标属性回读；会话另存并独立加载，方法状态和分量值一致。文件模式另从样例输入执行 Anisotropic → Orthotropic，快照与目录的保存重载核对、原输入摘要核对均通过。验证会话已关闭，产物位于本地 `outputs/catalog-operation-20261029/`。

上述证据覆盖具体转换路径，未证明四种方法间的所有有向转换、不同初始分量方法、所关联坐标系或 `LocalOrientation` 的内部设置或中断恢复。结构操作只检查完整活动设置及选定方法的未活动设置，不核对所有其他未活动方法的内部配置，也不判断切换后的物理合理性。覆盖工具分别记录操作、目标方法和文件重载样例，不把它们计为普通属性写入或全分支验收。

本机 STAR-CCM+ 2602 Build 21.02.007 的单相 `_TensorSinglePorous` 区域，已在工作副本中显式将 `Porous Viscous Resistance` 从初始 Orthotropic 方法切换到实际可用的 `AnisotropicTensorProfileMethod`，随后由 Bridge 读取 `full` 九分量、`kg/m^3-s` 单位和 `LocalOrientation` 引用，并将 `xx_value` 从 `0` 写为 `10` 后回读成功。`xy` 写入常量表达式 `3` 后回读为 `3.0`，`yx` 仍为 `0`，确认该 full 方法的上下三角是独立分量。该次方法切换由验收夹具准备完成，不作为目录结构操作的验收证据。

夹具显式将 XX 分量切换到实际允许的 `FunctionScalarProfileMethod` 后，普通 `modify` 在 `constant_component` 条件检查处拒绝，会话保持 `ready`；随后核对该 Function 方法的对象 key 未变，确认拒绝没有暗中切回 Constant。夹具显式恢复后，XX 仍为 `10`、XY 仍为 `3`。多相 `_TensorPorous` 的 Mixture 方法，以及 `Background` 中不存在的同名 Profile 均在写入前拒绝，会话保持 `ready`。会话另存为 `saved.sim` 后，文件入口读取的全部 22 个已配属性与保存前恢复后的会话结果在跨加载引用规范化后相同。文件 `modify` 将 `yx_value` 写为 `4` 并另存 `file-modified.sim`，`reopened_catalog_match`、`reopened_snapshot_match` 和 `input_unchanged` 均为 `true`；独立重载回读 XX=`10`、XY=`3`、YX=`4`，九分量保持 full 存储，`basis`（含 `LocalOrientation` 引用）规范化后一致。原 `Base.sim~` 的 SHA256 未变，验收会话已关闭。本轮没有运行网格、求解或报告求值，产物位于本地 `outputs/catalog-tensor-20261028/`。

本地映射校验接受只读空 `steps`，拒绝空写入管线。对称方法的二维三项、三维六项及上下三角别名，以及材料系数的代表性读写、拒绝和保存重载，已有本节开头所述证据；其他未适配方法仍待完成。原矩阵属性仍保留三维边界。

本机 STAR-CCM+ 2602 Build 21.02.007 的 `_SelectionReport` 体积平均报告已由 `Pressure` 关联到 `Density`，`value_checks` 记录 `scalar_field_function` 的预期和实际值均为 `SCALAR`。`parts` 已完成名称查询→静态 `Background` 区域→嵌套查询→空静态选择→同一嵌套查询的回读；嵌套规则为 `And(Type Is Region, Or(Name Matches Background, Tag Contains AirfoilMotion))`，保留 `PrefilterNamedObjects` 修饰符。

非标量 `Velocity`、不存在的场函数、跨会话新引用、重复静态对象、非法正则 `[` 和过时选择旧值均被写入前拒绝，会话保持 `ready`。本地校验拒绝不允许的关联类型、`java.lang.Runtime` 类型谓词、未知算子、深度 `17` 和 `257` 个节点的规则，并确认旧 schema 2/3 执行映射仍可加载。`describe` 返回场函数的 `value_types: ["field_function"]`、值条件 `SCALAR`，且 `conditions_checked` 保持 `false`。

会话保存后，文件 `modify` 将报告由 `Density` 改回 `Pressure`，嵌套标签查询保持不变；完整快照与目录内容的重载核对及输入摘要核对均通过。文件修改前的全部已配目录属性也与会话恢复后的结果跨加载规范化一致，确认原 `Density` 关联和嵌套标签规则均已持久化。原 `Base.sim~` 摘要未变，会话均已停止，未执行报告求值、网格或求解。本轮静态选择只验证单个区域与空集合；边界选择、多对象选择、其他谓词算子、未知谓词类型，以及并发或中断场景尚未实测。运行产物位于 `outputs/catalog-selection-20261028/`。

本机 STAR-CCM+ 2602 Build 21.02.007 已完成新增写入的内存回读：`ignore_boundary_values` 从 `false` 改为 `true`、`value_type` 从 `SCALAR` 改为 `VECTOR`、向量分量写入 `[2.25, -3.5, 4.75]`、向量表达式写入 `[5, -6, 7]`，以及重力分量写入 `[0, -9.8, 0] m/s^2`。重力修改的 `catalog_before.checks` 记录 `gravity_model_enabled` 的预期值和实际值均为 `true`。

没有重力模型的 `_NoGravity` 连续体被明确条件消息拒绝；过时布尔旧值及不兼容的 `m` 单位也被拒绝，三者会话均保持 `ready` 且最后请求状态为 `rejected`。本地请求校验拒绝用数值 `1` 写入布尔属性、非法枚举值、长度为 2 的向量和包含布尔分量的向量，并确认 schema 2 的 `primitive` 仍规范化为 `field_definition`。当时 `describe` 仅核对重力条件摘要；当前目标条件的实际检查范围见[目录描述验证](catalog-runtime.md#验证范围与剩余工作)。

会话另存后，文件 `modify` 将向量改为 `[8, -9, 10]` 并另存，`reopened_snapshot_match`、`reopened_catalog_match` 和 `input_unchanged` 均通过。再次独立加载该输出，用户场函数、向量和重力的全部已配目录属性与对应修改结果一致，完整快照也与文件摘要一致；原 `Base.sim~` 和输入 `fixture-saved.sim` 的摘要未变。未执行求解；本轮向量表达式只验证常量形式，重力只验证分量写入，动态向量表达式、其他枚举选项及其他单位尚未验证。本地运行产物位于 `outputs/catalog-typed-write-20261028/`。

本机 Linux、2602 Build 21.02.007 已通过文件标量表达式修改：由 `5 deg` 改为上例 `6 deg` 表达式，回读 SI 单位，另存重载后的旧快照和目录内容均一致，源文件 SHA256 未变。后台同一服务已完成 `quantity_value` 写入 `8 deg`、用户场函数定义写入 `0`、边界标签完整替换为 `AirfoilMotion`；重放旧数量预期值被明确拒绝，随后 `inspect` 成功且会话保持 `ready`。

不兼容量纲的单位和不存在的用户标签均在写入前拒绝。通过专用故障映射制造 setter 执行后的回读值不符时，操作失败并使会话进入 `uncertain`，后续 `inspect` 被阻断，未把写入后失败误报为 `rejected`。这项检查不覆盖进程崩溃或中断恢复。本地运行产物位于 `outputs/catalog-write-20261028/`。

正常会话修改显式另存后，已独立加载 `session-saved.sim`：完整旧快照与保存结果一致，标量、场函数、边界三个目标的全部已配目录属性也与对应修改结果一致，跨加载引用按上述规则规范化。原始 `Base.sim~` 的 SHA256 保持不变。

以上没有执行网格或求解，也不代表其他 STAR 版本、其他量纲、所有标签目标、系统标签、模型状态或中断恢复均已验证。其余值类型写入与结构操作仍见 [TODO](../../TODO.md)；已有结果可通过[分项覆盖报告](../tech/catalog.md#分项覆盖报告)统计具体读写与重载证据；Inspector 快照目录迁移与验收见[快照说明](../tech/inspector.md)。

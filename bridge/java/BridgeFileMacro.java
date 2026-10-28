import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.function.BiConsumer;
import java.util.function.Supplier;
import java.util.List;
import star.base.neo.NamedObject;
import star.base.neo.ClientServerObject;
import star.common.*;
import star.automation.*;
import star.base.report.*;
import star.meshing.*;

/**
 * 在 STAR 已加载的算例中读取对象清单、设置标量或显式另存，供文件与会话 Runner 共用。
 * Runner 替换配置占位符；本宏不生成网格、不执行求解。
 */
public class BridgeFileMacro extends StarMacro {
    private static final String RESULT = __RESULT__;
    private static final String ACTION = __ACTION__;
    private static final String EXPECTED_SESSION = __EXPECTED_SESSION__;
    private static final String OUTPUT = __OUTPUT__;
    private static final String NAME = __NAME__;
    private static final String UNIT = __UNIT__;
    private static final double VALUE = __VALUE__;

    @Override
    public void execute() {
        try {
            Simulation sim = getActiveSimulation();
            // 常驻请求先核对工作文件身份，避免把请求发到其他已打开的算例。
            if (!EXPECTED_SESSION.isEmpty()
                    && !Path.of(sim.getSessionPath()).toRealPath().equals(
                        Path.of(EXPECTED_SESSION).toRealPath())) {
                throw new IllegalArgumentException("Unexpected simulation session: " + sim.getSessionPath());
            }
            if (!List.of("inspect", "set-scalar", "save", "file-set").contains(ACTION)) {
                throw new IllegalArgumentException("Unknown action: " + ACTION);
            }
            // 1. 先读取对象与参数快照，便于区分目标修改与依赖值变化。
            String before = snapshot(sim);
            if (ACTION.equals("save") || ACTION.equals("file-set")) {
                if (OUTPUT.isEmpty()) throw new IllegalArgumentException("Output is required");
                if (Files.exists(Path.of(OUTPUT))) {
                    throw new IllegalArgumentException("Output already exists: " + OUTPUT);
                }
            }
            if (ACTION.equals("set-scalar") || ACTION.equals("file-set")) {
                NamedObject object = sim.get(GlobalParameterManager.class).getObject(NAME);
                if (!(object instanceof ScalarGlobalParameter)) {
                    throw new IllegalArgumentException("Not a scalar global parameter: " + NAME);
                }
                ScalarPhysicalQuantity quantity = ((ScalarGlobalParameter) object).getQuantity();
                Units units = sim.getUnitsManager().getObject(UNIT);
                if (units == null || !quantity.getUnits().compatible(units)) {
                    throw new IllegalArgumentException("Unknown or incompatible unit: " + UNIT);
                }
                // 2. 此入口明确把目标设置为数值常量；原表达式会由 before 保留。
                quantity.setValueAndUnits(VALUE, units);
            }
            // 会话的 set-scalar 只改内存；只有显式 save 或旧文件入口才保存。
            if (ACTION.equals("save") || ACTION.equals("file-set")) {
                sim.saveState(OUTPUT);
            }
            // 3. 成功标记在另存及回读结束后写出；Runner 不只依赖 STAR 退出码。
            // 只读请求复用同一次快照，避免重复查询，并保证 before 与 after 一致。
            String after = ACTION.equals("inspect") ? before : snapshot(sim);
            Files.writeString(Path.of(RESULT),
                "{\"status\":\"ok\",\"before\":" + before + ",\"after\":" + after + "}",
                StandardCharsets.UTF_8);
        } catch (Exception error) {
            throw new RuntimeException("StarBridge macro failed", error);
        }
    }

    /**
     * 读取已覆盖对象的属性与关系，不遍历任意 Bean 属性，也不计算报告值。
     * 各集合独立记录错误；空集合只有在对应位置没有 read_errors 时才表示确实为空。
     * inspection_complete 仅表示本版声明的字段均成功读取，不代表完整 STAR 设置。
     */
    private String snapshot(Simulation sim) {
        Map<String, Object> result = new LinkedHashMap<>();
        List<Map<String, Object>> errors = new ArrayList<>();
        result.put("schema_version", 1);
        result.put("simulation_name", sim.getPresentationName());
        result.put("session_path", sim.getSessionPath());
        result.put("modified", sim.isModified());

        // 1. 参数保留原有字段；场函数保留可引用名称、值类型及用户表达式。
        result.put("parameters", collect("parameters",
            () -> sim.get(GlobalParameterManager.class).getObjects(), (object, entry) -> {
                if (object instanceof ScalarGlobalParameter) {
                    scalar(entry, ((ScalarGlobalParameter) object).getQuantity());
                } else if (object instanceof VectorGlobalParameter) {
                    VectorPhysicalQuantity q = ((VectorGlobalParameter) object).getQuantity();
                    List<Double> components = new ArrayList<>();
                    for (double component : q.getRawVector().toDoubleArray()) components.add(component);
                    entry.put("definition", q.getDefinition());
                    entry.put("unit", q.getUnits().getPresentationName());
                    entry.put("raw_value", components);
                } else {
                    entry.put("unsupported", true);
                    throw new UnsupportedOperationException("Unsupported global parameter type");
                }
            }, errors));
        result.put("field_functions", collect("field_functions",
            () -> sim.getFieldFunctionManager().getObjects(), (object, entry) -> {
                entry.put("function_name", object.getFunctionName());
                entry.put("value_type", object.getTypeAsEnum().name());
                entry.put("dimensions", object.getDimensions().toString());
                entry.put("user_defined", object instanceof UserFieldFunction);
                if (object instanceof UserFieldFunction) {
                    entry.put("definition", ((UserFieldFunction) object).getDefinition());
                }
            }, errors));
        result.put("tags", collect("tags", () -> sim.get(TagManager.class).getObjects(),
            (object, entry) -> {}, errors));

        // 2. 模型放在所属连续体内，边界放在所属区域内，避免同名子对象发生混淆。
        result.put("continua", collect("continua", () -> sim.getContinuumManager().getObjects(),
            (object, entry) -> {
                entry.put("regions", references(object.getRegions()));
                entry.put("models", collect("continua/" + object.getPresentationName() + "/models",
                    () -> object.getModelManager().getObjects(), (model, detail) -> {}, errors));
            }, errors));
        result.put("regions", collect("regions", () -> sim.getRegionManager().getObjects(),
            (object, entry) -> {
                entry.put("region_type", object.getRegionType().getClass().getSimpleName());
                entry.put("physics_continuum", reference(object.getPhysicsContinuum()));
                entry.put("boundaries", collect("regions/" + object.getPresentationName() + "/boundaries",
                    () -> object.getBoundaryManager().getObjects(), (boundary, detail) -> {
                        detail.put("boundary_type", boundary.getBoundaryType().getClass().getSimpleName());
                    }, errors));
            }, errors));
        result.put("interfaces", collect("interfaces", () -> sim.getInterfaceManager().getObjects(),
            (object, entry) -> {
                entry.put("interface_type", object.getInterfaceType().getClass().getSimpleName());
                if (object instanceof BoundaryInterface) {
                    BoundaryInterface boundary = (BoundaryInterface) object;
                    entry.put("enabled", boundary.getEnabled());
                    entry.put("boundary0", boundaryReference(boundary.getParentBoundary0()));
                    entry.put("boundary1", boundaryReference(boundary.getParentBoundary1()));
                }
            }, errors));

        // 3. 操作只读取身份、关联和配置；报告不调用会求值的 getReportMonitorValue。
        result.put("mesh_operations", collect("mesh_operations",
            () -> sim.get(MeshOperationManager.class).getObjects(), (object, entry) -> {
                entry.put("index", object.getIndex());
                entry.put("input_parts", references(object.getInputGeometryObjects().getObjects()));
            }, errors));
        result.put("reports", collect("reports", () -> sim.getReportManager().getObjects(),
            (object, entry) -> {
                entry.put("unit", object.getUnits() == null ? null : object.getUnits().getPresentationName());
                if (object instanceof ExpressionReport) {
                    entry.put("definition", ((ExpressionReport) object).getDefinition());
                }
            }, errors));
        result.put("monitors", collect("monitors", () -> sim.getMonitorManager().getObjects(),
            (object, entry) -> {
                entry.put("enabled", object.getEnabled());
                if (object instanceof ReportMonitor) {
                    entry.put("report", reference(((ReportMonitor) object).getReport()));
                }
            }, errors));
        result.put("stopping_criteria", collect("stopping_criteria",
            () -> sim.getSolverStoppingCriterionManager().getObjects(), (object, entry) -> {
                entry.put("enabled", object.getIsUsed());
                if (object instanceof StepStoppingCriterion) {
                    entry.put("definition", ((StepStoppingCriterion) object).getDefinition());
                    entry.put("maximum_steps", ((StepStoppingCriterion) object).getMaximumNumberSteps());
                } else if (object instanceof PhysicalTimeStoppingCriterion) {
                    Map<String, Object> maximum = new LinkedHashMap<>();
                    entry.put("maximum_time", maximum);
                    scalar(maximum, ((PhysicalTimeStoppingCriterion) object).getMaximumTime());
                }
            }, errors));
        result.put("simulation_operations", collect("simulation_operations",
            () -> sim.get(SimDriverWorkflowManager.class).getObjects(), (object, entry) -> {
                entry.put("blocks", blocks(object.getBlocks(),
                    "simulation_operations/" + object.getPresentationName() + "/blocks", errors));
            }, errors));

        // 4. 即使一个类别失败，也交出其他类别；调用方必须检查完整性和错误位置。
        result.put("inspection_complete", errors.isEmpty());
        result.put("read_errors", errors);
        return json(result);
    }

    /** 统一数量字段：raw_value 使用 unit 所示单位，si_value 使用 SI 单位。 */
    private void scalar(Map<String, Object> entry, ScalarPhysicalQuantity quantity) {
        entry.put("definition", quantity.getDefinition());
        entry.put("unit", quantity.getUnits().getPresentationName());
        entry.put("raw_value", quantity.getRawValue());
        entry.put("si_value", quantity.getSIValue());
    }

    /**
     * 读取工作流中的操作及嵌套循环；子工作流只存引用，避免沿引用形成循环递归。
     * 返回名称排序的结构清单，不把集合位置解释为控制流或实际执行顺序。
     */
    private List<Map<String, Object>> blocks(AutomationBlockManager manager, String location,
                                             List<Map<String, Object>> errors) {
        return collect(location, manager::getObjects, (object, entry) -> {
            if (object instanceof LoopAutomationBlock) {
                entry.put("blocks", blocks(((LoopAutomationBlock) object).getBlocks(),
                    location + "/" + object.getPresentationName() + "/blocks", errors));
            } else if (object instanceof SubWorkflowAutomationBlock) {
                entry.put("workflow", reference(((SubWorkflowAutomationBlock) object).getSubWorkflow()));
            }
        }, errors);
    }

    /**
     * 按名称与类型排序并逐项读取，某项失败仍保留该项身份与已经读取的字段。
     * 管理器枚举失败写集合位置，单项读取失败同时写对象 read_error 和全局 read_errors。
     */
    private <T extends ClientServerObject> List<Map<String, Object>> collect(
            String location, Supplier<? extends Collection<T>> source,
            BiConsumer<T, Map<String, Object>> reader, List<Map<String, Object>> errors) {
        List<Map<String, Object>> entries = new ArrayList<>();
        try {
            List<T> objects = new ArrayList<>(source.get());
            objects.sort(Comparator.comparing(ClientServerObject::getPresentationName)
                .thenComparing(object -> object.getClass().getSimpleName()));
            for (T object : objects) {
                Map<String, Object> entry = reference(object);
                entries.add(entry);
                try {
                    // STAR 的 ClientServerObject 提供标签组；空数组表示没有附加标签。
                    List<String> tags = new ArrayList<>();
                    for (Tag tag : object.getTagGroup().getObjects()) {
                        tags.add(tag.getPresentationName());
                    }
                    tags.sort(String::compareTo);
                    entry.put("tags", tags);
                    reader.accept(object, entry);
                } catch (Exception error) {
                    entry.put("read_error", error.toString());
                    readError(errors, location + "/" + object.getPresentationName(), error);
                }
            }
        } catch (Exception error) {
            readError(errors, location, error);
        }
        return entries;
    }

    /** 对象关系使用名称和类型，不输出会话相关的 Java 对象地址或不稳定 ID。 */
    private Map<String, Object> reference(ClientServerObject object) {
        if (object == null) return null;
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("name", object.getPresentationName());
        entry.put("object_type", object.getClass().getSimpleName());
        return entry;
    }

    /** 关联对象集合也按名称、类型排序，使同一算例的多次快照可以直接比较。 */
    private List<Map<String, Object>> references(Collection<? extends ClientServerObject> objects) {
        List<ClientServerObject> sorted = new ArrayList<>(objects);
        sorted.sort(Comparator.comparing(ClientServerObject::getPresentationName)
            .thenComparing(object -> object.getClass().getSimpleName()));
        List<Map<String, Object>> entries = new ArrayList<>();
        for (ClientServerObject object : sorted) entries.add(reference(object));
        return entries;
    }

    /** 边界名称只在区域内唯一，因此接口端点同时携带所属区域；未设置端点保留 null。 */
    private Map<String, Object> boundaryReference(Boundary boundary) {
        Map<String, Object> entry = reference(boundary);
        if (entry != null) entry.put("region", reference(boundary.getRegion()));
        return entry;
    }

    /** 记录可定位的错误，避免把读取失败误解为算例没有相应对象。 */
    private void readError(List<Map<String, Object>> errors, String location, Exception error) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("location", location);
        entry.put("message", error.toString());
        errors.add(entry);
    }

    /** 只序列化显式构造的字段，拒绝隐式调用 STAR 对象的 toString 或属性访问。 */
    private String json(Object value) {
        if (value == null) return "null";
        if (value instanceof String) return quote((String) value);
        if (value instanceof Boolean) return value.toString();
        if (value instanceof Integer || value instanceof Long) return value.toString();
        if (value instanceof Number) return number(((Number) value).doubleValue());
        if (value instanceof Map<?, ?>) {
            List<String> entries = new ArrayList<>();
            for (Map.Entry<?, ?> entry : ((Map<?, ?>) value).entrySet()) {
                entries.add(quote((String) entry.getKey()) + ":" + json(entry.getValue()));
            }
            return "{" + String.join(",", entries) + "}";
        }
        if (value instanceof Collection<?>) {
            List<String> entries = new ArrayList<>();
            for (Object item : (Collection<?>) value) entries.add(json(item));
            return "[" + String.join(",", entries) + "]";
        }
        throw new IllegalArgumentException("Unsupported JSON value type: " + value.getClass().getName());
    }

    /** JSON 不允许 NaN 或 Infinity；保留为字符串以显式标识异常值。 */
    private String number(double value) {
        return Double.isFinite(value) ? Double.toString(value) : quote(Double.toString(value));
    }

    /** 对字符串逐字符转义，保留中文，避免名称或表达式破坏 JSON 结构。 */
    private String quote(String value) {
        if (value == null) return "null";
        StringBuilder result = new StringBuilder("\"");
        for (char c : value.toCharArray()) {
            if (c == '\\' || c == '"') result.append('\\').append(c);
            else if (c < 32) result.append(String.format("\\u%04x", (int) c));
            else result.append(c);
        }
        return result.append('"').toString();
    }
}

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
 * 在 STAR 已加载的算例中读取对象清单、修改表达式或标签、设置标量及显式另存，供文件与会话 Runner 共用。
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
    private static final Map<String, Object> MODIFICATION = __MODIFICATION__;
    private static final Map<String, Object> CATALOG_PLAN = __CATALOG_PLAN__;
    private static final Map<String, Object> CATALOG_REQUEST = __CATALOG_REQUEST__;
    private static final String SESSION_TOKEN = __SESSION_TOKEN__;

    @Override
    public void execute() {
        try {
            Simulation sim = getActiveSimulation();
            // 1. 先核对服务身份；目录版本检查必须早于旧快照或任何目录属性访问。
            if (!EXPECTED_SESSION.isEmpty()
                    && !Path.of(sim.getSessionPath()).toRealPath().equals(
                        Path.of(EXPECTED_SESSION).toRealPath())) {
                throw new IllegalArgumentException("Unexpected simulation session: " + sim.getSessionPath());
            }
            if (ACTION.equals("catalog-read") || ACTION.equals("catalog-describe") || ACTION.equals("catalog-verify")) {
                readCatalog(sim);
                return;
            }
            if (ACTION.equals("catalog-modify") || ACTION.equals("file-catalog-modify")) {
                modifyCatalog(sim);
                return;
            }
            if (CATALOG_PLAN != null || CATALOG_REQUEST != null) {
                throw new IllegalArgumentException("Catalog payload requires a catalog action");
            }
            if (!List.of("inspect", "set-scalar", "save", "file-set", "modify", "file-modify").contains(ACTION)) {
                throw new IllegalArgumentException("Unknown action: " + ACTION);
            }
            Map<String, Object> before = snapshot(sim);
            boolean modifying = ACTION.equals("modify") || ACTION.equals("file-modify");
            boolean saving = ACTION.equals("save") || ACTION.equals("file-set") || ACTION.equals("file-modify");
            if (saving) {
                if (OUTPUT.isEmpty()) throw new IllegalArgumentException("Output is required");
                if (Files.exists(Path.of(OUTPUT))) {
                    throw new IllegalArgumentException("Output already exists: " + OUTPUT);
                }
            }
            if (modifying) {
                Runnable change;
                try {
                    change = prepareModification(sim, before);
                } catch (IllegalArgumentException error) {
                    // 只有确定尚未调用写入 API 的预检查拒绝，才允许会话继续使用。
                    writeResult("rejected", before, before, error.getMessage());
                    return;
                }
                // 2. 写入或回读失败不冒充拒绝；Runner 会将后台会话标为 uncertain。
                change.run();
            } else if (ACTION.equals("set-scalar") || ACTION.equals("file-set")) {
                NamedObject object = sim.get(GlobalParameterManager.class).getObject(NAME);
                if (!(object instanceof ScalarGlobalParameter)) {
                    throw new IllegalArgumentException("Not a scalar global parameter: " + NAME);
                }
                ScalarPhysicalQuantity quantity = ((ScalarGlobalParameter) object).getQuantity();
                Units units = sim.getUnitsManager().getObject(UNIT);
                if (units == null || !quantity.getUnits().compatible(units)) {
                    throw new IllegalArgumentException("Unknown or incompatible unit: " + UNIT);
                }
                // 保留旧数值入口：设置数值常量，原表达式由 before 保存。
                quantity.setValueAndUnits(VALUE, units);
            }
            Map<String, Object> after = ACTION.equals("inspect") ? before : snapshot(sim);
            if (modifying) verifyModified(before, after);
            // 3. 新修改入口先回读再另存；后台 modify 不隐含保存。
            if (saving) {
                sim.saveState(OUTPUT);
                after = snapshot(sim);
                if (modifying) verifyModified(before, after);
            }
            writeResult("ok", before, after, null);
        } catch (Exception error) {
            throw new RuntimeException("StarBridge macro failed: " + error, error);
        }
    }

    /**
     * 执行目录描述或按需读取，独立保留会话元数据与目录结果。
     * 本分支没有写入或保存动作；版本和定位的明确拒绝不使会话进入未知修改状态。
     */
    private void readCatalog(Simulation sim) throws java.io.IOException {
        Map<String, Object> before = fields("session_path", sim.getSessionPath(), "modified", sim.isModified());
        Map<String, Object> catalog;
        boolean verifying = ACTION.equals("catalog-verify");
        try {
            if (CATALOG_PLAN == null || CATALOG_REQUEST == null || MODIFICATION != null
                    || !OUTPUT.isEmpty() || SESSION_TOKEN.isEmpty()
                    || !(verifying ? "read".equals(CATALOG_REQUEST.get("action"))
                                   : ACTION.equals("catalog-" + CATALOG_REQUEST.get("action")))) {
                throw new IllegalArgumentException("Catalog reads require a matching plan, request and read-only action");
            }
            // CatalogRuntime 先精确核对当前服务版本，再定位对象和读取选定属性。
            catalog = CatalogRuntime.inspect(sim, CATALOG_PLAN, CATALOG_REQUEST, SESSION_TOKEN);
        } catch (IllegalArgumentException error) {
            Map<String, Object> after = fields("session_path", sim.getSessionPath(), "modified", sim.isModified());
            writeResult("rejected", before, after, error.getMessage());
            return;
        }
        if (verifying) {
            // 文件重载核对需要同时读取原快照范围；普通 read 仍保持按需读取。
            // 这一步位于目录版本检查之后，不能为核对未知版本而先调用旧 API。
            before = snapshot(sim);
            if (!Boolean.TRUE.equals(before.get("inspection_complete"))
                    || !Boolean.TRUE.equals(catalog.get("inspection_complete"))) {
                throw new IllegalStateException("Reload verification requires complete covered reads");
            }
        }
        // 不将世代或对象 key 混入旧快照，避免另存重载时把新实例当成内容差异。
        Map<String, Object> after = verifying ? before
                : fields("session_path", sim.getSessionPath(), "modified", sim.isModified());
        Map<String, Object> result = fields("status", "ok", "before", before, "after", after,
                                           "catalog", catalog);
        Files.writeString(Path.of(RESULT), json(result), StandardCharsets.UTF_8);
    }

    /**
     * 目录修改先完成版本、目标、预期状态与全部读取检查，再执行一次已准备的写入。
     * prepare 之后的异常不能转为 rejected：此时写入或保存可能已生效。
     */
    private void modifyCatalog(Simulation sim) throws Exception {
        Map<String, Object> before = fields("session_path", sim.getSessionPath(), "modified", sim.isModified());
        CatalogRuntime.PreparedModification prepared;
        boolean saving = ACTION.equals("file-catalog-modify");
        try {
            if (CATALOG_PLAN == null || CATALOG_REQUEST == null || MODIFICATION != null
                    || SESSION_TOKEN.isEmpty() || !"modify".equals(CATALOG_REQUEST.get("action"))
                    || (saving && OUTPUT.isEmpty()) || (!saving && !OUTPUT.isEmpty())) {
                throw new IllegalArgumentException("Catalog modification requires a matching request and save mode");
            }
            // 1. 当前 server gate 与目标属性检查必须早于旧快照 API 和任何设置调用。
            prepared = CatalogRuntime.prepareModification(sim, CATALOG_PLAN, CATALOG_REQUEST, SESSION_TOKEN);
            before = snapshot(sim);
            if (!Boolean.TRUE.equals(before.get("inspection_complete"))) {
                throw new IllegalArgumentException("Modification requires a complete covered snapshot");
            }
            if (saving && Files.exists(Path.of(OUTPUT))) {
                throw new IllegalArgumentException("Output already exists: " + OUTPUT);
            }
        } catch (IllegalArgumentException error) {
            writeResult("rejected", before, before, error.getMessage());
            return;
        }

        // 2. 这里只执行后端已经准备好的设置动作；失败继续抛出，让会话进入 uncertain。
        Map<String, Object> catalog = prepared.apply();
        Map<String, Object> after = snapshot(sim);
        if (!Boolean.TRUE.equals(after.get("inspection_complete"))
                || !Boolean.TRUE.equals(catalog.get("inspection_complete"))) {
            throw new IllegalStateException("Modification readback is incomplete");
        }
        if (saving) {
            // 3. 先回读成功再另存；保存后的属性不得偏离已验证值，重载由 Runner 独立完成。
            sim.saveState(OUTPUT);
            after = snapshot(sim);
            Map<String, Object> saved = CatalogRuntime.inspect(sim, CATALOG_PLAN, catalogReadRequest(), SESSION_TOKEN);
            if (!Boolean.TRUE.equals(after.get("inspection_complete"))
                    || !Boolean.TRUE.equals(saved.get("inspection_complete"))
                    || !sameValue(catalog.get("properties"), saved.get("properties"))) {
                throw new IllegalStateException("Saved catalog values differ from verified readback");
            }
            catalog = saved;
        }
        Map<String, Object> result = fields("status", "ok", "before", before, "after", after,
                "catalog_before", prepared.before, "catalog", catalog, "catalog_request", CATALOG_REQUEST);
        Files.writeString(Path.of(RESULT), json(result), StandardCharsets.UTF_8);
    }

    /** 保存后仍在同一会话内读取全部计划属性；目标引用可以继续核对当前对象身份。 */
    private Map<String, Object> catalogReadRequest() {
        return fields("schema_version", 1L, "action", "read", "target", CATALOG_REQUEST.get("target"));
    }

    /** 保存执行状态、前后快照与原始修改请求；拒绝结果也保留可审阅证据。 */
    private void writeResult(String status, Map<String, Object> before,
                             Map<String, Object> after, String error) throws java.io.IOException {
        Map<String, Object> result = fields("status", status, "before", before, "after", after);
        if (MODIFICATION != null) result.put("modification", MODIFICATION);
        if (CATALOG_REQUEST != null) result.put("catalog_request", CATALOG_REQUEST);
        if (error != null) result.put("error", error);
        Files.writeString(Path.of(RESULT), json(result), StandardCharsets.UTF_8);
    }

    /**
     * 先解析唯一目标、核对预期旧属性并解析所需标签，再返回单项写入动作。
     * 本方法不能调用设置 API；只有返回后的 Runnable 可以写入。
     */
    @SuppressWarnings("unchecked")
    private Runnable prepareModification(Simulation sim, Map<String, Object> before) {
        if (MODIFICATION == null || !Boolean.TRUE.equals(before.get("inspection_complete"))) {
            throw new IllegalArgumentException("Modification requires a complete covered snapshot and request");
        }
        Map<String, Object> target = (Map<String, Object>) MODIFICATION.get("target");
        Map<String, Object> expected = (Map<String, Object>) MODIFICATION.get("expected");
        Map<String, Object> current = targetSnapshot(before, target);
        for (Map.Entry<String, Object> entry : expected.entrySet()) {
            if (!current.containsKey(entry.getKey()) || !sameValue(current.get(entry.getKey()), entry.getValue())) {
                throw new IllegalArgumentException("Precondition mismatch: " + entry.getKey());
            }
        }
        ClientServerObject object = resolveTarget(sim, target);
        String operation = (String) MODIFICATION.get("operation");
        if (operation.equals("set-definition")) {
            if (object instanceof ScalarGlobalParameter) {
                Map<String, Object> value = (Map<String, Object>) MODIFICATION.get("value");
                String definition = (String) value.get("definition");
                ScalarPhysicalQuantity quantity = ((ScalarGlobalParameter) object).getQuantity();
                // STAR 强制将非常量表达式的单位切换为 SI，不能假定保留原显示单位。
                // 请求必须显式声明该结果单位；不符合时在写入前拒绝。
                String siUnit = quantity.getUnits().getSIUnits().getPresentationName();
                Double constant = PhysicalQuantityParser.parseAsConstant(definition);
                if (constant != null && !Double.isFinite(constant)) {
                    throw new IllegalArgumentException("Scalar constants must be finite");
                }
                if (constant == null && !value.get("unit").equals(siUnit)) {
                    throw new IllegalArgumentException("Scalar expressions require SI result unit: '" + siUnit + "'");
                }
                Units units = findNamed(sim.getUnitsManager().getObjects(), (String) value.get("unit"));
                if (!quantity.getUnits().compatible(units)) {
                    throw new IllegalArgumentException("Incompatible result unit");
                }
                return () -> quantity.setDefinitionAndUnits(definition, units);
            }
            if (object instanceof UserFieldFunction) {
                String definition = (String) MODIFICATION.get("value");
                return () -> ((UserFieldFunction) object).setDefinition(definition);
            }
            throw new IllegalArgumentException("Definitions require scalar parameters or user field functions");
        }
        if (operation.equals("set-tags")) {
            TagManager manager = sim.get(TagManager.class);
            // 系统标签可能承载 STAR 内部状态，本入口只替换全部由用户标签构成的关联。
            for (Tag tag : manager.getTags(object)) {
                if (!(tag instanceof UserTag)) {
                    throw new IllegalArgumentException("Target has non-user tags");
                }
            }
            List<Tag> tags = new ArrayList<>();
            for (Object name : (List<?>) MODIFICATION.get("value")) {
                Tag tag = findNamed(manager.getObjects(), (String) name);
                if (!(tag instanceof UserTag)) {
                    throw new IllegalArgumentException("Not a user tag: " + name);
                }
                tags.add(tag);
            }
            return () -> manager.setTags(object, tags);
        }
        throw new IllegalArgumentException("Unsupported modification operation: " + operation);
    }

    /** 目标类别采用白名单；边界必须在指定区域中解析，不按全局同名对象猜测。 */
    private ClientServerObject resolveTarget(Simulation sim, Map<String, Object> target) {
        String name = (String) target.get("name");
        switch ((String) target.get("kind")) {
            case "parameter": return findNamed(sim.get(GlobalParameterManager.class).getObjects(), name);
            case "field_function": return findNamed(sim.getFieldFunctionManager().getObjects(), name);
            case "region": return findNamed(sim.getRegionManager().getObjects(), name);
            case "boundary":
                Region region = findNamed(sim.getRegionManager().getObjects(), (String) target.get("region"));
                return findNamed(region.getBoundaryManager().getObjects(), name);
            default: throw new IllegalArgumentException("Unsupported target kind");
        }
    }

    /** 只接受恰好一个显示名称匹配的对象；不创建缺失对象，也不接受模糊匹配。 */
    private <T extends ClientServerObject> T findNamed(Collection<T> objects, String name) {
        T found = null;
        for (T object : objects) {
            if (name.equals(object.getPresentationName())) {
                if (found != null) throw new IllegalArgumentException("Ambiguous object name: " + name);
                found = object;
            }
        }
        if (found == null) throw new IllegalArgumentException("Object not found: " + name);
        return found;
    }

    /** 从同一份 Inspector 快照定位对象，确保预检查与输出使用同一字段契约。 */
    @SuppressWarnings("unchecked")
    private Map<String, Object> targetSnapshot(Map<String, Object> snapshot, Map<String, Object> target) {
        String collection;
        switch ((String) target.get("kind")) {
            case "parameter": collection = "parameters"; break;
            case "field_function": collection = "field_functions"; break;
            case "region": collection = "regions"; break;
            case "boundary":
                snapshot = targetSnapshot(snapshot, fields("kind", "region", "name", target.get("region")));
                collection = "boundaries";
                break;
            default: throw new IllegalArgumentException("Unsupported target kind");
        }
        Map<String, Object> found = null;
        for (Map<String, Object> entry : (List<Map<String, Object>>) snapshot.get(collection)) {
            if (target.get("name").equals(entry.get("name"))) {
                if (found != null) throw new IllegalArgumentException("Ambiguous snapshot target");
                found = entry;
            }
        }
        if (found == null) throw new IllegalArgumentException("Snapshot target not found");
        return found;
    }

    /**
     * 保存前核对目标属性、声明的结果单位与身份；部分读取不能作为修改成功证据。
     * 表达式按文本回读核对，不调用求解或场函数求值来证明其物理有效性。
     */
    @SuppressWarnings("unchecked")
    private void verifyModified(Map<String, Object> before, Map<String, Object> after) {
        if (!Boolean.TRUE.equals(after.get("inspection_complete"))) {
            throw new IllegalStateException("Modified snapshot is incomplete");
        }
        Map<String, Object> target = (Map<String, Object>) MODIFICATION.get("target");
        Map<String, Object> original = targetSnapshot(before, target);
        Map<String, Object> current = targetSnapshot(after, target);
        String property = MODIFICATION.get("operation").equals("set-definition") ? "definition" : "tags";
        boolean scalar = property.equals("definition") && current.get("object_type").equals("ScalarGlobalParameter");
        Object value = scalar ? ((Map<?, ?>) MODIFICATION.get("value")).get("definition") : MODIFICATION.get("value");
        boolean matches = sameValue(current.get(property), value);
        if (!matches && scalar) {
            // STAR 将纯数值文本规范化为 double 字符串，例如 6 变为 6.0。
            Double wanted = PhysicalQuantityParser.parseAsConstant((String) value);
            Double actual = PhysicalQuantityParser.parseAsConstant((String) current.get("definition"));
            matches = wanted != null && actual != null && sameValue(wanted, actual);
        }
        if (!matches) {
            throw new IllegalStateException("Modification readback mismatch: " + property);
        }
        if (scalar && !sameValue(current.get("unit"), ((Map<?, ?>) MODIFICATION.get("value")).get("unit"))) {
            throw new IllegalStateException("Modification readback mismatch: unit");
        }
        if (scalar) {
            for (String key : List.of("raw_value", "si_value")) {
                Object number = current.get(key);
                if (!(number instanceof Number) || !Double.isFinite(((Number) number).doubleValue())) {
                    throw new IllegalStateException("Modified scalar is non-finite: " + key);
                }
            }
        }
        for (String key : List.of("name", "object_type", "unit", "function_name", "value_type", "dimensions")) {
            if (scalar && key.equals("unit")) continue;
            if (original.containsKey(key) && !sameValue(original.get(key), current.get(key))) {
                throw new IllegalStateException("Target identity or type changed: " + key);
            }
        }
    }

    /** 递归比较 JSON 值；映射不依赖键顺序，数值允许 1 与 1.0 相等。 */
    private boolean sameValue(Object left, Object right) {
        // Inspector 将非有限值输出为字符串；预期状态必须与这个 JSON 表示一致。
        if (left instanceof Double && !Double.isFinite((Double) left)) left = left.toString();
        if (right instanceof Double && !Double.isFinite((Double) right)) right = right.toString();
        if (left instanceof Number && right instanceof Number) {
            return new java.math.BigDecimal(left.toString()).compareTo(
                new java.math.BigDecimal(right.toString())) == 0;
        }
        if (left instanceof Map<?, ?> && right instanceof Map<?, ?>) {
            Map<?, ?> a = (Map<?, ?>) left;
            Map<?, ?> b = (Map<?, ?>) right;
            if (!a.keySet().equals(b.keySet())) return false;
            for (Object key : a.keySet()) if (!sameValue(a.get(key), b.get(key))) return false;
            return true;
        }
        if (left instanceof List<?> && right instanceof List<?>) {
            List<?> a = (List<?>) left;
            List<?> b = (List<?>) right;
            if (a.size() != b.size()) return false;
            for (int i = 0; i < a.size(); i++) if (!sameValue(a.get(i), b.get(i))) return false;
            return true;
        }
        return java.util.Objects.equals(left, right);
    }

    /** 按键值对构造请求和结果；Runner 只把转义后的 JSON 值填入此容器。 */
    private static Map<String, Object> fields(Object... pairs) {
        Map<String, Object> result = new LinkedHashMap<>();
        for (int i = 0; i < pairs.length; i += 2) result.put((String) pairs[i], pairs[i + 1]);
        return result;
    }

    /**
     * 读取已覆盖对象的属性与关系，不遍历任意 Bean 属性，也不计算报告值。
     * 各集合独立记录错误；空集合只有在对应位置没有 read_errors 时才表示确实为空。
     * inspection_complete 仅表示本版声明的字段均成功读取，不代表完整 STAR 设置。
     */
    private Map<String, Object> snapshot(Simulation sim) {
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
        return result;
    }

    /** 统一数量字段：raw_value 使用 unit 所示单位，si_value 使用 SI 单位。 */
    private void scalar(Map<String, Object> entry, ScalarPhysicalQuantity quantity) {
        entry.put("definition", quantity.getDefinition());
        entry.put("unit", quantity.getUnits().getPresentationName());
        entry.put("si_unit", quantity.getUnits().getSIUnits().getPresentationName());
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

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.List;
import star.common.*;

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
    private static final Map<String, Object> LEGACY_PLAN = __LEGACY_PLAN__;
    private static final Map<String, Object> SNAPSHOT_PLAN = __SNAPSHOT_PLAN__;

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
            // 2. 需要旧快照的入口先核对其目录；修改还须在任何准备或属性读取前核对写入目录。
            // 此处拒绝能确定尚未读取对象属性或写入，会话无需被标记为 uncertain。
            if (List.of("inspect", "save", "modify", "file-modify", "set-scalar", "file-set",
                    "catalog-modify", "file-catalog-modify", "catalog-verify").contains(ACTION)) {
                try {
                    CatalogRuntime.checkVersion(sim, SNAPSHOT_PLAN, SESSION_TOKEN);
                    if (List.of("modify", "file-modify", "set-scalar", "file-set").contains(ACTION)) {
                        CatalogRuntime.checkVersion(sim, LEGACY_PLAN, SESSION_TOKEN);
                    } else if (ACTION.equals("catalog-modify") || ACTION.equals("file-catalog-modify")) {
                        CatalogRuntime.checkVersion(sim, CATALOG_PLAN, SESSION_TOKEN);
                    }
                } catch (IllegalArgumentException error) {
                    Map<String, Object> unchanged = fields("session_path", sim.getSessionPath(),
                            "modified", sim.isModified());
                    writeResult("rejected", unchanged, unchanged, error.getMessage());
                    return;
                }
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
            if (List.of("modify", "file-modify", "set-scalar", "file-set").contains(ACTION)) {
                modifyLegacy(sim);
                return;
            }
            if (LEGACY_PLAN != null || MODIFICATION != null) {
                throw new IllegalArgumentException("Legacy payload requires a legacy modification action");
            }
            Map<String, Object> before = snapshot(sim);
            Map<String, Object> after = before;
            if (ACTION.equals("save")) {
                if (OUTPUT.isEmpty() || Files.exists(Path.of(OUTPUT))) {
                    throw new IllegalArgumentException("Save requires a new output file");
                }
                sim.saveState(OUTPUT);
                after = snapshot(sim);
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
            if (CATALOG_PLAN == null || CATALOG_REQUEST == null || MODIFICATION != null || LEGACY_PLAN != null
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
            if (CATALOG_PLAN == null || CATALOG_REQUEST == null || MODIFICATION != null || LEGACY_PLAN != null
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
     * 把旧修改契约转换为目录修改请求，写入只由 CatalogRuntime 的统一执行器完成。
     * 旧 expected 仍逐项核对；内部 expected 取自已与旧快照核对的目录值，不能覆盖调用方前提。
     */
    @SuppressWarnings("unchecked")
    private void modifyLegacy(Simulation sim) throws Exception {
        Map<String, Object> before = fields("session_path", sim.getSessionPath(), "modified", sim.isModified());
        CatalogRuntime.PreparedModification prepared;
        Map<String, Object> request, readRequest, oldTarget;
        boolean modifying = ACTION.equals("modify") || ACTION.equals("file-modify");
        boolean saving = ACTION.equals("file-set") || ACTION.equals("file-modify");
        try {
            if (LEGACY_PLAN == null || SESSION_TOKEN.isEmpty() || modifying != (MODIFICATION != null)
                    || (saving && (OUTPUT.isEmpty() || Files.exists(Path.of(OUTPUT))))
                    || (!saving && !OUTPUT.isEmpty())) {
                throw new IllegalArgumentException("Legacy modification requires its catalog plan and matching save mode");
            }
            // 1. 目录先检查当前服务的精确版本，再读取目标；这之前不访问旧快照 API。
            oldTarget = modifying ? (Map<String, Object>) MODIFICATION.get("target")
                    : fields("kind", "parameter", "name", NAME);
            Map<String, Object> target = legacyTarget(oldTarget, modifying);
            String property = !modifying ? "quantity_value"
                    : MODIFICATION.get("operation").equals("set-tags") ? "tags"
                    : oldTarget.get("kind").equals("parameter") ? "quantity" : "definition";
            readRequest = fields("schema_version", 1L, "action", "read", "target", target);
            Map<String, Object> catalog = CatalogRuntime.inspect(sim, LEGACY_PLAN, readRequest, SESSION_TOKEN);
            before = snapshot(sim);
            if (!Boolean.TRUE.equals(before.get("inspection_complete"))) {
                throw new IllegalArgumentException("Modification requires a complete covered snapshot");
            }
            Map<String, Object> current = targetSnapshot(before, oldTarget);
            if (modifying) {
                for (Map.Entry<String, Object> entry : ((Map<String, Object>) MODIFICATION.get("expected")).entrySet()) {
                    if (!current.containsKey(entry.getKey()) || !sameValue(current.get(entry.getKey()), entry.getValue())) {
                        throw new IllegalArgumentException("Precondition mismatch: " + entry.getKey());
                    }
                }
            }
            verifyLegacyProjection(current, catalog);

            // 2. 固定首次读取的对象身份；统一执行器重新读到的值还必须匹配同一旧快照。
            target.put("reference", ((Map<String, Object>) catalog.get("target")).get("reference"));
            Object value = modifying ? MODIFICATION.get("value") : fields("value", VALUE, "unit", UNIT);
            request = fields("schema_version", 2L, "action", "modify", "target", target,
                    "property", property, "expected", catalogValue(catalog, property), "value", value);
            prepared = CatalogRuntime.prepareModification(sim, LEGACY_PLAN, request, SESSION_TOKEN);
            verifyLegacyProjection(current, prepared.before);
        } catch (IllegalArgumentException error) {
            // 只有设置调用前的确定拒绝才可继续使用原会话。
            writeResult("rejected", before, before, error.getMessage());
            return;
        }

        // 3. apply 后的任何错误都继续抛出；Runner 将无法确认的会话标为 uncertain。
        Map<String, Object> catalog = prepared.apply();
        Map<String, Object> after = snapshot(sim);
        if (!Boolean.TRUE.equals(after.get("inspection_complete"))) {
            throw new IllegalStateException("Modified snapshot is incomplete");
        }
        verifyLegacyProjection(targetSnapshot(after, oldTarget), catalog);
        if (modifying) verifyModified(before, after);
        if (saving) {
            sim.saveState(OUTPUT);
            after = snapshot(sim);
            Map<String, Object> saved = CatalogRuntime.inspect(sim, LEGACY_PLAN, readRequest, SESSION_TOKEN);
            if (!Boolean.TRUE.equals(after.get("inspection_complete"))
                    || !Boolean.TRUE.equals(saved.get("inspection_complete"))
                    || !sameValue(catalog.get("properties"), saved.get("properties"))
                    || !sameValue(catalog.get("target"), saved.get("target"))) {
                throw new IllegalStateException("Saved catalog values differ from verified readback");
            }
            verifyLegacyProjection(targetSnapshot(after, oldTarget), saved);
            if (modifying) verifyModified(before, after);
            catalog = saved;
        }
        Map<String, Object> result = fields("status", "ok", "before", before, "after", after,
                "catalog_before", prepared.before, "catalog", catalog, "catalog_request", request);
        if (MODIFICATION != null) result.put("modification", MODIFICATION);
        Files.writeString(Path.of(RESULT), json(result), StandardCharsets.UTF_8);
    }

    /** 旧类型映射为固定目录类型；边界保留明确的所属区域路径。 */
    private Map<String, Object> legacyTarget(Map<String, Object> target, boolean modifying) {
        String kind = (String) target.get("kind");
        boolean definition = modifying && "set-definition".equals(MODIFICATION.get("operation"));
        String type;
        switch (kind) {
            case "parameter": type = !modifying || definition ? "scalar_parameter" : "global_parameter"; break;
            case "field_function": type = definition ? "user_field_function" : "field_function"; break;
            case "region": case "boundary": type = kind; break;
            default: throw new IllegalArgumentException("Unsupported legacy target kind");
        }
        Map<String, Object> result = fields("type", type, "name", target.get("name"));
        if (kind.equals("boundary")) {
            result.put("parent", fields("type", "region", "name", target.get("region")));
        }
        return result;
    }

    /** 目录读取必须完整且属性成功，缺失值不能作为内部 expected。 */
    @SuppressWarnings("unchecked")
    private Object catalogValue(Map<String, Object> catalog, String property) {
        if (!Boolean.TRUE.equals(catalog.get("inspection_complete"))) {
            throw new IllegalArgumentException("Legacy modification requires complete catalog reads");
        }
        Map<String, Object> entry = (Map<String, Object>) ((Map<?, ?>) catalog.get("properties")).get(property);
        if (entry == null || !"ok".equals(entry.get("status")) || !entry.containsKey("value")) {
            throw new IllegalArgumentException("Catalog property was not read successfully: " + property);
        }
        return entry.get("value");
    }

    /**
     * 将目录与旧 Inspector 共有字段投影到同一格式，拒绝两次读取间的属性变化。
     * 标签目录值带引用而旧值只有名称；数量按旧快照的五个字段逐项比较。
     */
    @SuppressWarnings("unchecked")
    private void verifyLegacyProjection(Map<String, Object> current, Map<String, Object> catalog) {
        Map<String, Object> target = (Map<String, Object>) catalog.get("target");
        String javaClass = (String) target.get("java_class");
        if (!sameValue(current.get("name"), target.get("name"))
                || !sameValue(current.get("object_type"), javaClass.substring(javaClass.lastIndexOf('.') + 1))) {
            throw new IllegalArgumentException("Legacy and catalog target identities differ");
        }
        for (String name : ((Map<String, Object>) catalog.get("properties")).keySet()) {
            Object value = catalogValue(catalog, name);
            if (name.equals("quantity") || name.equals("quantity_value")) {
                for (Map.Entry<String, Object> entry : ((Map<String, Object>) value).entrySet()) {
                    requireLegacyMatch(current, entry.getKey(), entry.getValue());
                }
                continue;
            }
            if (name.equals("tags")) {
                List<String> names = new ArrayList<>();
                for (Object tag : (List<?>) value) names.add((String) ((Map<?, ?>) tag).get("name"));
                names.sort(String::compareTo);
                value = names;
            } else if (name.equals("value_type")) {
                value = ((Map<?, ?>) value).get("selected");
            } else if (name.equals("region_type") || name.equals("boundary_type")) {
                String type = (String) ((Map<?, ?>) value).get("java_class");
                value = type.substring(type.lastIndexOf('.') + 1);
            } else if (name.equals("physics_continuum") && value != null) {
                Map<?, ?> reference = (Map<?, ?>) value;
                String type = (String) reference.get("java_class");
                value = fields("name", reference.get("name"), "object_type", type.substring(type.lastIndexOf('.') + 1));
            }
            // 目录额外读取的 index 等字段在旧契约中不存在，只保留在目录审计结果中。
            if (current.containsKey(name)) requireLegacyMatch(current, name, value);
        }
    }

    /** 共用字段必须真实存在且相等，禁止用目录当前值替换不匹配的旧预期。 */
    private void requireLegacyMatch(Map<String, Object> current, String name, Object value) {
        if (!current.containsKey(name) || !sameValue(current.get(name), value)) {
            throw new IllegalArgumentException("Legacy and catalog reads differ: " + name);
        }
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

    /** 旧 Inspector 输出也由已校验的目录计划读取；字段与遍历规则不再写死在宏中。 */
    private Map<String, Object> snapshot(Simulation sim) {
        return CatalogRuntime.snapshot(sim, SNAPSHOT_PLAN, SESSION_TOKEN);
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

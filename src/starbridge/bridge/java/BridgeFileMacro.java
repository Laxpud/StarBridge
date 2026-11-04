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
 * 在 STAR 已加载的算例中读取快照、执行目录读写及显式另存，供文件与会话 Runner 共用。
 * Runner 替换配置占位符；本宏不生成网格、不执行求解。
 */
public class BridgeFileMacro extends StarMacro {
    private static final String RESULT = __RESULT__;
    private static final String ACTION = __ACTION__;
    private static final String EXPECTED_SESSION = __EXPECTED_SESSION__;
    private static final String EXPECTED_SIMULATION_KEY = __EXPECTED_SIMULATION_KEY__;
    private static final String OUTPUT = __OUTPUT__;
    private static final Map<String, Object> CATALOG_PLAN = __CATALOG_PLAN__;
    private static final Map<String, Object> CATALOG_REQUEST = __CATALOG_REQUEST__;
    private static final String SESSION_TOKEN = __SESSION_TOKEN__;
    private static final Map<String, Object> SNAPSHOT_PLAN = __SNAPSHOT_PLAN__;
    private static final Map<String, Object> DISCOVERY_REQUEST = __DISCOVERY_REQUEST__;

    @Override
    public void execute() {
        try {
            Simulation sim = getActiveSimulation();
            // 1. 先核对服务身份；目录版本检查必须早于快照或任何目录属性访问。
            if (!EXPECTED_SIMULATION_KEY.isEmpty()
                    && !EXPECTED_SIMULATION_KEY.equals(sim.getObjectKeyAsString())) {
                throw new IllegalArgumentException("Simulation was replaced; open a new connection");
            }
            // 已绑定对象 key 后允许用户在 GUI 中另存为；重载造成 key 改变仍会拒绝。
            if (EXPECTED_SIMULATION_KEY.isEmpty() && !EXPECTED_SESSION.isEmpty()
                    && !Path.of(sim.getSessionPath()).toAbsolutePath().normalize().equals(
                        Path.of(EXPECTED_SESSION).toAbsolutePath().normalize())) {
                throw new IllegalArgumentException("Unexpected simulation session: " + sim.getSessionPath());
            }
            // 2. 需要快照的入口先核对其目录；修改还须在任何准备或属性读取前核对写入目录。
            // 此处拒绝能确定尚未读取对象属性或写入，会话无需被标记为 uncertain。
            if (List.of("session-info", "inspect", "save",
                    "catalog-modify", "file-catalog-modify", "catalog-verify").contains(ACTION)) {
                try {
                    if (SNAPSHOT_PLAN != null) CatalogRuntime.checkVersion(sim, SNAPSHOT_PLAN, SESSION_TOKEN);
                    if (ACTION.equals("catalog-modify") || ACTION.equals("file-catalog-modify")) {
                        CatalogRuntime.checkVersion(sim, CATALOG_PLAN, SESSION_TOKEN);
                    }
                } catch (IllegalArgumentException error) {
                    Map<String, Object> unchanged = fields("session_path", sim.getSessionPath(),
                            "modified", sim.isModified());
                    writeResult("rejected", unchanged, unchanged, error.getMessage());
                    return;
                }
            }
            // 会话接入只需要版本、加载对象和文件位置；不要求完整 Inspector 可读取。
            if (ACTION.equals("session-info")) {
                Map<String, Object> info = fields("session_path", sim.getSessionPath(),
                        "modified", sim.isModified(), "simulation_key", sim.getObjectKeyAsString());
                writeResult("ok", info, info, null);
                return;
            }
            if (ACTION.equals("discovery")) {
                discover(sim);
                return;
            }
            if (DISCOVERY_REQUEST != null) {
                throw new IllegalArgumentException("Discovery payload requires discovery action");
            }
            if (ACTION.equals("catalog-find") || ACTION.equals("catalog-read") || ACTION.equals("catalog-describe") || ACTION.equals("catalog-verify")) {
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
            if (!List.of("inspect", "save").contains(ACTION)) {
                throw new IllegalArgumentException("Unknown action: " + ACTION);
            }
            Map<String, Object> before = snapshot(sim);
            Map<String, Object> after = before;
            if (ACTION.equals("save")) {
                // 当前加载路径允许显式覆盖；另存为仍要求新文件，避免覆盖无关算例。
                boolean current = sim.getSessionPath() != null && !sim.getSessionPath().isEmpty() && !OUTPUT.isEmpty()
                        && Path.of(OUTPUT).toAbsolutePath().normalize().equals(
                            Path.of(sim.getSessionPath()).toAbsolutePath().normalize());
                if (OUTPUT.isEmpty() || (Files.exists(Path.of(OUTPUT)) && !current)) {
                    throw new IllegalArgumentException("Save-as requires a new output file");
                }
                sim.saveState(OUTPUT);
                after = snapshot(sim);
            }
            writeResult("ok", before, after, null);
        } catch (Exception error) {
            throw new RuntimeException("StarBridge macro failed: " + error, error);
        }
    }

    /** 仅调用发现提供器；每项错误由提供器保留，身份和版本拒绝单独返回。 */
    private void discover(Simulation sim) throws java.io.IOException {
        Map<String, Object> before = fields("session_path", sim.getSessionPath(), "modified", sim.isModified());
        Map<String, Object> discovery;
        try {
            if (DISCOVERY_REQUEST == null || CATALOG_PLAN != null || CATALOG_REQUEST != null
                    || SNAPSHOT_PLAN != null || !OUTPUT.isEmpty()) {
                throw new IllegalArgumentException("Discovery requires an isolated read-only request");
            }
            discovery = DiscoveryRuntime.run(sim, DISCOVERY_REQUEST, SESSION_TOKEN);
        } catch (IllegalArgumentException error) {
            writeResult("rejected", before, before, error.getMessage());
            return;
        }
        Map<String, Object> after = fields("session_path", sim.getSessionPath(), "modified", sim.isModified());
        Files.writeString(Path.of(RESULT), json(fields("status", "ok", "before", before,
                "after", after, "discovery", discovery)), StandardCharsets.UTF_8);
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
            if (CATALOG_PLAN == null || CATALOG_REQUEST == null
                    || !OUTPUT.isEmpty() || SESSION_TOKEN.isEmpty()
                    || !(verifying ? "read".equals(CATALOG_REQUEST.get("action"))
                                   : ACTION.equals("catalog-" + CATALOG_REQUEST.get("action")))) {
                throw new IllegalArgumentException("Catalog reads require a matching plan, request and read-only action");
            }
            // CatalogRuntime 先精确核对当前服务版本，再定位对象和读取选定属性。
            catalog = ACTION.equals("catalog-find")
                    ? CatalogRuntime.find(sim, CATALOG_PLAN, CATALOG_REQUEST, SESSION_TOKEN)
                    : CatalogRuntime.inspect(sim, CATALOG_PLAN, CATALOG_REQUEST, SESSION_TOKEN);
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
        // 不将世代或对象 key 混入快照，避免另存重载时把新实例当成内容差异。
        Map<String, Object> after = verifying ? before
                : fields("session_path", sim.getSessionPath(), "modified", sim.isModified());
        Map<String, Object> result = fields("status", "ok", "before", before, "after", after,
                                           "catalog", catalog);
        Files.writeString(Path.of(RESULT), json(result), StandardCharsets.UTF_8);
    }

    /**
     * 目录修改只核对目标、旧值与规则指定关联项；完整快照仅在显式审查或文件重载时读取。
     * prepare 之后的异常仍表示结果未确认，不能重试 setter。
     */
    private void modifyCatalog(Simulation sim) throws Exception {
        Map<String, Object> before = fields("session_path", sim.getSessionPath(), "modified", sim.isModified());
        CatalogRuntime.PreparedChange prepared;
        boolean auditing = SNAPSHOT_PLAN != null;
        boolean saving = ACTION.equals("file-catalog-modify");
        try {
            if (CATALOG_PLAN == null || CATALOG_REQUEST == null
                    || SESSION_TOKEN.isEmpty() || !"modify".equals(CATALOG_REQUEST.get("action"))
                    || (saving && OUTPUT.isEmpty()) || (!saving && !OUTPUT.isEmpty())) {
                throw new IllegalArgumentException("Catalog modification requires a matching request and save mode");
            }
            // 1. 版本、定位、旧值、单位、范围和必要关联项均由目标写计划验证。
            prepared = CatalogRuntime.prepareChange(sim, CATALOG_PLAN, CATALOG_REQUEST, SESSION_TOKEN);
            if (auditing) before = snapshot(sim);
            if (saving && Files.exists(Path.of(OUTPUT))) {
                throw new IllegalArgumentException("Output already exists: " + OUTPUT);
            }
        } catch (IllegalArgumentException error) {
            writeResult("rejected", before, before, error.getMessage());
            return;
        }

        // 2. apply 只执行一次赋值并回读；旧 Inspector 的其他设置不作为成功条件。
        Map<String, Object> catalog = prepared.apply();
        Map<String, Object> after = auditing ? snapshot(sim)
                : fields("session_path", sim.getSessionPath(), "modified", sim.isModified());
        if (!Boolean.TRUE.equals(catalog.get("inspection_complete"))) {
            throw new IllegalStateException("Modification readback is incomplete");
        }
        if (saving) {
            // 文件入口仍独立重载；这里先保存并核对目标计划中的回读值。
            sim.saveState(OUTPUT);
            after = snapshot(sim);
            Map<String, Object> saved = CatalogRuntime.inspect(sim, CATALOG_PLAN, catalogReadRequest(), SESSION_TOKEN);
            if (!Boolean.TRUE.equals(saved.get("inspection_complete"))
                    || !sameValue(catalog.get("properties"), saved.get("properties"))) {
                throw new IllegalStateException("Saved catalog values differ from verified readback");
            }
            catalog = saved;
        }
        Map<String, Object> result = fields("status", "ok", "before", before, "after", after,
                "catalog_before", prepared.before(), "catalog", catalog, "catalog_request", CATALOG_REQUEST,
                "snapshot_audit", auditing, "setter_attempts", 1);
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
        if (CATALOG_REQUEST != null) result.put("catalog_request", CATALOG_REQUEST);
        if (error != null) result.put("error", error);
        Files.writeString(Path.of(RESULT), json(result), StandardCharsets.UTF_8);
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

    /** Inspector 输出也由已校验的目录计划读取；字段与遍历规则不再写死在宏中。 */
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

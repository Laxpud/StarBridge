import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import star.common.*;
__IMPORTS__

/**
 * 在同一已加载算例中顺序执行显式 Java 步骤，每步前后写入可恢复的执行凭据。
 * 这是完整宏能力入口，不是代码沙箱；effect 为调用者的声明，不检测任意代码的副作用。
 */
public class StarBridgeProgram extends StarMacro {
    private static final String RESULT = __RESULT__;
    private static final String EXPECTED_KEY = __EXPECTED_KEY__;
    private static final String RELEASE = __RELEASE__;
    private static final String BUILD = __BUILD__;
    private static final String REQUEST_ID = __REQUEST_ID__;
    private final Map<String, Object> parameters = __PARAMETERS__;
    private final Map<String, Object> shared = new LinkedHashMap<>();
    private final List<Map<String, Object>> steps = new ArrayList<>();
    private Simulation sim;
    __DECLARATIONS__

    @Override
    public void execute() {
        Map<String, Object> before = new LinkedHashMap<>();
        Map<String, Object> execution = fields("request_id", REQUEST_ID, "status", "running",
                "steps", steps, "uncertain", false, "completion_basis", "step_return_and_serializable_result");
        try {
            sim = getActiveSimulation();
            before = sessionInfo();
            // 1. 先检查实际版本和对象身份；拒绝发生在任何用户步骤之前。
            if (!EXPECTED_KEY.equals(sim.getObjectKeyAsString())
                    || !RELEASE.equals(sim.getCurrentVersion()) || !BUILD.equals(sim.getReleaseNumber())) {
                execution.put("status", "rejected");
                execution.put("reason", "Simulation identity or STAR version changed");
                checkpoint("rejected", before, execution);
                return;
            }
            __STEP_METADATA__
            // 对象参数是当前会话的受信引用；全部解析成功后才允许任何用户步骤开始。
            try {
                __OBJECT_BINDING_SETUP__
            } catch (Exception error) {
                execution.put("status", "rejected");
                execution.put("reason", "Object parameter binding failed: " + error);
                checkpoint("rejected", before, execution);
                return;
            }
            checkpoint("running", before, execution);
            // 2. 只有前一步完成才开始下一步；失败后保留未开始项，不自动继续或重试。
            for (int index = 0; index < steps.size(); index++) {
                Map<String, Object> step = steps.get(index);
                Map<String, Object> result = new LinkedHashMap<>();
                step.put("status", "running");
                checkpoint("running", before, execution);
                try {
                    runStep(index, result);
                    // 先验证输出能够无歧义地序列化；不能把 Java 对象的 toString 当成读取值。
                    json(result);
                    step.put("result", freeze(result));
                    step.put("status", "completed");
                } catch (Throwable error) {
                    boolean uncertain = "mutate".equals(step.get("effect"));
                    step.put("status", uncertain ? "uncertain" : "failed");
                    step.put("error", fields("type", error.getClass().getName(), "message", String.valueOf(error.getMessage())));
                    execution.put("uncertain", uncertain);
                    execution.put("status", index > 0 ? "partial" : uncertain ? "uncertain" : "failed");
                    checkpoint(index > 0 ? "partial" : uncertain ? "uncertain" : "error", before, execution);
                    return;
                }
                checkpoint("running", before, execution);
            }
            execution.put("status", "completed");
            checkpoint("ok", before, execution);
        } catch (Throwable error) {
            // 无法写入最终凭据时让控制端保留未知结果；不会为了补结果再次执行步骤。
            throw new RuntimeException("StarBridge program did not produce a final receipt", error);
        }
    }

    /** 只替换已声明位置的 {object_id} 包装；其他 JSON 参数和持久请求原文保持不变。 */
    @SuppressWarnings("unchecked")
    private void bindParameter(List<?> path, Object value) {
        Object container = parameters;
        for (int index = 0; index < path.size() - 1; index++) {
            Object key = path.get(index);
            container = key instanceof String ? ((Map<?, ?>) container).get(key)
                    : ((List<?>) container).get(((Number) key).intValue());
        }
        Object key = path.get(path.size() - 1);
        if (key instanceof String) ((Map<String, Object>) container).put((String) key, value);
        else ((List<Object>) container).set(((Number) key).intValue(), value);
    }

    /** 根据序号调用独立方法，避免把前一步的局部变量意外暴露为复用约定。 */
    private void runStep(int index, Map<String, Object> result) throws Exception {
        switch (index) {
            __STEP_CASES__
            default: throw new IllegalArgumentException("Unknown step index");
        }
    }
    __STEP_METHODS__

    /** 只读会话身份和脏标记，不做全量快照，也不隐式保存或复制算例。 */
    private Map<String, Object> sessionInfo() {
        return fields("session_path", sim.getSessionPath(), "modified", sim.isModified(),
                "simulation_key", sim.getObjectKeyAsString());
    }

    /** 原子替换每个阶段的凭据；进程中断时，旧完整阶段比半份 JSON 更有用。 */
    private void checkpoint(String status, Map<String, Object> before, Map<String, Object> execution) throws Exception {
        Path destination = Path.of(RESULT);
        Path temporary = destination.resolveSibling("result.json.tmp");
        String text = json(fields("status", status, "before", before, "after", sessionInfo(), "execution", execution));
        Files.writeString(temporary, text, StandardCharsets.UTF_8);
        try {
            Files.move(temporary, destination, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        } catch (AtomicMoveNotSupportedException error) {
            Files.move(temporary, destination, StandardCopyOption.REPLACE_EXISTING);
        }
    }

    /** 供步骤构造明确的 JSON 结果；集合为空与未读取必须由步骤分别表达。 */
    public static Map<String, Object> fields(Object... pairs) {
        if (pairs.length % 2 != 0) throw new IllegalArgumentException("Expected key/value pairs");
        Map<String, Object> result = new LinkedHashMap<>();
        for (int i = 0; i < pairs.length; i += 2) result.put((String) pairs[i], pairs[i + 1]);
        return result;
    }

    /** 冻结已完成步骤的 JSON 值；后续 shared 中的活集合不能改写先前观察结果。 */
    private static Object freeze(Object value) {
        if (value == null || value instanceof String || value instanceof Boolean) return value;
        if (value instanceof Number) return new java.math.BigDecimal(value.toString());
        if (value instanceof Map<?, ?>) {
            Map<String, Object> copy = new LinkedHashMap<>();
            for (Map.Entry<?, ?> entry : ((Map<?, ?>) value).entrySet())
                copy.put((String) entry.getKey(), freeze(entry.getValue()));
            return Collections.unmodifiableMap(copy);
        }
        if (value instanceof Collection<?>) {
            List<Object> copy = new ArrayList<>();
            for (Object item : (Collection<?>) value) copy.add(freeze(item));
            return Collections.unmodifiableList(copy);
        }
        throw new IllegalArgumentException("Unsupported JSON snapshot value");
    }

    /** 仅接受 JSON 值，拒绝非有限数、未知对象以及非字符串键，不隐式调用 STAR getter。 */
    private static String json(Object value) {
        if (value == null) return "null";
        if (value instanceof String) return quote((String) value);
        if (value instanceof Boolean) return value.toString();
        if (value instanceof Number) {
            if (!Double.isFinite(((Number) value).doubleValue()))
                throw new IllegalArgumentException("Non-finite result; report an explicit unavailable state instead");
            return value.toString();
        }
        if (value instanceof Map<?, ?>) {
            List<String> entries = new ArrayList<>();
            for (Map.Entry<?, ?> entry : ((Map<?, ?>) value).entrySet()) {
                if (!(entry.getKey() instanceof String)) throw new IllegalArgumentException("JSON keys must be strings");
                entries.add(quote((String) entry.getKey()) + ":" + json(entry.getValue()));
            }
            return "{" + String.join(",", entries) + "}";
        }
        if (value instanceof Collection<?>) {
            List<String> entries = new ArrayList<>();
            for (Object item : (Collection<?>) value) entries.add(json(item));
            return "[" + String.join(",", entries) + "]";
        }
        throw new IllegalArgumentException("Unsupported JSON result: " + value.getClass().getName());
    }

    /** 对 JSON 字符串转义，保留中文和控制字符的确切含义。 */
    private static String quote(String value) {
        StringBuilder result = new StringBuilder("\"");
        for (char c : value.toCharArray()) {
            if (c == '\\' || c == '"') result.append('\\').append(c);
            else if (c < 32) result.append(String.format("\\u%04x", (int) c));
            else result.append(c);
        }
        return result.append('"').toString();
    }
}

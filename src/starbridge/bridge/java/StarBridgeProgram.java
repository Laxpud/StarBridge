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
    private static final String INITIALIZATION_EFFECT = __INITIALIZATION_EFFECT__;
    private final Map<String, Object> parameters = __PARAMETERS__;
    private final Map<String, Object> shared = new LinkedHashMap<>();
    private final List<Map<String, Object>> steps = new ArrayList<>();
    private Simulation sim;

    @Override
    public void execute() {
        Map<String, Object> before = new LinkedHashMap<>();
        Map<String, Object> initialization = fields("status", "not_started", "effect", INITIALIZATION_EFFECT,
                "scope", "Caller declarations and payload construction; effect aggregates all declared steps");
        Map<String, Object> execution = fields("request_id", REQUEST_ID, "status", "running",
                "initialization", initialization, "steps", steps, "uncertain", false,
                "completion_basis", "initialization_and_step_return_with_serializable_result");
        try {
            __STEP_METADATA__
            sim = getActiveSimulation();
            before = sessionInfo();
            // 1. 入口类中没有用户声明。先核对实际版本和对象身份，不触发 Payload 的类／实例初始化。
            if (!EXPECTED_KEY.equals(sim.getObjectKeyAsString())
                    || !RELEASE.equals(sim.getCurrentVersion()) || !BUILD.equals(sim.getReleaseNumber())) {
                execution.put("status", "rejected");
                execution.put("reason", "Simulation identity or STAR version changed");
                checkpoint("rejected", before, execution);
                return;
            }
            // 对象参数是当前会话的受信引用；全部解析成功后才允许用户初始化或步骤开始。
            try {
                __OBJECT_BINDING_SETUP__
            } catch (Exception error) {
                execution.put("status", "rejected");
                execution.put("reason", "Object parameter binding failed: " + error);
                checkpoint("rejected", before, execution);
                return;
            }
            // 2. 先持久记录初始化已开始，再首次主动使用 Payload。加载／链接可能更早发生，
            // 但初始化外层类不会初始化静态嵌套类；下面的 new 才触发 Payload 静态块、字段和实例块。
            // effect 沿用整个请求的声明：任一步 mutate 则初始化也按 mutate；不是副作用分析或沙箱。
            initialization.put("status", "running");
            checkpoint("running", before, execution);
            Payload payload;
            try {
                payload = new Payload(this, sim, parameters, shared);
            } catch (Throwable error) {
                boolean uncertain = "mutate".equals(INITIALIZATION_EFFECT);
                initialization.put("status", uncertain ? "uncertain" : "failed");
                Throwable cause = error.getCause();
                // 静态初始化失败通常被 ExceptionInInitializerError 包装；保留直接原因，不能只留下空消息。
                initialization.put("error", fields("type", error.getClass().getName(),
                        "message", String.valueOf(error.getMessage()), "cause", cause == null ? null :
                        fields("type", cause.getClass().getName(), "message", String.valueOf(cause.getMessage()))));
                execution.put("status", uncertain ? "uncertain" : "failed");
                execution.put("uncertain", uncertain);
                execution.put("reason", "Payload initialization failed; user declarations may have partially executed");
                checkpoint(uncertain ? "uncertain" : "error", before, execution);
                return;
            }
            initialization.put("status", "completed");
            checkpoint("running", before, execution);
            // 3. 只有初始化和前一步完成才开始下一步；失败后保留未开始项，不自动继续或重试。
            for (int index = 0; index < steps.size(); index++) {
                Map<String, Object> step = steps.get(index);
                Map<String, Object> result = new LinkedHashMap<>();
                step.put("status", "running");
                checkpoint("running", before, execution);
                try {
                    payload.runStep(index, result);
                    // 先验证输出能够无歧义地序列化；不能把 Java 对象的 toString 当成读取值。
                    json(result);
                    step.put("result", freeze(result));
                    step.put("status", "completed");
                } catch (Throwable error) {
                    boolean uncertain = "mutate".equals(step.get("effect"));
                    step.put("status", uncertain ? "uncertain" : "failed");
                    step.put("error", fields("type", error.getClass().getName(), "message", String.valueOf(error.getMessage())));
                    // 异常前已写入的观察仍有价值；只保留可序列化的冻结快照，不据此确认步骤完成。
                    try {
                        Object partialResult = freeze(result);
                        json(partialResult);
                        step.put("result", partialResult);
                    } catch (Throwable serializationError) {
                        // 快照失败单独记录，不能覆盖执行异常，也不能让不可序列化值破坏最终凭据。
                        step.put("serialization_error", fields("type", serializationError.getClass().getName(),
                                "message", String.valueOf(serializationError.getMessage())));
                    }
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

    /**
     * 在用户实例字段初始化前提供同一组上下文，并保留 StarMacro 的常用辅助方法。
     * Payload 的父类构造先完成，因此用户字段／实例块可以读取 sim、parameters、shared，
     * getActiveSimulation() 也已有目标；静态字段不能访问实例上下文，仍遵循普通 Java 规则。
     */
    private abstract static class PayloadContext extends StarMacro {
        protected Simulation sim;
        protected final Map<String, Object> parameters;
        protected final Map<String, Object> shared;
        private final StarBridgeProgram owner;

        protected PayloadContext(StarBridgeProgram owner, Simulation sim,
                Map<String, Object> parameters, Map<String, Object> shared) {
            this.owner = owner;
            this.sim = sim;
            this.parameters = parameters;
            this.shared = shared;
            // 使用父类 setter 初始化实际宏上下文；不是把一个没有 active simulation 的新宏交给用户。
            super.setActiveSimulation(sim);
        }

        // 脚本路径由 STAR 交给外层入口。路径辅助方法复用该入口，不能以新对象的空路径代替。
        @Override public String resolvePath(String path) { return owner.resolvePath(path); }
        @Override protected String resolveDataPath(String path) { return owner.resolveDataPath(path); }
        @Override protected String resolveWorkPath() { return owner.resolveWorkPath(); }
        @Override public void savePath(star.base.neo.NeoScriptFile path) { owner.savePath(path); }

        @Override public final void execute() {
            throw new IllegalStateException("Payload steps must be invoked by the execution wrapper");
        }
    }

    /**
     * 唯一承载用户声明及步骤的类。不得在入口字段、身份检查或对象绑定中主动使用此类；
     * new Payload 必须位于 initialization.running 凭据写出之后，才能保留初始化未知结果。
     * fields 等外层静态 JSON 辅助方法仍可直接使用；这不是限制任意 Java 代码的安全沙箱。
     */
    private static class Payload extends PayloadContext {
        private Payload(StarBridgeProgram owner, Simulation sim,
                Map<String, Object> parameters, Map<String, Object> shared) {
            super(owner, sim, parameters, shared);
        }

        __DECLARATIONS__

        /** 根据序号调用独立方法；步骤共享的是明确上下文，不是前一步的局部变量。 */
        private void runStep(int index, Map<String, Object> result) throws Exception {
            switch (index) {
                __STEP_CASES__
                default: throw new IllegalArgumentException("Unknown step index");
            }
        }
        __STEP_METHODS__
    }

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

    /** 冻结步骤完成或异常前已写入的 JSON 观察；后续 shared 中的活集合不能改写快照。 */
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

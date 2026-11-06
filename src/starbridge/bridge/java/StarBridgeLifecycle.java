import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import star.common.Simulation;
import star.common.StarMacro;

/**
 * 只处理会话身份读取和显式保存，不加载目录、发现规则或完整 Inspector。
 * 版本来自所选启动器的实际检测；进入保存前再次核对当前服务器与已绑定加载对象。
 */
public class StarBridgeLifecycle extends StarMacro {
    private static final String RESULT = __RESULT__;
    private static final String ACTION = __ACTION__;
    private static final String RELEASE = __RELEASE__;
    private static final String BUILD = __BUILD__;
    private static final String EXPECTED_KEY = __EXPECTED_KEY__;
    private static final String EXPECTED_SESSION = __EXPECTED_SESSION__;
    private static final String OUTPUT = __OUTPUT__;

    @Override
    public void execute() {
        Simulation sim = null;
        Map<String, Object> before = new LinkedHashMap<>();
        boolean saveStarted = false;
        try {
            sim = getActiveSimulation();
            before = info(sim);
            // 1. 版本与对象身份是运行时事实，不以存在目录或编译通过替代检查。
            require(RELEASE.equals(sim.getCurrentVersion()) && BUILD.equals(sim.getReleaseNumber()),
                    "STAR server version differs from the selected installation");
            require(EXPECTED_KEY.isEmpty() || EXPECTED_KEY.equals(sim.getObjectKeyAsString()),
                    "Simulation was replaced; reconnect before continuing");
            if (EXPECTED_KEY.isEmpty() && !EXPECTED_SESSION.isEmpty()) {
                require(sim.getSessionPath() != null && !sim.getSessionPath().isEmpty()
                        && Path.of(EXPECTED_SESSION).toAbsolutePath().normalize().equals(
                            Path.of(sim.getSessionPath()).toAbsolutePath().normalize()),
                        "Unexpected simulation session path");
            }
            if (ACTION.equals("session-info")) {
                writeResult("ok", before, before, null);
                return;
            }
            require(ACTION.equals("save"), "Unsupported lifecycle action");
            // 2. 当前路径允许明确覆盖；另存仅接受新.sim文件，临写前再检查，避免误覆盖。
            require(!OUTPUT.isEmpty(), "A save output path is required");
            Path output = Path.of(OUTPUT).toAbsolutePath().normalize();
            boolean current = sim.getSessionPath() != null && !sim.getSessionPath().isEmpty()
                    && output.equals(Path.of(sim.getSessionPath()).toAbsolutePath().normalize());
            require(Files.isDirectory(output.getParent()), "Save parent directory is unavailable");
            require(current || (!Files.exists(output) && OUTPUT.endsWith(".sim")),
                    "Save-as requires a new .sim file");
            saveStarted = true;
            sim.saveState(output.toString());
            writeResult("ok", before, info(sim), null);
        } catch (Throwable error) {
            // 保存开始后的异常不证明没有写文件；元数据读取失败也不能虚构当前路径或dirty值。
            Map<String, Object> after = fields("metadata_state", "unavailable");
            try { if (sim != null) after = info(sim); } catch (Throwable unavailable) { }
            try {
                writeResult(saveStarted ? "uncertain" : "rejected", before, after,
                        error.getClass().getName() + ": " + String.valueOf(error.getMessage()));
            } catch (Exception receiptError) {
                throw new RuntimeException("Lifecycle operation has no final receipt", receiptError);
            }
        }
    }

    /** 最小身份与dirty观察，不访问惰性模型、属性包装器或算例业务对象。 */
    private static Map<String, Object> info(Simulation sim) {
        return fields("session_path", sim.getSessionPath(), "modified", sim.isModified(),
                "simulation_key", sim.getObjectKeyAsString(),
                "star_version", fields("release", sim.getCurrentVersion(), "build", sim.getReleaseNumber()));
    }

    /** 完整凭据原子落盘；中断不能留下被误认为成功的半份JSON。 */
    private static void writeResult(String status, Map<String, Object> before,
            Map<String, Object> after, String error) throws Exception {
        Path destination = Path.of(RESULT);
        Path temporary = destination.resolveSibling("result.json.tmp");
        Files.writeString(temporary, json(fields("status", status, "before", before,
                "after", after, "error", error)), StandardCharsets.UTF_8);
        try {
            Files.move(temporary, destination, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        } catch (AtomicMoveNotSupportedException unsupported) {
            Files.move(temporary, destination, StandardCopyOption.REPLACE_EXISTING);
        }
    }

    private static void require(boolean condition, String message) {
        if (!condition) throw new IllegalArgumentException(message);
    }

    private static Map<String, Object> fields(Object... pairs) {
        Map<String, Object> result = new LinkedHashMap<>();
        for (int index = 0; index < pairs.length; index += 2) result.put((String) pairs[index], pairs[index + 1]);
        return result;
    }

    /** 本模板只输出明确的身份字符串、布尔值和映射，不调用未知对象的toString。 */
    private static String json(Object value) {
        if (value == null) return "null";
        if (value instanceof Boolean) return value.toString();
        if (value instanceof String) {
            StringBuilder result = new StringBuilder("\"");
            for (char character : ((String) value).toCharArray()) {
                if (character == '\\' || character == '"') result.append('\\').append(character);
                else if (character < 32) result.append(String.format("\\u%04x", (int) character));
                else result.append(character);
            }
            return result.append('"').toString();
        }
        if (value instanceof Map<?, ?>) {
            List<String> entries = new ArrayList<>();
            for (Map.Entry<?, ?> entry : ((Map<?, ?>) value).entrySet())
                entries.add(json(entry.getKey()) + ":" + json(entry.getValue()));
            return "{" + String.join(",", entries) + "}";
        }
        throw new IllegalArgumentException("Unsupported lifecycle metadata value");
    }
}

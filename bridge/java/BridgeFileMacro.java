import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import star.base.neo.NamedObject;
import star.common.*;

/**
 * 在 STAR 已加载的算例中读取、设置标量或显式另存，供文件与会话 Runner 共用。
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
            // 1. 先记录完整的已覆盖参数快照，便于区分目标修改与依赖值变化。
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
            String after = snapshot(sim);
            Files.writeString(Path.of(RESULT),
                "{\"status\":\"ok\",\"before\":" + before + ",\"after\":" + after + "}",
                StandardCharsets.UTF_8);
        } catch (Exception error) {
            throw new RuntimeException("StarBridge macro failed", error);
        }
    }

    /** 输出按名称排序的快照；无法读取的参数保留名称、类型及错误。 */
    private String snapshot(Simulation sim) {
        List<NamedObject> objects = new ArrayList<>(
            sim.get(GlobalParameterManager.class).getObjects());
        objects.sort(Comparator.comparing(NamedObject::getPresentationName));
        List<String> parameters = new ArrayList<>();
        for (NamedObject object : objects) {
            String entry = "{\"name\":" + quote(object.getPresentationName())
                + ",\"object_type\":" + quote(object.getClass().getSimpleName());
            try {
                if (object instanceof ScalarGlobalParameter) {
                    ScalarPhysicalQuantity q = ((ScalarGlobalParameter) object).getQuantity();
                    entry += ",\"definition\":" + quote(q.getDefinition())
                        + ",\"unit\":" + quote(q.getUnits().getPresentationName())
                        + ",\"raw_value\":" + number(q.getRawValue())
                        + ",\"si_value\":" + number(q.getSIValue());
                } else if (object instanceof VectorGlobalParameter) {
                    VectorPhysicalQuantity q = ((VectorGlobalParameter) object).getQuantity();
                    List<String> components = new ArrayList<>();
                    for (double component : q.getRawVector().toDoubleArray()) {
                        components.add(number(component));
                    }
                    entry += ",\"definition\":" + quote(q.getDefinition())
                        + ",\"unit\":" + quote(q.getUnits().getPresentationName())
                        + ",\"raw_value\":[" + String.join(",", components) + "]";
                } else {
                    entry += ",\"unsupported\":true";
                }
            } catch (Exception error) {
                entry += ",\"read_error\":" + quote(error.toString());
            }
            parameters.add(entry + "}");
        }
        return "{\"simulation_name\":" + quote(sim.getPresentationName())
            + ",\"session_path\":" + quote(sim.getSessionPath())
            + ",\"modified\":" + sim.isModified()
            + ",\"parameters\":[" + String.join(",", parameters) + "]}";
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

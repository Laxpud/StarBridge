import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.CodeSource;
import java.lang.reflect.InvocationTargetException;
import star.common.StarMacro;
import star.base.neo.NeoScriptFile;

/**
 * STAR 只再次编译这个受信启动宏；用户程序已按所选安装及冻结依赖统一编译。
 * 用字符串加载预编译包装器，避免 STAR 的不同 classpath／当前目录规则再次编译用户代码。
 * 实际身份、初始化、步骤状态与结果仍由包装器记录，此层不推断任务成功。
 */
public class __LAUNCH_CLASS__ extends StarMacro {
    @Override
    public void execute() {
        try {
            Class<?> programType = Class.forName(__PROGRAM_CLASS__, false, getClass().getClassLoader());
            CodeSource origin = programType.getProtectionDomain().getCodeSource();
            if (origin == null || !"file".equals(origin.getLocation().getProtocol())
                    || !Files.isSameFile(Path.of(origin.getLocation().toURI()), Path.of(__CLASSES__)))
                throw new IllegalStateException("Program did not load from this request compilation");
            StarMacro program = (StarMacro) programType.getConstructor().newInstance();
            program.setActiveSimulation(getActiveSimulation());
            // 普通代码步骤的 resolvePath 仍使用原请求包装器的位置，而非另造数据根。
            program.savePath(new NeoScriptFile(new File(__PROGRAM_SOURCE__)));
            program.execute();
        } catch (Throwable error) {
            Throwable cause = error instanceof InvocationTargetException && error.getCause() != null
                    ? error.getCause() : error;
            cause.printStackTrace();
            throw new RuntimeException("Precompiled StarBridge program failed; inspect its receipt and log", cause);
        }
    }
}

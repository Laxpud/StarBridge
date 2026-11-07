import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.CodeSource;
import java.lang.reflect.InvocationTargetException;
import java.net.URL;
import java.net.URLClassLoader;
import star.common.StarMacro;
import star.base.neo.NeoScriptFile;

/**
 * STAR 只再次编译这个受信启动宏；用户程序已按所选安装及冻结依赖统一编译。
 * STAR 编译此入口时只接收私有空用户 classpath；冻结的用户 JAR 不进入其 javac 插件发现。
 * 编译完成后才创建独立的运行加载器，保留 STAR 类型身份、完整宏、辅助类和 JAR 内资源。
 * 实际身份、初始化、步骤状态与结果仍由包装器记录；加载器建立不等于已运行用户声明。
 */
public class __LAUNCH_CLASS__ extends StarMacro {
    @Override
    public void execute() {
        Thread thread = Thread.currentThread();
        ClassLoader previousContext = thread.getContextClassLoader();
        try {
            String[] paths = __RUNTIME_PATHS__;
            URL[] urls = new URL[paths.length];
            for (int index = 0; index < paths.length; index++)
                urls[index] = new File(paths[index]).toURI().toURL();
            // 父加载器保留本次 STAR 模块身份；不把工作目录、原源码目录或旧 TCCL 加入用户路径。
            URLClassLoader runtime = new URLClassLoader(urls, getClass().getClassLoader());
            thread.setContextClassLoader(runtime);
            Class<?> programType = Class.forName(__PROGRAM_CLASS__, false, runtime);
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
        } finally {
            thread.setContextClassLoader(previousContext);
            // 不在同步入口返回时关闭 runtime：用户线程仍可能懒加载类或资源。加载器随本次客户端
            // 终止释放；这不保证异步工作完成，也不使嵌套 STAR 源宏编译继承这些运行期 URL。
        }
    }
}

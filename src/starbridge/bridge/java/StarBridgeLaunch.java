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
    /**
     * 本请求的包装器与其内部类只从本次classes取得；STAR/JDK及其他依赖仍遵守父委派。
     * 纯code沿用StarBridgeProgram类名，不能让父加载器中同名的旧包装器替代它；
     * 对象绑定时内联的DiscoveryRuntime也必须与本次包装器处于同一运行期package。
     * 不把所有用户JAR改成子优先，也不改变资源或SPI描述符的既有查找顺序。
     */
    private static final class RequestClassLoader extends URLClassLoader {
        private final String programName;
        private final boolean inlineDiscovery;
        private final Path classes;

        RequestClassLoader(URL[] urls, ClassLoader parent, String programName,
                           boolean inlineDiscovery, Path classes) {
            super(urls, parent);
            this.programName = programName;
            this.inlineDiscovery = inlineDiscovery;
            this.classes = classes;
        }

        private boolean belongsTo(String name, String owner) {
            return name.equals(owner) || name.startsWith(owner + "$");
        }

        @Override
        protected Class<?> loadClass(String name, boolean resolve) throws ClassNotFoundException {
            if (!belongsTo(name, programName) && !(inlineDiscovery && belongsTo(name, "DiscoveryRuntime")))
                return super.loadClass(name, resolve);
            synchronized (getClassLoadingLock(name)) {
                Class<?> type = findLoadedClass(name);
                // 只加载，不初始化；找不到本次生成类时失败，不向父级回退。
                if (type == null) type = findClass(name);
                try {
                    CodeSource origin = type.getProtectionDomain().getCodeSource();
                    if (type.getClassLoader() != this || origin == null
                            || !"file".equals(origin.getLocation().getProtocol())
                            || !Files.isSameFile(Path.of(origin.getLocation().toURI()), classes))
                        throw new IllegalStateException("Generated class did not load from this request compilation: " + name);
                } catch (Exception error) {
                    throw new ClassNotFoundException("Invalid generated class origin: " + name, error);
                }
                if (resolve) resolveClass(type);
                return type;
            }
        }
    }

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
            URLClassLoader runtime = new RequestClassLoader(urls, getClass().getClassLoader(),
                    __PROGRAM_CLASS__, __LOCAL_DISCOVERY__, Path.of(__CLASSES__));
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

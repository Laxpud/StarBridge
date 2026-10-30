#!/usr/bin/env python3
"""以最小 STAR 接口替身编译真实 DiscoveryRuntime，验证 R6/R8 提供器契约。

全部源码、class 文件和执行输出位于临时目录，不加载 STAR 库或启动算例。
替身只控制身份、子对象和描述符输入；被验证的解析、去重、错误处理来自
仓库生产 Java 文件。结果不计入真实 STAR 行为或版本兼容覆盖。
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]

STUBS = {
    'star/base/neo/ClientServerObject.java': r'''
package star.base.neo;
public class ClientServerObject {
    public String key, name;
    public ClientServerObject parent;
    public java.util.List<Object> children = new java.util.ArrayList<>();
    public java.beans.PropertyDescriptor[] descriptors = new java.beans.PropertyDescriptor[0];
    public ClientServerObject(String key, String name) { this.key = key; this.name = name; }
    public String getObjectKeyAsString() { return key; }
    public String getPresentationName() { return name; }
    public ClientServerObject getParent() { return parent; }
    public java.util.Collection<?> getChildren() { return children; }
    public java.beans.PropertyDescriptor[] getBeanPropertyDescriptors() { return descriptors; }
    public java.beans.PropertyDescriptor[] getLinkedBeanPropertyDescriptors() {
        return new java.beans.PropertyDescriptor[0];
    }
}
''',
    'star/common/Simulation.java': r'''
package star.common;
public class Simulation extends star.base.neo.ClientServerObject {
    public Simulation() { super("root", "Simulation"); }
    public String getCurrentVersion() { return "2602"; }
    public String getReleaseNumber() { return "21.02.007"; }
}
''',
    'star/common/Units.java': r'''
package star.common;
public class Units extends star.base.neo.ClientServerObject {
    public Units() { super("units", "m"); }
}
''',
    'star/base/neo/ScalarRange.java': r'''
package star.base.neo;
public class ScalarRange {
    public star.common.Units getUnits() { return null; }
    public boolean hasMin() { return true; }
    public boolean hasMax() { return true; }
    public double getMin() { return 0; }
    public double getMax() { return 1; }
    public boolean contains(double value) { return value >= 0 && value <= 1; }
    public boolean isIntegral() { return false; }
}
''',
}

HARNESS = r'''
import java.util.*;
import star.base.neo.ClientServerObject;
import star.common.Simulation;

public class DiscoveryContractHarness {
    static final String TOKEN = "fixture-session";
    static int checks = 0;

    public static class Bean extends ClientServerObject {
        static int getterCalls = 0;
        boolean linkedFailure = false;
        Bean(String key, String name) { super(key, name); }
        public double getValue() { getterCalls++; throw new IllegalStateException("Getter must not execute"); }
        @Override public java.beans.PropertyDescriptor[] getLinkedBeanPropertyDescriptors() {
            if (linkedFailure) throw new IllegalStateException("Linked metadata failure");
            return super.getLinkedBeanPropertyDescriptors();
        }
    }

    /** 仅元数据访问失败；getter 是否执行由独立计数器检查。 */
    static class BrokenDescriptor extends java.beans.PropertyDescriptor {
        BrokenDescriptor() throws Exception { super("broken", Bean.class, "getValue", null); }
        @Override public Enumeration<String> attributeNames() {
            return Collections.enumeration(List.of("broken_attribute"));
        }
        @Override public Object getValue(String name) { throw new IllegalStateException("Metadata attribute failure"); }
    }

    static Map<String,Object> fields(Object... pairs) {
        Map<String,Object> result = new LinkedHashMap<>();
        for (int i = 0; i < pairs.length; i += 2) result.put((String)pairs[i], pairs[i+1]);
        return result;
    }
    @SuppressWarnings("unchecked") static Map<String,Object> map(Object value) { return (Map<String,Object>)value; }
    @SuppressWarnings("unchecked") static List<Object> list(Object value) { return (List<Object>)value; }
    static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
    static Map<String,Object> run(Simulation sim, Map<String,Object> request) {
        return DiscoveryRuntime.run(sim, request, TOKEN);
    }
    static Map<String,Object> target(Object path) { return fields("session_token", TOKEN, "path", path); }
    static void rejected(Runnable action, String reason) {
        try { action.run(); } catch (IllegalArgumentException expected) {
            require(expected.getMessage().contains(reason), "Unexpected rejection: " + expected.getMessage());
            return;
        }
        throw new AssertionError("Expected rejection: " + reason);
    }
    static Bean attach(Simulation sim, String key, String name) {
        Bean bean = new Bean(key, name); bean.parent = sim; sim.children.add(bean); return bean;
    }
    static Map<String,Object> firstChild(Simulation sim) {
        return map(list(run(sim, fields("action", "browse")).get("children")).get(0));
    }

    static void duplicateIdentity() {
        Simulation sim = new Simulation(); Bean bean = attach(sim, "a", "same"); sim.children.add(bean);
        Map<String,Object> result = run(sim, fields("action", "browse"));
        require(list(result.get("children")).size() == 1, "Duplicate children were not deduplicated");
        Object path = map(list(result.get("children")).get(0)).get("path");
        require("a".equals(map(run(sim, fields("action", "describe", "target", target(path))).get("node")).get("key")),
                "Same-key duplicate falsely rejected during resolution");
        DiscoveryRuntime.checkBinding(sim, target(path), TOKEN);
        checks++;
    }

    static void ambiguousRelocation() {
        Simulation sim = new Simulation(); attach(sim, "old", "same"); Object path = firstChild(sim).get("path");
        attach(sim, "another", "same");
        rejected(() -> run(sim, fields("action", "describe", "target", target(path), "relocate", true)), "Ambiguous");
        checks++;
    }

    static void recreatedKey() {
        Simulation sim = new Simulation(); attach(sim, "old", "same"); Object path = firstChild(sim).get("path");
        sim.children.clear(); attach(sim, "new", "same");
        rejected(() -> run(sim, fields("action", "describe", "target", target(path))), "disappeared or changed");
        rejected(() -> DiscoveryRuntime.checkBinding(sim, target(path), TOKEN), "disappeared or changed");
        checks++;
    }

    static void cycleAndUnknownProxy() {
        Simulation sim = new Simulation(); Bean bean = attach(sim, "a", "child");
        Object path = firstChild(sim).get("path"); bean.children.add(sim);
        bean.children.add(new Object() {
            @Override public String toString() { throw new AssertionError("Unknown proxy toString must not execute"); }
        });
        List<Object> children = list(run(sim, fields("action", "browse", "target", target(path))).get("children"));
        require(children.size() == 2, "Cycle or unknown proxy omitted");
        boolean cycle = false, unknown = false;
        for (Object raw : children) {
            Map<String,Object> child = map(raw);
            require("proxy".equals(child.get("kind")) && "unsupported".equals(child.get("children_state")),
                    "Proxy was marked expandable");
            if ("root".equals(child.get("reference_key"))) cycle = true;
            if (child.get("key") == null) unknown = true;
        }
        require(cycle && unknown, "Cycle and non-CSO proxy must remain distinguishable");
        checks++;
    }

    static void descriptorsNeverInvokeGetter() throws Exception {
        Simulation sim = new Simulation(); Bean bean = attach(sim, "a", "child");
        bean.descriptors = new java.beans.PropertyDescriptor[] {
            new java.beans.PropertyDescriptor("value", Bean.class, "getValue", null)};
        Object path = firstChild(sim).get("path");
        Map<String,Object> result = run(sim, fields("action", "describe", "target", target(path)));
        require(list(result.get("properties")).size() == 1, "Valid descriptor missing");
        require(Bean.getterCalls == 0, "Description executed property getter");
        checks++;
    }

    static void localMetadataFailurePreservesSuccess() throws Exception {
        Simulation sim = new Simulation(); Bean bean = attach(sim, "a", "child");
        bean.descriptors = new java.beans.PropertyDescriptor[] {
            new java.beans.PropertyDescriptor("value", Bean.class, "getValue", null), new BrokenDescriptor()};
        bean.linkedFailure = true;
        Object path = firstChild(sim).get("path");
        Map<String,Object> result = run(sim, fields("action", "describe", "target", target(path)));
        require("partial".equals(result.get("state")), "Metadata failure must report partial coverage");
        require(list(result.get("properties")).size() == 1, "Local error removed successful descriptor");
        require(list(result.get("errors")).size() == 2, "Descriptor and provider errors were not retained");
        require(Bean.getterCalls == 0, "Metadata failure triggered getter fallback");
        checks++;
    }

    public static void main(String[] args) throws Exception {
        duplicateIdentity(); ambiguousRelocation(); recreatedKey(); cycleAndUnknownProxy();
        descriptorsNeverInvokeGetter(); localMetadataFailurePreservesSuccess();
        System.out.println("{\"successful\":true,\"checks_run\":" + checks + "}");
    }
}
'''


def compiler():
    """优先已有 PATH JDK，再寻找本机 Siemens 安装随附 JDK，不下载依赖。"""
    candidates = []
    if shutil.which('javac'):
        candidates.append(Path(shutil.which('javac')))
    if os.environ.get('JAVA_HOME'):
        candidates.append(Path(os.environ['JAVA_HOME']) / 'bin/javac')
    candidates.extend(sorted(Path('/usr/lib/jvm').glob('*/bin/javac')))
    candidates.extend(sorted(Path('/opt/Siemens').glob('*/jdk/*/*/bin/javac'), reverse=True))
    for candidate in candidates:
        executable = candidate.resolve()
        java = executable.with_name('java')
        if executable.is_file() and java.is_file() and os.access(executable, os.X_OK):
            return executable, java
    raise RuntimeError('A local JDK with javac and java is required')


def main():
    """临时编译并执行生产提供器，stdout 输出明确排除真实 STAR 覆盖的 JSON。"""
    report = {'scope': 'DiscoveryRuntime Java provider R6/R8 simulated contracts',
              'real_star_coverage': False, 'uses_star_libraries': False,
              'checks': ['same_key_duplicate_resolution', 'ambiguous_name_class_relocation',
                         'recreated_key_rejection', 'cycle_and_unknown_proxy',
                         'metadata_does_not_execute_getter', 'local_metadata_error_isolation']}
    try:
        javac, java = compiler()
        with tempfile.TemporaryDirectory(prefix='starbridge-java-discovery-contract-') as directory:
            work = Path(directory)
            for relative, source in {**STUBS, 'DiscoveryContractHarness.java': HARNESS}.items():
                path = work / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source, encoding='utf-8')
            shutil.copyfile(ROOT / 'bridge/java/DiscoveryRuntime.java', work / 'DiscoveryRuntime.java')
            sources = sorted(str(path) for path in work.rglob('*.java'))
            built = subprocess.run([str(javac), '-encoding', 'UTF-8', '-d', str(work / 'classes'), *sources],
                                   capture_output=True, text=True, timeout=60)
            if built.returncode:
                raise RuntimeError('Java compilation failed: ' + built.stderr)
            ran = subprocess.run([str(java), '-cp', str(work / 'classes'), 'DiscoveryContractHarness'],
                                 capture_output=True, text=True, timeout=30)
            if ran.returncode:
                raise RuntimeError('Java contracts failed: ' + ran.stderr)
            report.update(json.loads(ran.stdout))
            report['compiler'] = str(javac)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        report.update(successful=False, error=str(error))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get('successful') else 1


if __name__ == '__main__':
    raise SystemExit(main())

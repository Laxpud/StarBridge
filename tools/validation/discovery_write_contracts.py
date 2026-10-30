#!/usr/bin/env python3
"""用本机 STAR 库编译生产 Java，验证 W3 快照影响比较的纯数据契约。

Java harness 只调用 verifyDiscoverySnapshot，不构造 Simulation、不连接服务、
不执行 setter，也不把这些检查计入真实算例写入或持久化验收。源码和 class
输出放在临时目录；STAR 安装只提供编译及类加载依赖。
"""

import argparse
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]

HARNESS = r'''
import java.util.*;

public class DiscoveryWriteContractHarness {
    static final List<String> passed = new ArrayList<>();
    static Map<String, Object> fields(Object... pairs) {
        Map<String, Object> result = new LinkedHashMap<>();
        for (int index = 0; index < pairs.length; index += 2) result.put((String) pairs[index], pairs[index + 1]);
        return result;
    }
    @SuppressWarnings("unchecked") static Map<String, Object> map(Object value) { return (Map<String, Object>) value; }
    @SuppressWarnings("unchecked") static List<Object> list(Object value) { return (List<Object>) value; }
    static Object copy(Object value) {
        if (value instanceof Map<?, ?>) {
            Map<String, Object> result = new LinkedHashMap<>();
            for (Map.Entry<String, Object> item : map(value).entrySet()) result.put(item.getKey(), copy(item.getValue()));
            return result;
        }
        if (value instanceof List<?>) {
            List<Object> result = new ArrayList<>();
            for (Object item : list(value)) result.add(copy(item));
            return result;
        }
        return value;
    }
    static CatalogRuntime.SnapshotCapture copied(CatalogRuntime.SnapshotCapture source) {
        CatalogRuntime.SnapshotCapture result = new CatalogRuntime.SnapshotCapture();
        result.snapshot = map(copy(source.snapshot)); result.bindings.clear(); result.bindings.putAll(map(copy(source.bindings)));
        return result;
    }
    /** 使用与生产 capture 相同的旁路结构，完全独立于任何 STAR 服务对象。 */
    static CatalogRuntime.SnapshotCapture capture(boolean vector) {
        CatalogRuntime.SnapshotCapture result = new CatalogRuntime.SnapshotCapture();
        Map<String, Object> quantity = vector
                ? fields("definition", "[1,2,3]", "unit", "m", "components", new ArrayList<>(List.of(1.0, 2.0, 3.0)))
                : fields("definition", "1.0", "unit", "m", "si_unit", "m", "raw_value", 1.0, "si_value", 1.0);
        result.snapshot = fields("schema_version", 1, "simulation_name", "fixture", "session_path", "/isolated/fixture.sim",
                "modified", false, "inspection_complete", true, "read_errors", new ArrayList<>(),
                "parameters", new ArrayList<>(List.of(fields("name", "_Discovery/Identity", "quantity", quantity))),
                "other", fields("name", "retained", "value", 9.0));
        map(result.bindings.get("objects")).put("/parameters/0", fields("key", "owner_1", "java_class", "FixtureOwner"));
        map(result.bindings.get("fields")).put("/parameters/0/quantity", fields("key", "quantity_1",
                "java_class", vector ? "star.common.VectorPhysicalQuantity" : "star.common.ScalarPhysicalQuantity",
                "adapter", vector ? "vector" : "quantity", "selected", new ArrayList<>(),
                "allowed_suffixes", vector ? List.of("/components", "/definition", "/unit")
                                           : List.of("/definition", "/raw_value", "/si_value", "/unit")));
        return result;
    }
    static Map<String, Object> target(boolean vector) {
        return fields("key", "quantity_1", "java_class", vector ? "star.common.VectorPhysicalQuantity" : "star.common.ScalarPhysicalQuantity",
                "adapter", vector ? "vector_value" : "scalar_value");
    }
    static Map<String, Object> quantity(CatalogRuntime.SnapshotCapture capture) {
        return map(map(list(capture.snapshot.get("parameters")).get(0)).get("quantity"));
    }
    static void require(boolean condition, String message) { if (!condition) throw new AssertionError(message); }
    static Map<String, Object> accepts(String label, CatalogRuntime.SnapshotCapture before,
            CatalogRuntime.SnapshotCapture after, Map<String, Object> target) {
        Map<String, Object> scope = CatalogRuntime.verifyDiscoverySnapshot(before, after, target);
        require("passed".equals(scope.get("verification")), "Missing verification result"); passed.add(label); return scope;
    }
    static void rejects(String label, CatalogRuntime.SnapshotCapture before,
            CatalogRuntime.SnapshotCapture after, Map<String, Object> target, String expected) {
        try { CatalogRuntime.verifyDiscoverySnapshot(before, after, target); }
        catch (IllegalArgumentException error) {
            require(error.getMessage().contains(expected), "Unexpected rejection: " + error.getMessage()); passed.add(label); return;
        }
        throw new AssertionError("Expected rejection: " + label);
    }
    public static void main(String[] arguments) {
        CatalogRuntime.SnapshotCapture before = capture(false), after = copied(before);
        quantity(after).putAll(fields("definition", "200.0", "unit", "cm", "raw_value", 200.0, "si_value", 2.0));
        Map<String, Object> scope = accepts("target_scalar_fields", before, after, target(false));
        require(list(scope.get("allowed_snapshot_pointers")).size() == 4, "Unexpected scalar allowed scope");
        require("bound_quantity_fields".equals(scope.get("mode")), "Unexpected bound mode");
        before = capture(true); after = copied(before);
        quantity(after).putAll(fields("definition", "[4,5,6]", "unit", "cm", "components", List.of(4.0, 5.0, 6.0)));
        accepts("target_vector_fields", before, after, target(true));
        before = capture(false); after = copied(before); map(after.snapshot.get("other")).put("value", 10.0);
        rejects("non_target_content", before, after, target(false), "/other/value");
        after = copied(before); quantity(after).put("si_unit", "s");
        rejects("undeclared_quantity_field", before, after, target(false), "/si_unit");
        after = copied(before); map(map(after.bindings.get("fields")).get("/parameters/0/quantity")).put("key", "quantity_recreated");
        rejects("field_binding_key", before, after, target(false), "binding changed");
        after = copied(before); map(map(after.bindings.get("objects")).get("/parameters/0")).put("key", "owner_recreated");
        rejects("owner_binding_key", before, after, target(false), "binding changed");
        after = copied(before); Map<String, Object> bound = map(after.bindings.get("fields"));
        bound.put("/parameters/1/quantity", bound.remove("/parameters/0/quantity"));
        rejects("binding_pointer", before, after, target(false), "binding changed");
        Map<String, Object> outside = target(false); outside.put("key", "outside_snapshot");
        scope = accepts("outside_target_unchanged", before, copied(before), outside);
        require("unchanged_snapshot".equals(scope.get("mode")) && list(scope.get("allowed_snapshot_pointers")).isEmpty(), "Unexpected outside scope");
        after = copied(before); quantity(after).put("raw_value", 2.0);
        rejects("outside_target_changed", before, after, outside, "/raw_value");
        after = copied(before); after.snapshot.put("modified", true);
        accepts("modified_metadata_only", before, after, outside);
        after = copied(before); after.snapshot.put("session_path", "/different.sim");
        rejects("session_path_preserved", before, after, target(false), "/session_path");
        after = copied(before); after.snapshot.put("simulation_name", "renamed");
        rejects("simulation_name_preserved", before, after, target(false), "/simulation_name");
        after = copied(before); map(list(after.snapshot.get("parameters")).get(0)).put("name", "renamed/object");
        rejects("object_name_preserved", before, after, target(false), "/parameters/0/name");
        after = copied(before); quantity(after).put("raw_value", 2.0);
        Map<String, Object> primitive = target(false); primitive.put("adapter", "primitive");
        rejects("primitive_no_implicit_scope", before, after, primitive, "/raw_value");
        after = copied(before); after.snapshot.put("inspection_complete", false);
        rejects("incomplete_snapshot", before, after, target(false), "incomplete");
        System.out.println("{\"checks\":" + passed.size() + ",\"passed\":[\"" + String.join("\",\"", passed) + "\"]}");
    }
}
'''


def main():
    """在临时目录编译并执行纯比较器；失败保留进程错误，不改用户算例。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installation', type=Path, default=Path('/opt/Siemens/21.02.007-R8'))
    args = parser.parse_args()
    installation = args.installation.resolve(strict=True)
    compilers = sorted(installation.glob('jdk/**/bin/javac'))
    if len(compilers) != 1:
        raise RuntimeError('Expected exactly one bundled JDK compiler in the selected installation')
    javac = compilers[0]
    java = javac.with_name('java')
    jars = sorted(installation.rglob('*.jar'))
    if not jars:
        raise RuntimeError('No STAR Java libraries found in the selected installation')
    classpath = ':'.join(map(str, jars))
    with tempfile.TemporaryDirectory(prefix='starbridge-write-contracts-') as directory:
        temporary = Path(directory)
        harness = temporary / 'DiscoveryWriteContractHarness.java'
        harness.write_text(HARNESS, encoding='utf-8')
        compiled = subprocess.run([str(javac), '-proc:none', '-cp', classpath, '-d', directory,
            str(ROOT / 'bridge/java/CatalogRuntime.java'), str(ROOT / 'bridge/java/DiscoveryRuntime.java'),
            str(harness)], capture_output=True, text=True, timeout=90, check=True)
        executed = subprocess.run([str(java), '-cp', directory + ':' + classpath,
            'DiscoveryWriteContractHarness'], capture_output=True, text=True, timeout=30, check=True)
        result = json.loads(executed.stdout)
        print(json.dumps({'scope': 'pure_snapshot_impact_contracts', 'real_simulation_write': False,
            'installation': str(installation), **result, 'compiler_notes': compiled.stderr.strip()}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

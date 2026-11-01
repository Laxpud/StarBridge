/**
 * 在已验证的精确版本上枚举一层服务对象，或描述当前实例的 Bean 元数据。
 * 请求来自 Core 的内部引用；本类不执行描述符 getter、setter 或属性编辑器。
 */
class DiscoveryRuntime {
    /**
     * 在执行计划进入读取或修改管线前重新核对发现时的完整身份绑定。
     * 只走身份与子对象枚举，不读取描述符或属性；不经 CatalogRuntime 回调，避免版本校验递归。
     */
    public static void checkBinding(star.common.Simulation sim, java.util.Map<String, Object> binding, String token) {
        require("2602".equals(sim.getCurrentVersion()) && "21.02.007".equals(sim.getReleaseNumber()),
                "Discovery binding version is unsupported");
        require(binding != null && token != null && !token.isEmpty(), "Discovery binding and session token are required");
        Budget budget = new Budget(fields("max_nodes", 20000, "timeout_ms", 30000));
        resolve(sim, binding, token, false, new java.util.ArrayList<>(), budget);
        require(!budget.expired(), "Discovery binding resolution timed out");
    }

    /** 核对版本、会话和完整父路径后执行一次有界发现；局部元数据错误保留成功项。 */
    public static java.util.Map<String, Object> run(star.common.Simulation sim, java.util.Map<String, Object> request, String token) {
        require("2602".equals(sim.getCurrentVersion()) && "21.02.007".equals(sim.getReleaseNumber()), "Discovery version is unsupported");
        require(token != null && !token.isEmpty(), "Session token is required");
        Budget budget = new Budget(request);
        boolean relocate = Boolean.TRUE.equals(request.get("relocate"));
        java.util.List<Object> path = new java.util.ArrayList<>();
        star.base.neo.ClientServerObject target = resolve(sim, request.get("target"), token, relocate, path, budget);
        java.util.Map<String, Object> result = fields("runtime", fields("release", sim.getCurrentVersion(), "build", sim.getReleaseNumber(), "session_token", token),
                "node", node(target, path), "errors", new java.util.ArrayList<>(), "truncations", new java.util.ArrayList<>(),
                "applied_budget", fields("max_nodes", budget.maxNodes, "timeout_ms", budget.timeoutMs, "depth", 1, "limit", budget.limit));
        String action = (String) request.get("action");
        if ("browse".equals(action)) browse(target, path, request, result, budget);
        else if ("describe".equals(action)) describe(target, result, budget);
        else throw new IllegalArgumentException("Unsupported discovery action");
        result.put("elapsed_ms", (System.nanoTime() - budget.started) / 1000000L);
        return result;
    }

    /**
     * 普通引用逐层核对 key、名称和类型，保证重建的同名对象不能替代旧对象。
     * 显式重定位只按结构化名称和类型匹配，每层都要求唯一；其结果形成新的会话引用。
     */
    private static star.base.neo.ClientServerObject resolve(star.common.Simulation sim, Object raw, String token, boolean relocate,
            java.util.List<Object> actualPath, Budget budget) {
        star.base.neo.ClientServerObject current = sim;
        if (raw == null) { actualPath.add(identity(current)); return current; }
        java.util.Map<String, Object> target = map(raw);
        require(relocate || token.equals(target.get("session_token")), "Stale discovery session token");
        java.util.List<?> path = (java.util.List<?>) target.get("path");
        require(path != null && !path.isEmpty() && path.size() <= 64, "Invalid discovery path");
        // 显式跨加载重定位以当前 Simulation 为锚点；保存副本可能更改根显示名称。
        require(relocate ? current.getClass().getName().equals(map(path.get(0)).get("java_class"))
                : matches(current, map(path.get(0)), false), "Discovery root identity changed");
        actualPath.add(identity(current));
        for (int depth = 1; depth < path.size(); depth++) {
            require(!budget.expired(), "Discovery identity resolution timed out");
            java.util.Map<String, Object> expected = map(path.get(depth));
            star.base.neo.ClientServerObject found = null;
            int inspected = 0;
            for (Object child : current.getChildren()) {
                require(++inspected <= budget.maxNodes && !budget.expired(), "Discovery identity resolution budget exceeded");
                if (!(child instanceof star.base.neo.ClientServerObject) || !matches((star.base.neo.ClientServerObject) child, expected, relocate)) continue;
                star.base.neo.ClientServerObject candidate = (star.base.neo.ClientServerObject) child;
                // 同一对象可被提供器重复引用；只有不同 key 的同名同类型对象才构成歧义。
                require(found == null || found.getObjectKeyAsString().equals(candidate.getObjectKeyAsString()),
                        "Ambiguous discovery path");
                found = candidate;
            }
            require(found != null, "Discovery target disappeared or changed");
            current = found; actualPath.add(identity(current));
        }
        return current;
    }

    /** 单层枚举只接受 star.base.neo.ClientServerObject 的已核验接口；其他元素返回不可展开代理，不调用其方法。 */
    private static void browse(star.base.neo.ClientServerObject target, java.util.List<Object> path, java.util.Map<String, Object> request,
            java.util.Map<String, Object> result, Budget budget) {
        java.util.List<Object> items = new java.util.ArrayList<>();
        java.util.List<Object> relations = new java.util.ArrayList<>();
        java.util.Set<String> seen = new java.util.HashSet<>();
        boolean complete = true;
        int filtered = 0, inspected = 0;
        String scope = request.containsKey("scope") ? (String) request.get("scope") : "simulation";
        require("simulation".equals(scope) || "all".equals(scope), "Unsupported discovery scope");
        try {
            for (Object child : target.getChildren()) {
                if (inspected >= budget.maxNodes || budget.expired()) {
                    truncation(result, budget.expired() ? "time_budget" : "node_budget"); complete = false; break;
                }
                int ordinal = inspected++;
                try {
                    if (!(child instanceof star.base.neo.ClientServerObject)) {
                        items.add(fields("kind", "proxy", "key", null, "name", "Unsupported proxy", "label", "Unsupported proxy",
                                "java_class", child == null ? null : child.getClass().getName(), "proxy_ordinal", ordinal,
                                "path", path, "children_state", "unsupported", "property_state", "unsupported",
                                "reason", "No verified provider for non-star.base.neo.ClientServerObject child", "relations", new java.util.ArrayList<>()));
                        continue;
                    }
                    star.base.neo.ClientServerObject object = (star.base.neo.ClientServerObject) child;
                    if ("simulation".equals(scope) && hierarchy(object.getClass()).contains("star.material.MaterialDataBaseManager")) { filtered++; continue; }
                    String key = object.getObjectKeyAsString();
                    star.base.neo.ClientServerObject parent = object.getParent();
                    boolean owned = parent != null && parent.getObjectKeyAsString().equals(target.getObjectKeyAsString());
                    relations.add(fields("kind", owned ? "owns" : "references", "target_key", key, "java_class", object.getClass().getName()));
                    if (!seen.add(key)) continue;
                    java.util.List<Object> childPath = new java.util.ArrayList<>(path); childPath.add(identity(object));
                    java.util.Map<String, Object> item = node(object, childPath);
                    // 循环保留为关系，不把同一祖先再次暴露成可递归展开的路径。
                    for (Object segment : path) {
                        if (key.equals(map(segment).get("key"))) {
                            item.put("kind", "proxy"); item.put("children_state", "unsupported");
                            item.put("property_state", "unsupported"); item.put("reason", "Cycle reference to ancestor");
                            item.put("reference_key", key); break;
                        }
                    }
                    items.add(item);
                } catch (Exception error) { failure(result, "child", error); complete = false; }
            }
        } catch (Exception error) { failure(result, "children", error); complete = false; }
        // 同步枚举即使返回空集合，也可能已经耗尽时间；不能把超时观察标为完整。
        if (budget.expired()) { truncation(result, "time_budget"); complete = false; }
        items.sort(java.util.Comparator.comparing(DiscoveryRuntime::sortKey));
        map(result.get("node")).put("relations", relations);
        map(result.get("node")).put("children_state", complete ? "complete" : "partial");
        result.put("filtered_count", filtered); result.put("scope", scope);
        page(result, "children", items, complete, budget);
    }

    /** 分别读取普通和 linked 描述符；按 getter 声明、签名和完整描述上下文去重。 */
    private static void describe(star.base.neo.ClientServerObject target, java.util.Map<String, Object> result, Budget budget) {
        java.util.Map<String, java.util.Map<String, Object>> unique = new java.util.LinkedHashMap<>();
        boolean complete = true;
        int inspected = 0;
        for (String source : java.util.Arrays.asList("bean", "linked")) {
            if (budget.expired() || inspected >= budget.maxNodes) {
                truncation(result, budget.expired() ? "time_budget" : "node_budget"); complete = false; break;
            }
            java.beans.PropertyDescriptor[] descriptors;
            try { descriptors = "bean".equals(source) ? target.getBeanPropertyDescriptors() : target.getLinkedBeanPropertyDescriptors(); }
            catch (Exception error) { failure(result, source, error); complete = false; continue; }
            if (descriptors == null) continue;
            for (java.beans.PropertyDescriptor descriptor : descriptors) {
                if (inspected++ >= budget.maxNodes || budget.expired()) { truncation(result, budget.expired() ? "time_budget" : "node_budget"); complete = false; break; }
                try {
                    java.util.Map<String, Object> value = descriptor(descriptor);
                    // Bean 与 linked 描述符可能只因 GUI 排序 Order 不同而重复；排序不是属性声明身份。
                    java.util.Map<String, Object> context = new java.util.LinkedHashMap<>(value);
                    java.util.Map<String, Object> attributes = new java.util.TreeMap<>(map(value.get("attributes")));
                    attributes.remove("Order"); context.put("attributes", attributes);
                    String key = canonical(context);
                    java.util.Map<String, Object> prior = unique.get(key);
                    if (prior == null) { value.put("sources", new java.util.ArrayList<>(java.util.Arrays.asList(source))); unique.put(key, value); }
                    else {
                        ((java.util.List<Object>) prior.get("sources")).add(source);
                        // 保留不同提供器的原始排序和属性标记，去重不丢掉来源信息。
                        java.util.List<Object> variants = (java.util.List<Object>) prior.computeIfAbsent("descriptor_variants", ignored -> new java.util.ArrayList<>());
                        variants.add(fields("source", source, "attributes", value.get("attributes")));
                    }
                } catch (Exception error) { failure(result, "descriptor:" + descriptor.getName(), error); complete = false; }
            }
        }
        if (budget.expired()) { truncation(result, "time_budget"); complete = false; }
        java.util.List<Object> items = new java.util.ArrayList<>(unique.values());
        items.sort(java.util.Comparator.comparing(DiscoveryRuntime::canonical));
        map(result.get("node")).put("property_state", complete ? "complete" : "partial");
        page(result, "properties", items, complete, budget);
    }

    /** 描述符只提供声明与标记；复杂属性值不调用 toString 或实例化编辑器。 */
    private static java.util.Map<String, Object> descriptor(java.beans.PropertyDescriptor p) throws Exception {
        java.util.Map<String, Object> attrs = new java.util.TreeMap<>();
        for (java.util.Enumeration<String> names = p.attributeNames(); names.hasMoreElements();) {
            String name = names.nextElement(); attrs.put(name, metadataValue(p.getValue(name)));
        }
        return fields("name", p.getName(), "display_name", p.getDisplayName(), "description", p.getShortDescription(),
                "property_type", p.getPropertyType() == null ? null : p.getPropertyType().getName(),
                "getter", method(p.getReadMethod()), "setter", method(p.getWriteMethod()),
                "hidden", p.isHidden(), "expert", p.isExpert(), "bound", p.isBound(), "constrained", p.isConstrained(),
                "editor_class", p.getPropertyEditorClass() == null ? null : p.getPropertyEditorClass().getName(), "attributes", attrs);
    }

    /** 注解方法只是元数据访问；这里从不反射调用被描述对象的方法。 */
    private static Object method(java.lang.reflect.Method m) throws Exception {
        if (m == null) return null;
        java.util.List<Object> annotations = new java.util.ArrayList<>();
        for (java.lang.annotation.Annotation a : m.getAnnotations()) {
            java.util.Map<String, Object> values = new java.util.TreeMap<>();
            for (java.lang.reflect.Method attribute : a.annotationType().getDeclaredMethods()) values.put(attribute.getName(), metadataValue(attribute.invoke(a)));
            annotations.add(fields("type", a.annotationType().getName(), "values", values));
        }
        annotations.sort(java.util.Comparator.comparing(DiscoveryRuntime::canonical));
        java.util.List<String> parameters = new java.util.ArrayList<>();
        for (Class<?> type : m.getParameterTypes()) parameters.add(type.getName());
        return fields("owner", m.getDeclaringClass().getName(), "name", m.getName(), "return_type", m.getReturnType().getName(),
                "parameter_types", parameters, "public", java.lang.reflect.Modifier.isPublic(m.getModifiers()), "static", java.lang.reflect.Modifier.isStatic(m.getModifiers()), "annotations", annotations);
    }

    /** 元数据递归仅允许简单值、数组与 Java 声明对象，未知载荷保留实际类型。 */
    private static Object metadataValue(Object value) throws Exception {
        if (value == null || value instanceof String || value instanceof Boolean || value instanceof Number) return value;
        // 2602 ScalarRange 的这些方法已核对为本地数值/字段读取；拒绝子类覆盖扩大调用面。
        if (value.getClass() == star.base.neo.ScalarRange.class) {
            star.base.neo.ScalarRange range = (star.base.neo.ScalarRange) value;
            star.common.Units units = range.getUnits();
            return fields("metadata_class", value.getClass().getName(), "source", "descriptor_range",
                    "minimum", range.hasMin() ? range.getMin() : null, "maximum", range.hasMax() ? range.getMax() : null,
                    "minimum_included", range.hasMin() ? range.contains(range.getMin()) : null,
                    "maximum_included", range.hasMax() ? range.contains(range.getMax()) : null,
                    "integral", range.isIntegral(), "units", units == null ? null : identity(units));
        }
        if (value instanceof Class<?>) return fields("class", ((Class<?>) value).getName());
        if (value instanceof java.lang.reflect.Method) return method((java.lang.reflect.Method) value);
        if (value instanceof Enum<?>) return ((Enum<?>) value).name();
        if (value.getClass().isArray()) {
            java.util.List<Object> result = new java.util.ArrayList<>();
            for (int i = 0; i < java.lang.reflect.Array.getLength(value); i++) result.add(metadataValue(java.lang.reflect.Array.get(value, i)));
            return result;
        }
        if (value instanceof java.lang.annotation.Annotation) {
            java.lang.annotation.Annotation a = (java.lang.annotation.Annotation) value;
            java.util.Map<String, Object> result = fields("annotation", a.annotationType().getName());
            for (java.lang.reflect.Method m : a.annotationType().getDeclaredMethods()) result.put(m.getName(), metadataValue(m.invoke(a)));
            return result;
        }
        return fields("metadata_class", value.getClass().getName());
    }

    /** 页码只针对本次稳定排序后的已观察集合；截断集合没有可声明的完整数量。 */
    private static void page(java.util.Map<String, Object> result, String field, java.util.List<Object> items, boolean complete, Budget budget) {
        int start = Math.min(budget.offset, items.size()), end = Math.min(items.size(), start + budget.limit);
        result.put(field, new java.util.ArrayList<>(items.subList(start, end)));
        result.put("state", complete ? "complete" : "partial");
        result.put("total_count", complete ? items.size() : null);
        result.put("observed_count", items.size());
        result.put("next_offset", end < items.size() ? end : null);
        result.put("fingerprint", digest(canonical(items)));
        result.put("sort", "canonical_identity_or_descriptor");
    }

    /** 节点返回可验证路径和来源，名称含斜杠不会被重新解析成路径分隔符。 */
    private static java.util.Map<String, Object> node(star.base.neo.ClientServerObject object, java.util.List<Object> path) {
        java.util.Map<String, Object> result = identity(object);
        result.putAll(fields("kind", "object", "label", object.getPresentationName(), "path", new java.util.ArrayList<>(path),
                "hierarchy", hierarchy(object.getClass()), "children_state", "not_loaded", "property_state", "not_loaded",
                "relations", new java.util.ArrayList<>(), "relocation", fields("available", true, "requires_unique_path", true),
                "provenance", fields("provider", "cso-bean-v1", "release", "2602", "build", "21.02.007")));
        return result;
    }
    private static java.util.Map<String, Object> identity(star.base.neo.ClientServerObject object) {
        star.base.neo.ClientServerObject parent = object.getParent();
        return fields("key", object.getObjectKeyAsString(), "name", object.getPresentationName(), "java_class", object.getClass().getName(),
                "parent_key", parent == null ? null : parent.getObjectKeyAsString());
    }
    private static boolean matches(star.base.neo.ClientServerObject object, java.util.Map<String, Object> expected, boolean relocate) {
        // STAR 分组的导航边可能是引用边；同时核对枚举边和首次观察到的真实拥有者。
        star.base.neo.ClientServerObject parent = object.getParent();
        String parentKey = parent == null ? null : parent.getObjectKeyAsString();
        return (relocate || (object.getObjectKeyAsString().equals(expected.get("key"))
                && expected.containsKey("parent_key") && java.util.Objects.equals(parentKey, expected.get("parent_key"))))
                && object.getPresentationName().equals(expected.get("name")) && object.getClass().getName().equals(expected.get("java_class"));
    }
    private static java.util.List<String> hierarchy(Class<?> type) {
        java.util.List<String> result = new java.util.ArrayList<>();
        for (Class<?> current = type; current != null; current = current.getSuperclass()) result.add(current.getName());
        return result;
    }
    private static String sortKey(Object raw) {
        java.util.Map<String, Object> item = map(raw);
        return canonical(java.util.Arrays.asList(item.get("name"), item.get("java_class"), item.get("key"), item.get("proxy_ordinal")));
    }
    private static void failure(java.util.Map<String, Object> result, String phase, Exception error) {
        ((java.util.List<Object>) result.get("errors")).add(fields("phase", phase, "error", error.getClass().getName() + ": " + error.getMessage()));
    }
    private static void truncation(java.util.Map<String, Object> result, String reason) { ((java.util.List<Object>) result.get("truncations")).add(fields("reason", reason)); }
    private static java.util.Map<String, Object> map(Object value) { require(value instanceof java.util.Map, "Expected discovery object"); return (java.util.Map<String, Object>) value; }
    private static void require(boolean ok, String message) { if (!ok) throw new IllegalArgumentException(message); }
    private static java.util.Map<String, Object> fields(Object... pairs) {
        java.util.Map<String, Object> result = new java.util.LinkedHashMap<>();
        for (int i = 0; i < pairs.length; i += 2) result.put((String) pairs[i], pairs[i + 1]);
        return result;
    }

    /** 指纹编码使用长度前缀和有序键，避免名称分隔符及哈希碰撞造成静默翻页。 */
    private static String canonical(Object value) {
        if (value == null) return "N";
        if (value instanceof java.util.Map<?, ?>) {
            java.util.Map<String, Object> sorted = new java.util.TreeMap<>((java.util.Map<String, Object>) value);
            StringBuilder out = new StringBuilder("M");
            for (java.util.Map.Entry<String, Object> item : sorted.entrySet()) out.append(canonical(item.getKey())).append(canonical(item.getValue()));
            return out.append(";").toString();
        }
        if (value instanceof java.util.Collection<?>) {
            StringBuilder out = new StringBuilder("L");
            for (Object item : (java.util.Collection<?>) value) out.append(canonical(item));
            return out.append(";").toString();
        }
        String text = String.valueOf(value);
        return value.getClass().getName() + ":" + text.length() + ":" + text;
    }
    private static String digest(String value) {
        try {
            byte[] bytes = java.security.MessageDigest.getInstance("SHA-256").digest(value.getBytes(java.nio.charset.StandardCharsets.UTF_8));
            StringBuilder out = new StringBuilder();
            for (byte b : bytes) out.append(String.format("%02x", b & 255));
            return out.toString();
        } catch (java.security.NoSuchAlgorithmException error) { throw new IllegalStateException(error); }
    }
    /** 时间边界不能中断 STAR 单次同步调用；每次调用返回后都检查剩余预算。 */
    private static final class Budget {
        final long started = System.nanoTime();
        final int maxNodes, timeoutMs, limit, offset;
        Budget(java.util.Map<String, Object> request) {
            maxNodes = number(request, "max_nodes", 2000, 1, 20000);
            timeoutMs = number(request, "timeout_ms", 5000, 1, 120000);
            limit = number(request, "limit", 100, 1, 1000);
            offset = number(request, "offset", 0, 0, 1000000);
        }
        boolean expired() { return (System.nanoTime() - started) / 1000000L >= timeoutMs; }
        static int number(java.util.Map<String, Object> request, String name, int fallback, int min, int max) {
            Object value = request.get(name);
            if (value == null) return fallback;
            require(value instanceof Number, "Invalid discovery budget: " + name);
            long n = ((Number) value).longValue();
            require(n >= min && n <= max && ((Number) value).doubleValue() == n, "Invalid discovery budget: " + name);
            return (int) n;
        }
    }
}

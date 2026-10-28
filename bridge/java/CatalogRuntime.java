/**
 * 在已核对版本的 STAR 会话中执行目录裁剪后的定位、读取和单项修改管线。
 * 本类作为同文件辅助类追加到 BridgeFileMacro 源码；计划由 Python 校验，
 * 请求只能选择目录属性，不能提供 Java 类、方法或任意调用片段。
 */
class CatalogRuntime {
    /** 返回当前 server 的版本与 Runner 会话世代；不使用保存文件的原始版本。 */
    public static java.util.Map<String, Object> metadata(
            star.common.Simulation sim, String sessionToken) {
        require(sessionToken != null && !sessionToken.isEmpty(), "Session token is required");
        return fields("release", string(sim.getCurrentVersion(), "runtime.release"),
                      "build", string(sim.getReleaseNumber(), "runtime.build"),
                      "session_token", sessionToken);
    }

    /** 目录读取和旧快照共用同一版本门槛，目录中的方法只能在匹配的当前服务上执行。 */
    public static java.util.Map<String, Object> checkVersion(star.common.Simulation sim,
            java.util.Map<String, Object> plan, String sessionToken) {
        require(plan != null, "Execution plan is required");
        java.util.Map<String, Object> runtime = metadata(sim, sessionToken);
        require((plan.get("schema_version") instanceof Integer || plan.get("schema_version") instanceof Long)
                && ((Number) plan.get("schema_version")).longValue() == 1L,
                "Unsupported execution plan schema_version");
        java.util.Map<String, Object> version = object(plan.get("target"), "plan.target");
        require(runtime.get("release").equals(version.get("release"))
                && runtime.get("build").equals(version.get("build")),
                "Catalog version mismatch: expected " + version + ", got " + runtime);
        return runtime;
    }

    /**
     * 按目录节点生成旧 schema 1 快照，保留名称排序、局部失败与完整性标记的既有契约。
     * 版本检查先于快照元数据和字段读取；节点只描述读取，不执行设置、求值或保存。
     */
    public static java.util.Map<String, Object> snapshot(star.common.Simulation sim,
            java.util.Map<String, Object> plan, String sessionToken) {
        checkVersion(sim, plan, sessionToken);
        string(plan.get("catalog_id"), "snapshot.catalog_id");
        java.util.Map<String, Object> nodes = object(plan.get("nodes"), "snapshot.nodes");
        java.util.List<java.util.Map<String, Object>> errors = new java.util.ArrayList<>();
        java.util.Map<String, Object> result = fields("schema_version", 1,
                "simulation_name", sim.getPresentationName(), "session_path", sim.getSessionPath(),
                "modified", sim.isModified());
        java.util.Set<String> active = new java.util.HashSet<>();
        // 每个根集合独立记录枚举错误；一个集合失败不会中止其他集合的读取。
        for (Object raw : list(plan.get("collections"), "snapshot.collections")) {
            java.util.Map<String, Object> field = object(raw, "snapshot collection");
            require(field.keySet().equals(java.util.Set.of("output", "read", "collection")),
                    "Invalid snapshot collection fields");
            String output = string(field.get("output"), "collection.output");
            result.put(output, snapshotCollection(sim, null, nodes, field, output,
                    sessionToken, errors, active, 0));
        }
        result.put("inspection_complete", errors.isEmpty());
        result.put("read_errors", errors);
        return result;
    }

    /** 集合管线失败返回空数组并记录路径；节点错误由各节点自身保留，互不覆盖。 */
    private static java.util.List<java.util.Map<String, Object>> snapshotCollection(
            star.common.Simulation sim, star.base.neo.ClientServerObject owner,
            java.util.Map<String, Object> nodes, java.util.Map<String, Object> field,
            String location, String token, java.util.List<java.util.Map<String, Object>> errors,
            java.util.Set<String> active, int depth) {
        java.util.List<java.util.Map<String, Object>> result = new java.util.ArrayList<>();
        java.util.List<star.base.neo.ClientServerObject> values = new java.util.ArrayList<>();
        String node;
        try {
            node = string(field.get("collection"), "collection.node");
            Object raw = pipeline(sim, owner, null, object(field.get("read"), "collection.read"));
            require(raw instanceof java.util.Collection<?>, "Snapshot collection requires a collection");
            for (Object value : (java.util.Collection<?>) raw) {
                require(value instanceof star.base.neo.ClientServerObject,
                        "Snapshot collection requires STAR objects");
                values.add((star.base.neo.ClientServerObject) value);
            }
            values.sort(java.util.Comparator.comparing(star.base.neo.ClientServerObject::getPresentationName)
                    .thenComparing(value -> value.getClass().getSimpleName()));
        } catch (Exception error) {
            snapshotError(errors, location, error);
            return result;
        }
        for (star.base.neo.ClientServerObject value : values) {
            result.add(snapshotNode(sim, value, nodes, node, location, token, errors, active, depth));
        }
        return result;
    }

    /**
     * 节点先保留身份，再按顺序读取公共字段及全部匹配的类型分支。
     * 活动路径按节点和对象 key 检测循环；重复引用在不同路径上仍可正常读取。
     */
    private static java.util.Map<String, Object> snapshotNode(star.common.Simulation sim,
            star.base.neo.ClientServerObject value, java.util.Map<String, Object> nodes, String nodeId,
            String location, String token, java.util.List<java.util.Map<String, Object>> errors,
            java.util.Set<String> active, int depth) {
        java.util.Map<String, Object> result = new java.util.LinkedHashMap<>();
        String path = location, activeKey = null;
        boolean entered = false;
        try {
            String name = value.getPresentationName();
            result.put("name", name);
            result.put("object_type", value.getClass().getSimpleName());
            path += "/" + name;
            require(depth < 64, "Snapshot nesting exceeds 64 nodes");
            activeKey = nodeId + "\u0000" + value.getObjectKeyAsString();
            require(active.add(activeKey), "Snapshot node cycle detected: " + nodeId);
            entered = true;
            java.util.Map<String, Object> node = object(nodes.get(nodeId), "snapshot node " + nodeId);
            snapshotFields(sim, value, nodes, list(node.get("fields"), "node.fields"), result,
                    path, token, errors, active, depth);
            boolean matched = false;
            for (Object raw : list(node.get("variants"), "node.variants")) {
                java.util.Map<String, Object> variant = object(raw, "node variant");
                Class<?> type = javaType(string(variant.get("java_class"), "variant.java_class"));
                if (type.isInstance(value)) {
                    matched = true;
                    snapshotFields(sim, value, nodes, list(variant.get("fields"), "variant.fields"),
                            result, path, token, errors, active, depth);
                }
            }
            require(node.get("require_variant") instanceof Boolean, "Node require_variant must be boolean");
            if (Boolean.TRUE.equals(node.get("require_variant")) && !matched) {
                result.put("unsupported", true);
                throw new IllegalArgumentException("Unsupported snapshot object type: " + value.getClass().getName());
            }
        } catch (Exception error) {
            result.put("read_error", errorText(error));
            snapshotError(errors, path, error);
        } finally {
            if (entered) active.remove(activeKey);
        }
        return result;
    }

    /**
     * 四种字段分别处理适配值、子集合、单对象记录和常量；未配置的隐式读取不会发生。
     * select 只沿适配结果的映射取值，quantity 展开沿用旧数量的五个字段及单位含义。
     */
    private static void snapshotFields(star.common.Simulation sim,
            star.base.neo.ClientServerObject owner, java.util.Map<String, Object> nodes,
            java.util.List<?> fields, java.util.Map<String, Object> result, String location, String token,
            java.util.List<java.util.Map<String, Object>> errors, java.util.Set<String> active, int depth)
            throws Exception {
        for (Object raw : fields) {
            java.util.Map<String, Object> field = object(raw, "snapshot field");
            Object output = field.get("output");
            require(field.containsKey("output") && (output == null || output instanceof String && !((String) output).isEmpty()),
                    "Snapshot output must be a non-empty string or null");
            if (field.containsKey("collection")) {
                require(field.keySet().equals(java.util.Set.of("output", "read", "collection")) && output != null,
                        "Invalid snapshot collection fields");
                result.put((String) output, snapshotCollection(sim, owner, nodes, field,
                        location + "/" + output, token, errors, active, depth + 1));
                continue;
            }
            Object value;
            if (field.containsKey("literal")) {
                require(field.keySet().equals(java.util.Set.of("output", "literal")) && output != null,
                        "Invalid snapshot literal fields");
                value = primitive(field.get("literal"));
            } else {
                value = pipeline(sim, owner, null, object(field.get("read"), "field.read"));
                if (field.containsKey("record")) {
                    require(field.keySet().equals(java.util.Set.of("output", "read", "record")) && output != null,
                            "Invalid snapshot record fields");
                    require(value == null || value instanceof star.base.neo.ClientServerObject,
                            "Snapshot record requires a STAR object");
                    value = value == null ? null : snapshotNode(sim, (star.base.neo.ClientServerObject) value,
                            nodes, string(field.get("record"), "record.node"), location + "/" + output,
                            token, errors, active, depth + 1);
                } else {
                    require(field.keySet().equals(java.util.Set.of("output", "read", "adapter", "select")),
                            "Invalid snapshot adapted fields");
                    String adapter = string(field.get("adapter"), "field.adapter");
                    value = encode(value, adapter, token);
                    for (Object key : list(field.get("select"), "field.select")) {
                        String name = string(key, "select key");
                        java.util.Map<String, Object> map = object(value, "selected value");
                        require(map.containsKey(name), "Snapshot selected value is missing: " + name);
                        value = map.get(name);
                    }
                    if (output == null) {
                        require(adapter.equals("quantity"), "Only quantity fields may expand into a node");
                        result.putAll(object(value, "expanded quantity"));
                        continue;
                    }
                }
            }
            result.put((String) output, value);
        }
    }

    /** 全局错误保留路径和展开后的根因，防止空集合或部分记录被误解为完整结果。 */
    private static void snapshotError(java.util.List<java.util.Map<String, Object>> errors,
            String location, Exception error) {
        errors.add(fields("location", location, "message", errorText(error)));
    }

    /**
     * 先核对版本和目标身份，再描述或读取选定属性；单项读取失败保留其他结果。
     * 返回值只含 JSON 可表示的数据。这里的完整性只针对本次选择，不代表整个算例。
     */
    public static java.util.Map<String, Object> inspect(
            star.common.Simulation sim, java.util.Map<String, Object> plan,
            java.util.Map<String, Object> request, String sessionToken) {
        // 1. 目录中的任何方法都必须在当前 server 版本匹配后才有机会执行。
        java.util.Map<String, Object> runtime = checkVersion(sim, plan, sessionToken);
        String action = string(request.get("action"), "request.action");
        require(action.equals("describe") || action.equals("read"), "Unsupported catalog action");
        String catalogId = string(plan.get("catalog_id"), "plan.catalog_id");
        java.util.Map<String, Object> target = object(request.get("target"), "request.target");
        java.util.Map<String, Object> types = object(plan.get("types"), "plan.types");
        Resolved resolved = locate(sim, types, target, sessionToken, 0);
        String typeId = string(target.get("type"), "target.type");
        java.util.Map<String, Object> propertiesByType = object(plan.get("properties"), "plan.properties");
        java.util.Map<String, Object> available = object(propertiesByType.get(typeId), "type properties");
        java.util.List<String> selected = selectedProperties(request, available);

        // 2. 描述只交出目录适配状态；它不为了判断“可写”而尝试调用 setter。
        java.util.Map<String, Object> result = fields(
                "target", fields("type", typeId, "name", resolved.object.getPresentationName(),
                    "java_class", resolved.object.getClass().getName(),
                    "reference", identity(resolved.object, sessionToken),
                    "locator", locator(target)),
                "catalog_id", catalogId, "runtime", runtime);
        java.util.Map<String, Object> values = new java.util.LinkedHashMap<>();
        boolean complete = true;
        for (String name : selected) {
            java.util.Map<String, Object> property = object(available.get(name), "property " + name);
            String adapter = string(property.get("adapter"), "property.adapter");
            if (action.equals("describe")) {
                require(property.get("writable") instanceof Boolean, "Invalid writable implementation flag");
                values.put(name, fields("adapter", adapter, "writable", property.get("writable"),
                                        "reason", string(property.get("reason"), "property.reason"),
                                        "conditions_checked", false));
                continue;
            }
            // 3. 读取错误属于对应属性；未知适配器和未支持查询也不能伪装成空值。
            try {
                Object raw = pipeline(sim, resolved.object, resolved.parent,
                                      object(property.get("read"), "property.read"));
                values.put(name, fields("status", "ok", "value", encode(raw, adapter, sessionToken)));
            } catch (Exception error) {
                complete = false;
                values.put(name, fields("status", "error", "error", errorText(error)));
            }
        }
        result.put("properties", values);
        result.put("inspection_complete", complete);
        return result;
    }

    /**
     * 保存已经完成预检查的单项修改；apply 只允许执行一次，失败后不得自动重试。
     * before/after 使用目录读取封套，旧完整快照与保存流程仍由调用方负责。
     */
    public static final class PreparedModification {
        public final java.util.Map<String, Object> before;
        private final star.common.Simulation sim;
        private final java.util.Map<String, Object> plan;
        private final java.util.Map<String, Object> readRequest;
        private final String token, property, adapter;
        private final Object value;
        private final Invocation invocation;
        private boolean applied;

        PreparedModification(star.common.Simulation sim, java.util.Map<String, Object> plan,
                java.util.Map<String, Object> readRequest, String token, String property,
                String adapter, Object value, Invocation invocation,
                java.util.Map<String, Object> before) {
            this.sim = sim; this.plan = plan; this.readRequest = readRequest; this.token = token;
            this.property = property; this.adapter = adapter; this.value = value;
            this.invocation = invocation; this.before = before;
        }

        /** 写入后核对目的属性和对象身份；此阶段的任何异常都表示结果可能已改变。 */
        public synchronized java.util.Map<String, Object> apply() throws Exception {
            if (applied) throw new IllegalStateException("Prepared modification has already been attempted");
            applied = true;
            invocation.invoke();
            java.util.Map<String, Object> after = inspect(sim, plan, readRequest, token);
            if (!Boolean.TRUE.equals(after.get("inspection_complete")))
                throw new IllegalStateException("Modification readback is incomplete");
            verifyWritten(adapter, value, propertyValue(after, property));
            if (!sameValue(before.get("target"), after.get("target")))
                throw new IllegalStateException("Modification target identity changed");
            for (String key : java.util.List.of("name", "function_name", "value_type", "dimensions", "unit")) {
                if (key.equals("unit") && (adapter.equals("scalar_expression") || adapter.equals("scalar_value"))) continue;
                java.util.Map<String, Object> original = object(before.get("properties"), "before.properties");
                if (original.containsKey(key) && !sameValue(propertyValue(before, key), propertyValue(after, key)))
                    throw new IllegalStateException("Modification identity property changed: " + key);
            }
            return after;
        }
    }

    /**
     * 在任何 setter 前核对完整读取、预期状态、单位和标签，再解析唯一最终调用。
     * 只有此方法的拒绝可解释为未写入；调用方不能把 apply 的异常转成 rejected。
     */
    public static PreparedModification prepareModification(star.common.Simulation sim,
            java.util.Map<String, Object> plan, java.util.Map<String, Object> request, String token) {
        require((request.get("schema_version") instanceof Integer || request.get("schema_version") instanceof Long)
                && ((Number) request.get("schema_version")).longValue() == 2L
                && "modify".equals(request.get("action")), "Invalid catalog modification request");
        require(request.keySet().equals(java.util.Set.of("schema_version", "action", "target", "property", "expected", "value")),
                "Invalid catalog modification fields");
        java.util.Map<String, Object> target = object(request.get("target"), "request.target");
        java.util.Map<String, Object> readRequest = fields("schema_version", 1L, "action", "read", "target", target);
        // inspect 先核对运行版本和引用，再读取本类型全部已配置属性。
        java.util.Map<String, Object> before = inspect(sim, plan, readRequest, token);
        require(Boolean.TRUE.equals(before.get("inspection_complete")), "Modification requires complete catalog reads");
        String typeId = string(target.get("type"), "target.type");
        String property = string(request.get("property"), "request.property");
        java.util.Map<String, Object> properties = object(object(plan.get("properties"), "plan.properties").get(typeId), "type properties");
        java.util.Map<String, Object> entry = object(properties.get(property), "modification property");
        require(Boolean.TRUE.equals(entry.get("writable")), "Property is not implemented for writing");
        java.util.Map<String, Object> writer = object(entry.get("write"), "property.write");
        String adapter = string(writer.get("adapter"), "write.adapter");
        Object expected = request.get("expected"), actual = propertyValue(before, property);
        if (adapter.equals("user_tags")) {
            // 标签关联的旧状态是名称与实际类型集合；读回携带的 token/key 仅为描述。
            // 目标自身的 reference 已由 inspect 严格核对，不在此处削弱其身份前提。
            require(sameValue(tagState(expected), tagState(actual)), "Modification expected tags do not match");
        } else require(sameValue(expected, actual), "Modification expected value does not match");
        Resolved resolved = locate(sim, object(plan.get("types"), "plan.types"), target, token, 0);
        require(sameValue(identity(resolved.object, token), object(before.get("target"), "before.target").get("reference")),
                "Modification target changed during preparation");
        Object value = request.get("value");
        java.util.Map<String, Object> values = new java.util.LinkedHashMap<>();
        try {
            if (adapter.equals("primitive")) {
                require(resolved.object instanceof star.common.UserFieldFunction,
                        "Primitive definition writes require a user field function");
                require(value instanceof String && !((String) value).trim().isEmpty(), "Definition must be non-empty");
                values.put("value", value);
            } else if (adapter.equals("scalar_expression") || adapter.equals("scalar_value")) {
                Object raw = pipeline(sim, resolved.object, resolved.parent, object(entry.get("read"), "property.read"));
                require(raw instanceof star.common.ScalarPhysicalQuantity, "Scalar writes require a scalar quantity");
                star.common.ScalarPhysicalQuantity quantity = (star.common.ScalarPhysicalQuantity) raw;
                java.util.Map<String, Object> input = object(value, "scalar value");
                String field = adapter.equals("scalar_expression") ? "definition" : "value";
                require(input.keySet().equals(java.util.Set.of(field, "unit")), "Invalid scalar value fields");
                require(input.get("unit") instanceof String, "Scalar unit must be a string");
                star.common.Units units = uniqueNamed(sim.getUnitsManager().getObjects(), (String) input.get("unit"), star.common.Units.class);
                require(quantity.getUnits().compatible(units), "Incompatible result unit");
                values.put("units", units);
                if (adapter.equals("scalar_expression")) {
                    String definition = string(input.get("definition"), "scalar definition");
                    require(!definition.trim().isEmpty(), "Scalar definition must be non-empty");
                    Double constant = star.common.PhysicalQuantityParser.parseAsConstant(definition);
                    require(constant == null || Double.isFinite(constant), "Scalar constant must be finite");
                    require(constant != null || input.get("unit").equals(quantity.getUnits().getSIUnits().getPresentationName()),
                            "Scalar expressions require the SI result unit");
                    values.put("definition", definition);
                } else {
                    require(input.get("value") instanceof Number && Double.isFinite(((Number) input.get("value")).doubleValue()),
                            "Scalar value must be finite");
                    values.put("number", input.get("value"));
                }
            } else if (adapter.equals("user_tags")) {
                Object raw = pipeline(sim, resolved.object, resolved.parent, object(entry.get("read"), "property.read"));
                require(raw instanceof java.util.Collection<?>, "Tag read must return a collection");
                for (Object tag : (java.util.Collection<?>) raw)
                    require(tag instanceof star.common.UserTag, "Target has non-user tags");
                java.util.List<String> names = tagNames(value);
                star.common.TagManager manager = sim.get(star.common.TagManager.class);
                java.util.List<star.common.Tag> tags = new java.util.ArrayList<>();
                for (String name : names) tags.add(uniqueNamed(manager.getObjects(), name, star.common.UserTag.class));
                values.put("value", tags);
            } else throw new IllegalArgumentException("Unsupported write adapter: " + adapter);
            Invocation setter = prepareWrite(sim, resolved, object(writer.get("pipeline"), "write.pipeline"), values);
            // 回读固定到本次准备得到的 key，不能让同名重建的对象冒充写入对象。
            java.util.Map<String, Object> fixedTarget = new java.util.LinkedHashMap<>(target);
            fixedTarget.put("reference", identity(resolved.object, token));
            java.util.Map<String, Object> fixedRead = fields("schema_version", 1L, "action", "read", "target", fixedTarget);
            return new PreparedModification(sim, plan, fixedRead, token, property, adapter, value, setter, before);
        } catch (Exception error) {
            throw new IllegalArgumentException("Modification preparation failed: " + errorText(error), error);
        }
    }

    /** 从完整目录结果中取一个成功的属性值，拒绝缺失、错误或伪造的空值。 */
    private static Object propertyValue(java.util.Map<String, Object> result, String property) {
        java.util.Map<String, Object> entry = object(object(result.get("properties"), "properties").get(property), property);
        require("ok".equals(entry.get("status")) && entry.containsKey("value"), "Property was not read successfully: " + property);
        return entry.get("value");
    }

    /** 在当前管理器中按名称唯一匹配；空单位名称是合法的无量纲单位对象名。 */
    private static <T extends star.base.neo.ClientServerObject> T uniqueNamed(
            java.util.Collection<?> values, String name, Class<T> type) {
        T found = null;
        for (Object value : values) {
            if (!(value instanceof star.base.neo.ClientServerObject)) continue;
            star.base.neo.ClientServerObject object = (star.base.neo.ClientServerObject) value;
            if (!name.equals(object.getPresentationName())) continue;
            require(found == null, "Named object is ambiguous: " + name);
            require(type.isInstance(object), "Named object has an unsupported type: " + name);
            found = type.cast(object);
        }
        require(found != null, "Named object is missing: " + name);
        return found;
    }

    /** 标签输入是完整名称集合；排序只用于核对，不赋予标签关联顺序语义。 */
    private static java.util.List<String> tagNames(Object value) {
        java.util.List<String> result = new java.util.ArrayList<>();
        for (Object item : list(value, "tag names")) {
            String name = string(item, "tag name");
            require(!result.contains(name), "Duplicate tag name");
            result.add(name);
        }
        java.util.Collections.sort(result);
        return result;
    }

    /** 规范化标签读取状态；显式忽略引用元数据，名称和实际类型仍逐项核对。 */
    private static java.util.List<Object> tagState(Object value) {
        java.util.List<Object> result = new java.util.ArrayList<>();
        java.util.Set<String> seen = new java.util.HashSet<>();
        for (Object raw : list(value, "expected tags")) {
            java.util.Map<String, Object> tag = object(raw, "expected tag");
            require(tag.keySet().equals(java.util.Set.of("name", "java_class"))
                    || tag.keySet().equals(java.util.Set.of("name", "java_class", "reference")), "Invalid expected tag fields");
            String name = string(tag.get("name"), "expected tag name");
            require(seen.add(name), "Duplicate expected tag name");
            String className = string(tag.get("java_class"), "expected tag type");
            try { require(star.common.UserTag.class.isAssignableFrom(javaType(className)), "Expected tag is not a UserTag"); }
            catch (ClassNotFoundException error) { throw new IllegalArgumentException("Unknown expected tag type", error); }
            if (tag.containsKey("reference")) {
                java.util.Map<String, Object> ref = object(tag.get("reference"), "tag reference");
                require(ref.keySet().equals(java.util.Set.of("session_token", "key")), "Invalid tag reference fields");
                string(ref.get("session_token"), "tag session token"); string(ref.get("key"), "tag key");
            }
            result.add(fields("name", name, "java_class", className));
        }
        result.sort(java.util.Comparator.comparing(Object::toString));
        return result;
    }

    /** 数值按数学值比较，布尔值始终保持独立类型；对象和列表要求完整结构一致。 */
    private static boolean sameValue(Object left, Object right) {
        if (left == null || right == null) return left == right;
        if (left instanceof Number && right instanceof Number)
            return new java.math.BigDecimal(left.toString()).compareTo(new java.math.BigDecimal(right.toString())) == 0;
        if (left instanceof java.util.Map<?, ?> && right instanceof java.util.Map<?, ?>) {
            java.util.Map<?, ?> a = (java.util.Map<?, ?>) left, b = (java.util.Map<?, ?>) right;
            if (!a.keySet().equals(b.keySet())) return false;
            for (Object key : a.keySet()) if (!sameValue(a.get(key), b.get(key))) return false;
            return true;
        }
        if (left instanceof java.util.List<?> && right instanceof java.util.List<?>) {
            java.util.List<?> a = (java.util.List<?>) left, b = (java.util.List<?>) right;
            if (a.size() != b.size()) return false;
            for (int i = 0; i < a.size(); i++) if (!sameValue(a.get(i), b.get(i))) return false;
            return true;
        }
        return left.getClass() == right.getClass() && left.equals(right);
    }

    /** 回读必须符合适配器的写入语义，不因 setter 返回便声称成功。 */
    private static void verifyWritten(String adapter, Object wanted, Object actual) {
        boolean matches;
        if (adapter.equals("scalar_expression") || adapter.equals("scalar_value")) {
            java.util.Map<String, Object> input = object(wanted, "scalar input"), output = object(actual, "scalar output");
            matches = sameValue(input.get("unit"), output.get("unit"));
            if (adapter.equals("scalar_expression")) {
                Object before = input.get("definition"), after = output.get("definition");
                boolean definitionMatches = sameValue(before, after);
                if (!definitionMatches) {
                    try {
                        double a = Double.parseDouble((String) before), b = Double.parseDouble((String) after);
                        definitionMatches = Double.isFinite(a) && Double.isFinite(b) && a == b;
                    } catch (NumberFormatException error) { /* 非数值表达式保持文本严格比较。 */ }
                }
                matches &= definitionMatches;
            } else {
                Object readback = output.get("raw_value");
                matches &= readback instanceof Number;
                if (readback instanceof Number) {
                    double a = ((Number) input.get("value")).doubleValue(), b = ((Number) readback).doubleValue();
                    matches &= Double.isFinite(b) && Math.abs(a - b) <= Math.max(1e-12, 1e-12 * Math.max(Math.abs(a), Math.abs(b)));
                }
            }
        } else if (adapter.equals("user_tags")) {
            java.util.List<String> names = new java.util.ArrayList<>();
            for (Object tag : tagState(actual)) names.add((String) object(tag, "tag").get("name"));
            java.util.Collections.sort(names);
            matches = names.equals(tagNames(wanted));
        } else matches = sameValue(wanted, actual);
        if (!matches) throw new IllegalStateException("Modification readback does not match requested value");
    }

    /** 保存本次定位得到的对象及父对象，使父路径只解析一次后用于属性管线。 */
    private static final class Resolved {
        final star.base.neo.ClientServerObject object;
        final star.base.neo.ClientServerObject parent;
        Resolved(star.base.neo.ClientServerObject object, star.base.neo.ClientServerObject parent) {
            this.object = object;
            this.parent = parent;
        }
    }

    /**
     * 从当前管理器枚举后按类型和名称唯一定位，随后核对会话内引用。
     * key 只用于当前会话重新定位的核对，不证明对象在保存重载或删除重建后仍是同一实例。
     */
    private static Resolved locate(star.common.Simulation sim, java.util.Map<String, Object> types,
            java.util.Map<String, Object> target, String sessionToken, int depth) {
        require(depth < 32, "Target parent nesting is too deep");
        String typeId = string(target.get("type"), "target.type");
        String name = string(target.get("name"), "target.name");
        java.util.Map<String, Object> type = object(types.get(typeId), "target type " + typeId);
        star.base.neo.ClientServerObject parent = null;
        Object parentType = type.get("parent_type");
        if (parentType != null) {
            java.util.Map<String, Object> parentTarget = object(target.get("parent"), "target.parent");
            require(parentType.equals(parentTarget.get("type")), "Target parent type mismatch");
            parent = locate(sim, types, parentTarget, sessionToken, depth + 1).object;
        } else {
            require(!target.containsKey("parent"), "Unexpected parent for target type " + typeId);
        }
        try {
            Class<?> expectedClass = javaType(string(type.get("java_class"), "type.java_class"));
            require(star.base.neo.ClientServerObject.class.isAssignableFrom(expectedClass),
                    "Target type is not a STAR object");
            Object value = pipeline(sim, null, parent, object(type.get("locate"), "type.locate"));
            require(value instanceof java.util.Collection<?>, "Locator must return a collection");
            star.base.neo.ClientServerObject found = null;
            for (Object item : (java.util.Collection<?>) value) {
                if (!expectedClass.isInstance(item)) continue;
                star.base.neo.ClientServerObject candidate = (star.base.neo.ClientServerObject) item;
                if (!name.equals(candidate.getPresentationName())) continue;
                require(found == null, "Target is ambiguous: " + typeId + "/" + name);
                found = candidate;
            }
            require(found != null, "Target is missing: " + typeId + "/" + name);
            if (target.containsKey("reference")) {
                java.util.Map<String, Object> reference = object(target.get("reference"), "target.reference");
                require(sessionToken.equals(reference.get("session_token")), "Object reference session mismatch");
                require(found.getObjectKeyAsString().equals(reference.get("key")), "Object reference key mismatch");
            }
            return new Resolved(found, parent);
        } catch (Exception error) {
            throw new IllegalArgumentException("Catalog target resolution failed: " + errorText(error), error);
        }
    }

    /** 去掉各层的会话引用，仅保留文件重载后可重新解析的显式名称、类型和父路径。 */
    private static java.util.Map<String, Object> locator(java.util.Map<String, Object> target) {
        java.util.Map<String, Object> result = fields("type", target.get("type"), "name", target.get("name"));
        if (target.containsKey("parent")) {
            result.put("parent", locator(object(target.get("parent"), "target.parent")));
        }
        return result;
    }

    /** 保存已解析的方法、接收对象与参数；构造它不会调用 setter。 */
    private static final class Invocation {
        final java.lang.reflect.Method method;
        final Object receiver;
        final Object[] arguments;
        Invocation(java.lang.reflect.Method method, Object receiver, Object[] arguments) {
            this.method = method; this.receiver = receiver; this.arguments = arguments;
        }
        Object invoke() throws Exception {
            try { return method.invoke(receiver, arguments); }
            catch (java.lang.reflect.InvocationTargetException error) {
                Throwable cause = error.getCause();
                if (cause instanceof Exception) throw (Exception) cause;
                if (cause instanceof Error) throw (Error) cause;
                throw error;
            }
        }
    }

    /** 按明确参数类查找 public 方法；检查参数和访问权限时还不执行调用。 */
    private static Invocation invocation(Object receiver, java.util.Map<String, Object> call,
                                         java.util.Map<String, Object> context) throws Exception {
        Class<?> owner = javaType(string(call.get("owner"), "step.owner"));
        require(receiver != null && owner.isInstance(receiver), "Pipeline receiver type mismatch");
        java.util.List<?> names = list(call.get("parameter_types"), "step.parameter_types");
        java.util.List<?> specs = list(call.get("arguments"), "step.arguments");
        require(names.size() == specs.size(), "Pipeline argument count mismatch");
        Class<?>[] parameterTypes = new Class<?>[names.size()];
        Object[] arguments = new Object[names.size()];
        for (int index = 0; index < names.size(); index++) {
            parameterTypes[index] = javaType(string(names.get(index), "parameter type"));
            java.util.Map<String, Object> spec = object(specs.get(index), "argument binding");
            require(spec.size() == 1, "Argument binding must contain exactly one source");
            Object value;
            if (spec.containsKey("class")) value = javaType(string(spec.get("class"), "class argument"));
            else if (spec.containsKey("literal")) value = spec.get("literal");
            else if (spec.containsKey("context")) {
                String key = string(spec.get("context"), "context argument");
                require(context.containsKey(key), "Unknown argument context: " + key);
                value = context.get(key);
            } else throw new IllegalArgumentException("Unknown argument binding");
            arguments[index] = convert(value, parameterTypes[index]);
        }
        java.lang.reflect.Method method = owner.getMethod(string(call.get("name"), "step.name"), parameterTypes);
        require(!java.lang.reflect.Modifier.isStatic(method.getModifiers()), "Static pipeline calls are unsupported");
        // 不放宽 Java 访问权限；不可访问的方法需要维护者选择正确的公开声明。
        require(method.canAccess(receiver), "Pipeline method is not publicly accessible");
        return new Invocation(method, receiver, arguments);
    }

    /** 由已声明的管线根取得接收对象；参数上下文与接收对象分别保存。 */
    private static Object root(star.common.Simulation sim, Object object, Object parent,
                               java.util.Map<String, Object> pipeline) {
        switch (string(pipeline.get("root"), "pipeline.root")) {
            case "simulation": return sim;
            case "object": return object;
            case "parent": return parent;
            default: throw new IllegalArgumentException("Unsupported pipeline root");
        }
    }

    /** 读取管线只执行明确的 read 调用，返回值供下一步使用。 */
    private static Object pipeline(star.common.Simulation sim, Object object, Object parent,
                                  java.util.Map<String, Object> pipeline) throws Exception {
        Object receiver = root(sim, object, parent, pipeline);
        java.util.Map<String, Object> context = fields("object", object, "parent", parent);
        for (Object raw : list(pipeline.get("steps"), "pipeline.steps")) {
            java.util.Map<String, Object> call = object(raw, "pipeline step");
            // 兼容之前已裁剪、未包含 effect 字段的 v1 只读计划。
            require(!call.containsKey("effect") || "read".equals(call.get("effect")),
                    "Read pipeline cannot invoke a write method");
            receiver = invocation(receiver, call, context).invoke();
        }
        return receiver;
    }

    /** 执行写入前缀的读取，解析最终 setter；最终调用留到 PreparedModification.apply。 */
    private static Invocation prepareWrite(star.common.Simulation sim, Resolved resolved,
            java.util.Map<String, Object> pipeline, java.util.Map<String, Object> values) throws Exception {
        Object receiver = root(sim, resolved.object, resolved.parent, pipeline);
        java.util.Map<String, Object> context = fields("object", resolved.object, "parent", resolved.parent);
        context.putAll(values);
        java.util.List<?> steps = list(pipeline.get("steps"), "write steps");
        require(!steps.isEmpty(), "Write pipeline cannot be empty");
        for (int index = 0; index < steps.size(); index++) {
            java.util.Map<String, Object> call = object(steps.get(index), "write step");
            boolean last = index == steps.size() - 1;
            require((last ? "write" : "read").equals(call.get("effect")),
                    "Only the final write pipeline call may mutate");
            Invocation ready = invocation(receiver, call, context);
            if (last) {
                require(ready.method.getReturnType() == void.class, "Write setter must return void");
                return ready;
            }
            receiver = ready.invoke();
        }
        throw new IllegalArgumentException("Missing write setter");
    }

    /** 将计划中的类名解析为精确类型；数组递归解析，嵌套类须使用 JVM 二进制名称。 */
    private static Class<?> javaType(String name) throws ClassNotFoundException {
        switch (name) {
            case "boolean": return boolean.class;
            case "byte": return byte.class;
            case "short": return short.class;
            case "int": return int.class;
            case "long": return long.class;
            case "float": return float.class;
            case "double": return double.class;
            case "char": return char.class;
            case "void": return void.class;
            default:
                if (name.endsWith("[]")) {
                    return java.lang.reflect.Array.newInstance(javaType(name.substring(0, name.length() - 2)), 0).getClass();
                }
                return Class.forName(name, false, CatalogRuntime.class.getClassLoader());
        }
    }

    /** 精确检查参数类型和整数范围，避免反射调用时静默截断或选择另一重载。 */
    private static Object convert(Object value, Class<?> type) {
        if (!type.isPrimitive()) {
            require(value == null || type.isInstance(value), "Reference argument type mismatch: " + type.getName());
            return value;
        }
        if (type == boolean.class) {
            require(value instanceof Boolean, "Boolean argument required");
            return value;
        }
        if (type == char.class) {
            require(value instanceof String && ((String) value).length() == 1, "Single-character argument required");
            return ((String) value).charAt(0);
        }
        require(value instanceof Number, "Numeric argument required: " + type.getName());
        Number number = (Number) value;
        require(Double.isFinite(number.doubleValue()), "Numeric argument must be finite");
        java.math.BigDecimal decimal = new java.math.BigDecimal(number.toString());
        if (type == double.class) {
            double result = number.doubleValue();
            require(decimal.compareTo(java.math.BigDecimal.valueOf(result)) == 0,
                    "Double argument would lose precision");
            return result;
        }
        if (type == float.class) {
            float result = number.floatValue();
            require(Float.isFinite(result), "Float argument is out of range");
            require(decimal.compareTo(new java.math.BigDecimal(Float.toString(result))) == 0,
                    "Float argument would lose precision");
            return result;
        }
        try {
            if (type == long.class) return decimal.longValueExact();
            if (type == int.class) return decimal.intValueExact();
            if (type == short.class) return decimal.shortValueExact();
            if (type == byte.class) return decimal.byteValueExact();
        } catch (ArithmeticException error) {
            throw new IllegalArgumentException("Integral argument is fractional or out of range", error);
        }
        throw new IllegalArgumentException("Unsupported primitive argument: " + type.getName());
    }

    /** 按值种类序列化，不依据对象类名猜测未实现的数据格式。 */
    private static Object encode(Object value, String adapter, String sessionToken) {
        require(java.util.List.of("primitive", "reference", "collection", "quantity", "vector", "enum", "query",
                "name", "type_name", "names", "enum_name")
                .contains(adapter), "Unsupported value adapter: " + adapter);
        // 类型、枚举和名称集合必须有实际值；空集合与缺失集合不能混为一谈。
        // 单对象 name 仍允许 null，以表示报告等对象尚未设置可选单位。
        if (value == null) {
            require(!java.util.List.of("type_name", "names", "enum_name").contains(adapter),
                    "Metadata adapter requires a non-null value: " + adapter);
            return null;
        }
        switch (adapter) {
            case "primitive": return primitive(value);
            // 这些身份适配器也供普通按需读取使用，不附带会话引用或执行对象求值。
            case "name":
                require(value instanceof star.base.neo.ClientServerObject, "Name adapter requires a STAR object");
                return ((star.base.neo.ClientServerObject) value).getPresentationName();
            case "type_name": return value.getClass().getSimpleName();
            case "names":
                require(value instanceof java.util.Collection<?>, "Names adapter requires a collection");
                java.util.List<String> names = new java.util.ArrayList<>();
                for (Object item : (java.util.Collection<?>) value) {
                    require(item instanceof star.base.neo.ClientServerObject, "Names adapter requires STAR objects");
                    names.add(((star.base.neo.ClientServerObject) item).getPresentationName());
                }
                java.util.Collections.sort(names);
                return names;
            case "enum_name":
                require(value instanceof Enum<?>, "Enum name adapter requires an enum");
                return ((Enum<?>) value).name();
            case "reference":
                require(value instanceof star.base.neo.ClientServerObject, "Reference adapter requires a STAR object");
                return reference((star.base.neo.ClientServerObject) value, sessionToken);
            case "collection":
                require(value instanceof java.util.Collection<?>, "Collection adapter requires a collection");
                return collection((java.util.Collection<?>) value, sessionToken);
            case "quantity":
                require(value instanceof star.common.ScalarPhysicalQuantity, "Quantity adapter requires a scalar quantity");
                star.common.ScalarPhysicalQuantity scalar = (star.common.ScalarPhysicalQuantity) value;
                return fields("definition", scalar.getDefinition(),
                    "unit", scalar.getUnits().getPresentationName(),
                    "si_unit", scalar.getUnits().getSIUnits().getPresentationName(),
                    "raw_value", primitive(scalar.getRawValue()), "si_value", primitive(scalar.getSIValue()));
            case "vector":
                require(value instanceof star.common.VectorPhysicalQuantity, "Vector adapter requires a vector quantity");
                star.common.VectorPhysicalQuantity vector = (star.common.VectorPhysicalQuantity) value;
                // 原始分量沿 STAR 当前数量对象的坐标约定返回，不进行坐标系变换。
                java.util.List<Object> components = new java.util.ArrayList<>();
                for (double component : vector.getRawVector().toDoubleArray()) components.add(primitive(component));
                return fields("definition", vector.getDefinition(), "unit", vector.getUnits().getPresentationName(),
                              "components", components);
            case "enum":
                require(value instanceof star.common.EnumeratedOption<?>, "Enum adapter requires an EnumeratedOption");
                star.common.EnumeratedOption<?> option = (star.common.EnumeratedOption<?>) value;
                java.util.List<String> allowed = new java.util.ArrayList<>();
                for (Enum<?> element : option.getElements()) allowed.add(element.name());
                // getElements 返回当前允许集合；保留 STAR 提供的编辑器显示顺序。
                Enum<?> selected = option.getSelectedElement();
                return fields("selected", selected == null ? null : selected.name(), "allowed", allowed);
            case "query": return query(value, sessionToken);
            default: throw new IllegalArgumentException("Unsupported value adapter: " + adapter);
        }
    }

    /** 查询保留规则本身；未知谓词明确失败，不能把动态规则变成一次性的对象列表。 */
    private static Object query(Object value, String sessionToken) {
        require(value instanceof star.base.query.ManagerWithQuery<?>, "Query adapter requires a ManagerWithQuery");
        star.base.query.ManagerWithQuery<?> manager = (star.base.query.ManagerWithQuery<?>) value;
        star.base.query.Query query = manager.getQuery();
        if (query == null) {
            return fields("mode", "static", "objects", collection(manager.getObjects(), sessionToken));
        }
        Object predicate = query.getPredicate();
        java.util.Map<String, Object> rule;
        // 只编码公开且已核对 getter 的谓词；组合谓词等需要后续单独适配。
        if (predicate != null && predicate.getClass() == star.base.query.NamePredicate.class) {
            star.base.query.NamePredicate name = (star.base.query.NamePredicate) predicate;
            rule = fields("type", "name", "operator", name.getOperator().name(), "value", name.getName());
        } else if (predicate != null && predicate.getClass() == star.base.query.TypePredicate.class) {
            star.base.query.TypePredicate type = (star.base.query.TypePredicate) predicate;
            rule = fields("type", "java_type", "operator", type.getOperator().name(), "value", type.getType().getName());
        } else {
            throw new IllegalArgumentException("Unsupported query predicate: "
                    + (predicate == null ? "null" : predicate.getClass().getName()));
        }
        java.util.List<String> modifiers = new java.util.ArrayList<>();
        for (star.base.query.Query.Modifier modifier : query.getModifiers()) modifiers.add(modifier.name());
        java.util.Collections.sort(modifiers);
        return fields("mode", "query", "predicate", rule, "modifiers", modifiers);
    }

    /** 保留 JSON 基础类型；非有限数值使用显式字符串，避免生成非法 JSON。 */
    private static Object primitive(Object value) {
        if (value == null || value instanceof String || value instanceof Boolean) return value;
        if (value instanceof Character) return value.toString();
        if (value instanceof Number) {
            if ((value instanceof Double && !Double.isFinite((Double) value))
                    || (value instanceof Float && !Float.isFinite((Float) value))) return value.toString();
            return value;
        }
        throw new IllegalArgumentException("Unsupported primitive value: " + value.getClass().getName());
    }

    /** 将对象集合转换为稳定的引用列表；此顺序只用于输出，不能解释为操作执行顺序。 */
    private static java.util.List<Object> collection(java.util.Collection<?> source, String sessionToken) {
        java.util.List<Object> result = new java.util.ArrayList<>();
        for (Object value : source) {
            result.add(value instanceof star.base.neo.ClientServerObject
                    ? reference((star.base.neo.ClientServerObject) value, sessionToken) : primitive(value));
        }
        result.sort(java.util.Comparator.comparing(value -> value == null ? "null" : value.getClass().getName() + ":" + value));
        return result;
    }

    /** 对象引用始终含会话世代；名称及 Java 类型用于解释和重新定位，不充当永久 ID。 */
    private static java.util.Map<String, Object> reference(star.base.neo.ClientServerObject value, String sessionToken) {
        return fields("name", value.getPresentationName(), "java_class", value.getClass().getName(),
                      "reference", identity(value, sessionToken));
    }

    /** 会话内对象 key 只能与 Runner 的会话世代一起使用。 */
    private static java.util.Map<String, Object> identity(star.base.neo.ClientServerObject value, String sessionToken) {
        return fields("session_token", sessionToken, "key", value.getObjectKeyAsString());
    }

    /** 默认读取该类型的全部已适配属性；显式列表禁止重复和未知名称。 */
    private static java.util.List<String> selectedProperties(java.util.Map<String, Object> request,
                                                            java.util.Map<String, Object> available) {
        java.util.List<String> result = new java.util.ArrayList<>();
        if (!request.containsKey("properties")) {
            result.addAll(available.keySet());
        } else {
            for (Object value : list(request.get("properties"), "request.properties")) {
                String name = string(value, "property ID");
                require(available.containsKey(name), "Unknown property: " + name);
                require(!result.contains(name), "Duplicate property: " + name);
                result.add(name);
            }
        }
        java.util.Collections.sort(result);
        return result;
    }

    /** 将反射包装异常展开为稳定错误说明，不把底层失败变成空值或成功状态。 */
    private static String errorText(Throwable error) {
        while (error instanceof java.lang.reflect.InvocationTargetException && error.getCause() != null) {
            error = error.getCause();
        }
        return error.getClass().getSimpleName() + ": " + String.valueOf(error.getMessage());
    }

    /** 构造保持字段顺序的 JSON 对象，供宏自身的 JSON 编码器输出。 */
    private static java.util.Map<String, Object> fields(Object... values) {
        java.util.Map<String, Object> result = new java.util.LinkedHashMap<>();
        for (int index = 0; index < values.length; index += 2) result.put((String) values[index], values[index + 1]);
        return result;
    }

    /** 对计划和请求的容器边界做防御检查；具体字段白名单仍由 Python 编译器负责。 */
    @SuppressWarnings("unchecked")
    private static java.util.Map<String, Object> object(Object value, String location) {
        require(value instanceof java.util.Map<?, ?>, "Object required at " + location);
        return (java.util.Map<String, Object>) value;
    }

    /** 要求列表，防止计划字段类型错误落入隐式转换或单项循环。 */
    private static java.util.List<?> list(Object value, String location) {
        require(value instanceof java.util.List<?>, "Array required at " + location);
        return (java.util.List<?>) value;
    }

    /** 协议标识符和对象名称必须是非空字符串，不接受 null 的隐式文本形式。 */
    private static String string(Object value, String location) {
        require(value instanceof String && !((String) value).isEmpty(), "Non-empty string required at " + location);
        return (String) value;
    }

    /** 在任何读取前拒绝无效前提；读取阶段的异常由属性结果单独记录。 */
    private static void require(boolean condition, String message) {
        if (!condition) throw new IllegalArgumentException(message);
    }
}

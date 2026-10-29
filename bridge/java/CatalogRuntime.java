/**
 * 在已核对版本的 STAR 会话中执行目录裁剪后的定位、读取和单项修改管线。
 * 本类作为同文件辅助类追加到 BridgeFileMacro 源码；计划由 Python 校验，
 * 请求只能选择目录属性或操作，不能提供 Java 类、方法或任意调用片段。
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

        // 2. 描述读取目录已声明的目标条件；没有新值时不判断单位、关联或最终可写性。
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
                java.util.Map<String, Object> description = fields("adapter", adapter, "writable", property.get("writable"),
                                        "reason", string(property.get("reason"), "property.reason"),
                                        "guards", property.getOrDefault("guards", java.util.List.of()),
                                        "preserved_properties", property.getOrDefault("preserved_properties", java.util.List.of()),
                                        "value_types", property.getOrDefault("value_types", java.util.List.of()),
                                        "value_guards", property.getOrDefault("value_guards", java.util.List.of()),
                                        "value_bounds", property.getOrDefault("value_bounds", false));
                description.putAll(describeConditions(sim, resolved, property, sessionToken));
                if (description.get("target_condition_status").equals("error")) complete = false;
                values.put(name, description);
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
        if (action.equals("describe")) {
            // 操作描述只执行 available 与 guards 的读取；参数选择和源状态完整性在修改准备时检查。
            java.util.Map<String, Object> operations = object(plan.getOrDefault("operations", fields()), "plan.operations");
            java.util.Map<String, Object> descriptions = new java.util.LinkedHashMap<>();
            for (java.util.Map.Entry<String, Object> entry : object(operations.getOrDefault(typeId, fields()),
                    "type operations").entrySet()) {
                java.util.Map<String, Object> description = describeOperation(sim, resolved,
                        object(entry.getValue(), "operation"), sessionToken);
                if (description.get("target_condition_status").equals("error")
                        || !Boolean.TRUE.equals(description.get("method_choices_checked"))) complete = false;
                descriptions.put(entry.getKey(), description);
            }
            result.put("operations", descriptions);
        }
        result.put("inspection_complete", complete);
        return result;
    }

    /** 描述操作范围及选项；Profile 枚举全部方法，材料物性只查找目录已映射的类。 */
    private static java.util.Map<String, Object> describeOperation(star.common.Simulation sim,
            Resolved resolved, java.util.Map<String, Object> operation, String token) {
        java.util.Map<String, Object> result = fields("adapter", operation.get("adapter"),
                "implemented", true, "reason", operation.get("reason"),
                "read_properties", operation.get("read_properties"), "state_property", operation.get("state_property"),
                "preserved_properties", operation.get("preserved_properties"), "impacts", operation.get("impacts"));
        result.putAll(describeConditions(sim, resolved, fields("writable", true,
                "condition_reads", operation.get("guards")), token));
        java.util.List<Object> choices = new java.util.ArrayList<>();
        java.util.List<Object> unmapped = new java.util.ArrayList<>();
        boolean material = "material_method".equals(operation.get("adapter"));
        result.put("method_choices_scope", material ? "mapped_classes" : "all_available");
        result.put("method_resolution", material ? "class_lookup" : "enumeration");
        try {
            java.util.Map<String, Object> mappings = object(operation.get("methods"), "operation.methods");
            if (material) {
                // 材料 API 仅按类查找既有方法；查到一个对象不等于枚举了所有选项或证明无重复。
                for (java.util.Map.Entry<String, Object> mapping : mappings.entrySet()) {
                    star.material.MaterialPropertyMethod method = lookupMaterialMethod(sim, resolved, operation,
                            string(mapping.getValue(), "mapped material method"));
                    choices.add(fields("id", mapping.getKey(), "java_class", mapping.getValue(),
                            "available", method != null && method.getClass().getName().equals(mapping.getValue()),
                            "resolved_method", method == null ? null : reference(method, token)));
                }
            } else {
                java.util.List<star.common.ProfileMethod> available = availableMethods(sim, resolved, operation);
                // 可发现的方法不自动成为可执行能力；Profile 可完整枚举，因此返回未映射项。
                for (star.common.ProfileMethod method : available)
                    if (!mappings.containsValue(method.getClass().getName())) unmapped.add(reference(method, token));
                for (java.util.Map.Entry<String, Object> mapping : mappings.entrySet()) {
                    java.util.List<Object> matches = new java.util.ArrayList<>();
                    for (star.common.ProfileMethod method : available)
                        if (method.getClass().getName().equals(mapping.getValue())) matches.add(reference(method, token));
                    choices.add(fields("id", mapping.getKey(), "java_class", mapping.getValue(),
                            "available", matches.size() == 1, "matches", matches));
                }
            }
            result.put("method_choices_checked", true);
        } catch (Exception error) {
            result.put("method_choices_checked", false);
            result.put("method_choices_error", errorText(error));
        }
        result.put("method_choices", choices);
        if (!material) result.put("unmapped_methods", unmapped);
        return result;
    }

    /** 属性赋值和结构操作共用外层快照、保存及失败处理，但各自声明需要的前后读取。 */
    public interface PreparedChange {
        java.util.Map<String, Object> before();
        java.util.Map<String, Object> apply() throws Exception;
    }

    /** schema 3 仅表示结构操作请求；旧属性 schema 2 的校验和行为保持独立。 */
    public static PreparedChange prepareChange(star.common.Simulation sim,
            java.util.Map<String, Object> plan, java.util.Map<String, Object> request, String token) {
        Object schema = request.get("schema_version");
        if ((schema instanceof Integer || schema instanceof Long) && ((Number) schema).longValue() == 3L)
            return prepareOperation(sim, plan, request, token);
        return prepareModification(sim, plan, request, token);
    }

    /** 从目录只读管线枚举 Profile 方法；不调用可能隐式切换方法的 getMethod(Class)。 */
    private static java.util.List<star.common.ProfileMethod> availableMethods(star.common.Simulation sim,
            Resolved resolved, java.util.Map<String, Object> operation) throws Exception {
        require("profile_method".equals(operation.get("adapter")), "Unsupported operation adapter");
        require(resolved.object instanceof star.common.TensorProfile, "Method operation requires a TensorProfile");
        Object raw = pipeline(sim, resolved.object, resolved.parent, object(operation.get("available"), "operation.available"));
        require(raw instanceof java.util.Collection<?>, "Available methods must be a collection");
        java.util.List<star.common.ProfileMethod> methods = new java.util.ArrayList<>();
        for (Object item : (java.util.Collection<?>) raw) {
            require(item instanceof star.common.ProfileMethod, "Invalid available profile method");
            methods.add((star.common.ProfileMethod) item);
        }
        return methods;
    }

    /**
     * 按目录类查找材料物性已有方法，不调用 setter，也不通过只返回活动项的 getObjects 枚举。
     * 2602 的查找 API 以本地 NeoException 报告缺失；只识别已核对的错误及类元数据，
     * 其他异常继续传播，避免把连接失败或服务器错误解释成“不支持此方法”。
     */
    private static star.material.MaterialPropertyMethod lookupMaterialMethod(star.common.Simulation sim,
            Resolved resolved, java.util.Map<String, Object> operation, String className) throws Exception {
        require("material_method".equals(operation.get("adapter")), "Unsupported material operation adapter");
        require(resolved.object instanceof star.material.MaterialProperty,
                "Material method operation requires a MaterialProperty");
        Object raw = pipeline(sim, resolved.object, resolved.parent, object(operation.get("available"), "operation.available"));
        require(raw instanceof star.material.MaterialProperty
                && ((star.material.MaterialProperty) raw).getObjectKeyAsString().equals(resolved.object.getObjectKeyAsString()),
                "Material method lookup must use the operation target");
        Class<? extends star.material.MaterialPropertyMethod> type = javaType(className)
                .asSubclass(star.material.MaterialPropertyMethod.class);
        try {
            return ((star.material.MaterialProperty) raw).getMaterialPropertyMethod(type);
        } catch (star.base.neo.NeoException error) {
            star.base.neo.NeoProperty details = error.getNeoProperty();
            if (details != null && !details.containsKey("Neo.Error") && details.containsKey("error")
                    && details.containsKey("Class")
                    && "MaterialPropertyMethod not found in MaterialProperty".equals(details.getString("error"))
                    && type.toString().equals(details.getString("Class"))) return null;
            throw error;
        }
    }

    /** 仅选择已审阅 ID 对应的既有方法；Profile 检查唯一匹配，材料检查按类查找结果的精确类型。 */
    private static star.base.neo.ClientServerObject selectedMethod(star.common.Simulation sim, Resolved resolved,
            java.util.Map<String, Object> operation, String methodId) throws Exception {
        java.util.Map<String, Object> mappings = object(operation.get("methods"), "operation.methods");
        require(mappings.containsKey(methodId), "Unknown mapped method: " + methodId);
        if ("material_method".equals(operation.get("adapter"))) {
            String className = string(mappings.get(methodId), "mapped material method");
            star.material.MaterialPropertyMethod method = lookupMaterialMethod(sim, resolved, operation, className);
            require(method != null, "Material method is unavailable: " + methodId);
            require(method.getClass().getName().equals(className), "Material method does not match mapped class: " + methodId);
            return method;
        }
        star.common.ProfileMethod selected = null;
        for (star.common.ProfileMethod method : availableMethods(sim, resolved, operation)) {
            if (!method.getClass().getName().equals(mappings.get(methodId))) continue;
            require(selected == null, "Profile method is ambiguous: " + methodId);
            selected = method;
        }
        require(selected != null, "Profile method is unavailable: " + methodId);
        return selected;
    }

    /** 跨加载只规范化方向关联引用；直接拥有的轴向量及其全部其他设置仍参与比较。 */
    private static java.util.Map<String, Object> tensorMethodContent(Object value) {
        java.util.Map<String, Object> result = new java.util.LinkedHashMap<>(object(value, "tensor method state"));
        for (String key : java.util.List.of("coordinate_system", "local_orientation"))
            if (result.containsKey(key)) result.put(key, referenceState(result.get(key)));
        if (result.containsKey("direction_axes")) {
            java.util.List<Object> axes = new java.util.ArrayList<>();
            for (Object raw : list(result.get("direction_axes"), "direction axes")) {
                java.util.Map<String, Object> axis = new java.util.LinkedHashMap<>(object(raw, "direction axis"));
                axis.put("coordinate_system", referenceState(axis.get("coordinate_system")));
                axes.add(axis);
            }
            result.put("direction_axes", axes);
        }
        return result;
    }

    /** 仅张量状态规范化方向引用；材料状态不含协议引用，全部元数据和数量原样参与比较。 */
    private static Object operationMethodContent(java.util.Map<String, Object> operation, Object value) {
        if ("profile_method".equals(operation.get("adapter"))) return tensorMethodContent(value);
        require("material_method".equals(operation.get("adapter")), "Unsupported structural operation adapter");
        return object(value, "material method state");
    }

    /** 从指定的既有方法读取完整设置，可用于未活动目标方法的准备检查，不重新选择活动方法。 */
    private static Object operationMethodState(Resolved resolved, java.util.Map<String, Object> operation,
            star.base.neo.ClientServerObject method, String token) {
        if ("profile_method".equals(operation.get("adapter"))) {
            require(resolved.object instanceof star.common.TensorProfile && method instanceof star.common.ProfileMethod,
                    "Profile method state requires a TensorProfile and ProfileMethod");
            return tensorMethodState((star.common.TensorProfile) resolved.object, (star.common.ProfileMethod) method, token);
        }
        require("material_method".equals(operation.get("adapter"))
                && resolved.object instanceof star.material.MaterialProperty && method instanceof star.material.MaterialPropertyMethod,
                "Material method state requires a MaterialProperty and MaterialPropertyMethod");
        return materialMethodState((star.material.MaterialProperty) resolved.object,
                (star.material.MaterialPropertyMethod) method, token);
    }

    /** 按操作的目标类型读取无参当前方法，供 setter 后核对所选对象 key。 */
    private static star.base.neo.ClientServerObject currentOperationMethod(Resolved resolved,
            java.util.Map<String, Object> operation) {
        star.base.neo.ClientServerObject method;
        if ("profile_method".equals(operation.get("adapter"))) {
            require(resolved.object instanceof star.common.TensorProfile, "Method operation requires a TensorProfile");
            method = ((star.common.TensorProfile) resolved.object).getMethod();
        } else {
            require("material_method".equals(operation.get("adapter"))
                    && resolved.object instanceof star.material.MaterialProperty,
                    "Material method operation requires a MaterialProperty");
            method = ((star.material.MaterialProperty) resolved.object).getMethod();
        }
        require(method != null, "Current operation method is missing");
        return method;
    }

    /**
     * 先读取完整活动方法状态并核对 expected，再准备一次已绑定的方法选择 setter。
     * 方法切换可能重建分量；不会把逐值回写或切回旧方法宣称为可用的回滚。
     */
    private static PreparedOperation prepareOperation(star.common.Simulation sim,
            java.util.Map<String, Object> plan, java.util.Map<String, Object> request, String token) {
        require("modify".equals(request.get("action")) && request.keySet().equals(java.util.Set.of(
                "schema_version", "action", "target", "operation", "expected", "arguments")),
                "Invalid structural operation request");
        try {
            // 1. 版本及各层对象身份先固定；后续读取和最终调用前均沿同一身份重定位。
            checkVersion(sim, plan, token);
            java.util.Map<String, Object> types = object(plan.get("types"), "plan.types");
            java.util.Map<String, Object> target = pinTarget(sim, types,
                    object(request.get("target"), "request.target"), token, 0);
            Resolved resolved = locate(sim, types, target, token, 0);
            String typeId = string(target.get("type"), "target.type");
            String operationId = string(request.get("operation"), "request.operation");
            java.util.Map<String, Object> operation = object(object(object(plan.get("operations"),
                    "plan.operations").get(typeId), "type operations").get(operationId), "operation");
            require(java.util.List.of("profile_method", "material_method").contains(operation.get("adapter")),
                    "Unsupported structural operation adapter");
            java.util.List<Object> checks = checkGuards(sim, resolved, operation, token);
            java.util.Map<String, Object> readRequest = fields("schema_version", 1L, "action", "read",
                    "target", target, "properties", operation.get("read_properties"));
            java.util.Map<String, Object> before = inspect(sim, plan, readRequest, token);
            require(Boolean.TRUE.equals(before.get("inspection_complete")), "Operation requires complete source state");
            String property = string(operation.get("state_property"), "operation.state_property");
            require(sameValue(operationMethodContent(operation, request.get("expected")),
                    operationMethodContent(operation, propertyValue(before, property))), "Operation expected state does not match");
            // 2. 按各适配器的发现规则取得既有方法对象；准备期间不调用 setter。
            java.util.Map<String, Object> arguments = object(request.get("arguments"), "request.arguments");
            require(arguments.keySet().equals(java.util.Set.of("method")), "Operation requires a method argument");
            String methodId = string(arguments.get("method"), "arguments.method");
            star.base.neo.ClientServerObject method = selectedMethod(sim, resolved, operation, methodId);
            // 未活动方法也可能保留非常量分量；先只读其设置，避免已知不可回读的目标进入 setter。
            Object destination = operationMethodState(resolved, operation, method, token);
            Invocation setter = prepareWrite(sim, resolved, object(operation.get("write"), "operation.write"),
                    fields("method", method));
            before.put("checks", checks);
            before.put("selected_method_state", destination);
            return new PreparedOperation(sim, plan, readRequest, operation, before, token,
                    property, methodId, method, destination, setter);
        } catch (Exception error) {
            throw new IllegalArgumentException("Structural operation rejected: " + errorText(error), error);
        }
    }

    /** 保存已固定的源状态、方法对象与唯一 setter；进入 apply 后的错误均按结果不确定处理。 */
    private static final class PreparedOperation implements PreparedChange {
        private final star.common.Simulation sim;
        private final java.util.Map<String, Object> plan, readRequest, operation, before;
        private final String token, stateProperty, methodId, methodKey, methodClass;
        private final Object destination;
        private final Invocation setter;
        private boolean applied;
        PreparedOperation(star.common.Simulation sim, java.util.Map<String, Object> plan,
                java.util.Map<String, Object> readRequest, java.util.Map<String, Object> operation,
                java.util.Map<String, Object> before, String token, String stateProperty, String methodId,
                star.base.neo.ClientServerObject method, Object destination, Invocation setter) {
            this.sim = sim; this.plan = plan; this.readRequest = readRequest; this.operation = operation;
            this.before = before; this.token = token; this.stateProperty = stateProperty; this.methodId = methodId;
            this.methodKey = method.getObjectKeyAsString(); this.methodClass = method.getClass().getName();
            this.destination = destination; this.setter = setter;
        }
        public java.util.Map<String, Object> before() { return before; }

        public synchronized java.util.Map<String, Object> apply() throws Exception {
            if (applied) throw new IllegalStateException("Prepared operation has already been attempted");
            applied = true;
            checkVersion(sim, plan, token);
            Resolved resolved = locate(sim, object(plan.get("types"), "plan.types"),
                    object(readRequest.get("target"), "read target"), token, 0);
            checkGuards(sim, resolved, operation, token);
            // 1. setter 前重读源状态和可选方法，拒绝准备后发生的同名重建或设置变化。
            java.util.Map<String, Object> current = inspect(sim, plan, readRequest, token);
            require(Boolean.TRUE.equals(current.get("inspection_complete"))
                    && sameValue(before.get("properties"), current.get("properties")),
                    "Operation source state changed after preparation");
            star.base.neo.ClientServerObject selected = selectedMethod(sim, resolved, operation, methodId);
            require(methodKey.equals(selected.getObjectKeyAsString()), "Selected method identity changed");
            require(sameValue(destination, operationMethodState(resolved, operation, selected, token)),
                    "Selected method settings changed after preparation");
            setter.invoke();
            // 2. 新活动方法与对象身份必须匹配；全部已声明影响状态须能完整读取。
            java.util.Map<String, Object> after = inspect(sim, plan, readRequest, token);
            require(Boolean.TRUE.equals(after.get("inspection_complete")), "Operation readback is incomplete");
            require(sameValue(before.get("target"), after.get("target")), "Operation target identity changed");
            java.util.Map<String, Object> oldState = object(propertyValue(before, stateProperty), "old method state");
            java.util.Map<String, Object> newState = object(propertyValue(after, stateProperty), "new method state");
            require(methodClass.equals(newState.get("method")), "Operation method readback mismatch");
            require(methodKey.equals(currentOperationMethod(resolved, operation).getObjectKeyAsString()),
                    "Active method identity mismatch");
            java.util.List<String> identityFields = "profile_method".equals(operation.get("adapter"))
                    ? java.util.List.of("java_class", "dimensions", "is_3d", "shape")
                    : java.util.List.of("name", "java_class", "dimensions");
            for (String key : identityFields)
                require(sameValue(oldState.get(key), newState.get(key)), "Operation changed identity: " + key);
            for (Object raw : list(operation.get("preserved_properties"), "operation.preserved_properties")) {
                String name = string(raw, "preserved property");
                require(sameValue(propertyValue(before, name), propertyValue(after, name)),
                        "Operation changed preserved property: " + name);
            }
            return after;
        }
    }

    /**
     * 逐项读取目标条件并保留实际值；条件不满足是正常描述结果，读取异常才表示信息不完整。
     * 此处没有调用者的新值，因此新关联条件、单位、预期旧状态等仍由 Modifier 在写入前检查。
     */
    private static java.util.Map<String, Object> describeConditions(star.common.Simulation sim,
            Resolved resolved, java.util.Map<String, Object> property, String token) {
        java.util.List<?> guards = list(property.getOrDefault("condition_reads", java.util.List.of()),
                                       "property.condition_reads");
        java.util.List<Object> checks = new java.util.ArrayList<>();
        boolean failed = false, unavailable = false;
        for (Object raw : guards) {
            java.util.Map<String, Object> guard = object(raw, "condition");
            java.util.Map<String, Object> check = fields("id", guard.get("id"),
                    "expected", guard.get("expected"), "message", guard.get("message"));
            try {
                Object actual = encode(pipeline(sim, resolved.object, resolved.parent,
                        object(guard.get("read"), "condition.read")),
                        string(guard.get("adapter"), "condition.adapter"), token);
                boolean matched = sameValue(guard.get("expected"), actual);
                check.put("actual", actual);
                check.put("status", matched ? "satisfied" : "unsatisfied");
                failed |= !matched;
            } catch (Exception error) {
                unavailable = true;
                check.put("status", "error");
                check.put("error", errorText(error));
            }
            checks.add(check);
        }
        // 没有条件并不证明任意值可写，也不把尚未实现写入的属性显示成满足条件。
        String status = !Boolean.TRUE.equals(property.get("writable")) ? "not_implemented"
                : guards.isEmpty() ? "not_declared"
                : unavailable ? "error" : failed ? "unsatisfied" : "satisfied";
        return fields("conditions_checked", !guards.isEmpty() && !unavailable,
                "value_conditions_checked", false,
                "target_condition_status", status, "guard_checks", checks);
    }

    /**
     * 保存候选标量及其只读管线；每次检查都重新读取数量和范围，不缓存 GUI 可改变的范围。
     * quantityKey 固定准备阶段的数量身份，防止新建同名数量替代即将写入的原对象。
     */
    private static final class ScalarBoundsCheck {
        private final String quantityKey, definition;
        private final star.common.Units requestUnits;
        private final java.util.Map<String, Object> quantityRead, boundsRead;

        ScalarBoundsCheck(String quantityKey, String definition, star.common.Units requestUnits,
                java.util.Map<String, Object> quantityRead, java.util.Map<String, Object> boundsRead) {
            this.quantityKey = quantityKey; this.definition = definition; this.requestUnits = requestUnits;
            this.quantityRead = quantityRead; this.boundsRead = boundsRead;
        }

        /** 只修改两个普通临时 input；验证、求值和单位换算均不向原 quantity 写入。 */
        java.util.Map<String, Object> check(star.common.Simulation sim, Resolved resolved) throws Exception {
            // 1. 两条映射管线必须返回同一数量的 input；范围数值按原 input 的单位解释。
            Object rawQuantity = pipeline(sim, resolved.object, resolved.parent, quantityRead);
            require(rawQuantity instanceof star.common.ScalarPhysicalQuantity,
                    "Scalar bounds require a scalar quantity");
            star.common.ScalarPhysicalQuantity quantity = (star.common.ScalarPhysicalQuantity) rawQuantity;
            require(quantityKey.equals(quantity.getObjectKeyAsString()), "Scalar bounds quantity identity changed");
            Object rawInput = pipeline(sim, resolved.object, resolved.parent, boundsRead);
            require(rawInput instanceof star.common.BoundedScalarInput,
                    "Scalar bounds require a BoundedScalarInput");
            star.common.BoundedScalarInput original = (star.common.BoundedScalarInput) rawInput;
            require(original.getQuantity() != null
                    && quantityKey.equals(original.getQuantity().getObjectKeyAsString()),
                    "Scalar bounds input belongs to another quantity");
            star.common.Units originalUnits = original.getUnits();
            java.util.Map<String, Object> checked = scalarBounds(original);
            require(quantity.getUnits() != null && quantity.getUnits().compatible(requestUnits)
                    && originalUnits.compatible(requestUnits), "Incompatible scalar bounds unit");
            Double constant = star.common.PhysicalQuantityParser.parseAsConstant(definition);
            require(constant == null || Double.isFinite(constant), "Scalar constant must be finite");
            require(constant != null || requestUnits.getPresentationName().equals(
                    quantity.getUnits().getSIUnits().getPresentationName()),
                    "Scalar expressions require the SI result unit");

            // 2. 普通副本不携带 BoundedScalarInput 的可变 range；表达式切换单位不能影响原范围。
            star.common.ScalarPhysicalQuantityInput candidate = new star.common.ScalarPhysicalQuantityInput(original);
            candidate.setDefinition(definition);
            candidate.setUnitsNoRescale(requestUnits);
            String validation = candidate.validate();
            require(validation == null || validation.isEmpty(), "Scalar bounds preview validation failed: " + validation);
            double si = quantity.previewValue(candidate);
            require(Double.isFinite(si), "Scalar bounds preview must be finite");

            // 3. previewValue 总是返回 SI；普通副本保留 absolute/delta 约定，换回范围的原始单位。
            // range.getUnits() 可以为 null，不能据此把 range 的数值误判为 SI。
            star.common.ScalarPhysicalQuantityInput converted = new star.common.ScalarPhysicalQuantityInput(original);
            converted.setDefinition(Double.toString(si));
            converted.setUnitsNoRescale(originalUnits.getSIUnits());
            converted.setUnits(originalUnits);
            Double rangeValue = converted.isConstantValue();
            require(rangeValue != null && Double.isFinite(rangeValue), "Scalar bounds conversion must be finite");
            star.base.neo.ScalarRange range = original.getRange();
            require(range.contains(rangeValue.doubleValue()), "Scalar value is outside the allowed range");
            require(!range.isIntegral() || rangeValue.doubleValue() == Math.rint(rangeValue.doubleValue()),
                    "Scalar range requires an integral value");
            checked.put("preview_si_value", si);
            checked.put("range_value", rangeValue);
            return checked;
        }
    }

    /**
     * 保存已经完成预检查的单项修改；apply 只允许执行一次，失败后不得自动重试。
     * before/after 使用目录读取封套，旧完整快照与保存流程仍由调用方负责。
     */
    public static final class PreparedModification implements PreparedChange {
        public final java.util.Map<String, Object> before;
        private final star.common.Simulation sim;
        private final java.util.Map<String, Object> plan;
        private final java.util.Map<String, Object> readRequest;
        private final String token, property, adapter;
        private final Object value;
        private final Invocation invocation;
        private final java.util.Map<String, Object> writer;
        private final java.util.List<ReferenceBinding> bindings;
        private final ScalarBoundsCheck boundsCheck;
        private boolean applied;

        public java.util.Map<String, Object> before() { return before; }

        PreparedModification(star.common.Simulation sim, java.util.Map<String, Object> plan,
                java.util.Map<String, Object> readRequest, String token, String property,
                String adapter, Object value, Invocation invocation,
                java.util.Map<String, Object> writer, java.util.Map<String, Object> before,
                java.util.List<ReferenceBinding> bindings, ScalarBoundsCheck boundsCheck) {
            this.sim = sim; this.plan = plan; this.readRequest = readRequest; this.token = token;
            this.property = property; this.adapter = adapter; this.value = value;
            this.invocation = invocation; this.writer = writer; this.before = before;
            this.bindings = java.util.List.copyOf(bindings);
            this.boundsCheck = boundsCheck;
        }

        /**
         * setter 前重新定位并核对 guards，写入后核对目的属性、对象身份及声明的额外不变项。
         * 这些检查不锁定 GUI；一旦进入 apply，任何异常都沿结果不确定路径处理，不能重试。
         */
        public synchronized java.util.Map<String, Object> apply() throws Exception {
            if (applied) throw new IllegalStateException("Prepared modification has already been attempted");
            applied = true;
            checkVersion(sim, plan, token);
            Resolved current = locate(sim, object(plan.get("types"), "plan.types"),
                    object(readRequest.get("target"), "read target"), token, 0);
            checkGuards(sim, current, writer, token);
            // 新关联、标签及身份谓词均固定到准备阶段的 key；同名重建不能替代原对象。
            for (ReferenceBinding binding : bindings) {
                Resolved referenced = locate(sim, object(plan.get("types"), "plan.types"), binding.target, token, 0);
                checkGuards(sim, referenced, fields("guards", binding.guards), token);
            }
            // 范围和表达式依赖可能在准备后变化；紧贴唯一 setter 再读取并预览一次。
            // 此处失败仍属于 apply 的结果不确定路径，调用方不能自动重试 setter。
            if (boundsCheck != null) boundsCheck.check(sim, current);
            invocation.invoke();
            java.util.Map<String, Object> after = inspect(sim, plan, readRequest, token);
            if (!Boolean.TRUE.equals(after.get("inspection_complete")))
                throw new IllegalStateException("Modification readback is incomplete");
            verifyWritten(adapter, value, propertyValue(after, property));
            if (!sameValue(before.get("target"), after.get("target")))
                throw new IllegalStateException("Modification target identity changed");
            for (String key : java.util.List.of("name", "function_name", "value_type", "dimensions", "unit",
                    "profile_method", "property_method", "coordinate_system", "local_orientation", "basis")) {
                if (key.equals(property)) continue;
                if (key.equals("unit") && (adapter.equals("scalar_expression") || adapter.equals("scalar_value")
                        || adapter.equals("vector_expression") || adapter.equals("vector_value"))) continue;
                java.util.Map<String, Object> original = object(before.get("properties"), "before.properties");
                if (original.containsKey(key) && !sameValue(propertyValue(before, key), propertyValue(after, key)))
                    throw new IllegalStateException("Modification identity property changed: " + key);
            }
            // 额外不变项比较完整编码值；关联引用元数据也保留，读取失败不能视作相等。
            // before/after 已要求完整读取，不在此吞掉异常或重新执行 setter。
            for (Object raw : list(writer.getOrDefault("preserved_properties", java.util.List.of()),
                    "write.preserved_properties")) {
                String name = string(raw, "preserved property");
                if (!sameValue(propertyValue(before, name), propertyValue(after, name)))
                    throw new IllegalStateException("Modification preserved property changed: " + name);
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
        // 1. 先核对版本、对象引用和声明式前提，避免不适用的数量读取被误当成普通写入。
        checkVersion(sim, plan, token);
        Resolved resolved = locate(sim, object(plan.get("types"), "plan.types"), target, token, 0);
        String typeId = string(target.get("type"), "target.type");
        String property = string(request.get("property"), "request.property");
        java.util.Map<String, Object> properties = object(object(plan.get("properties"), "plan.properties").get(typeId), "type properties");
        java.util.Map<String, Object> entry = object(properties.get(property), "modification property");
        require(Boolean.TRUE.equals(entry.get("writable")), "Property is not implemented for writing");
        java.util.Map<String, Object> writer = object(entry.get("write"), "property.write");
        java.util.List<Object> checks = checkGuards(sim, resolved, writer, token);
        // 2. 全部前提通过后读取本类型所有属性；旧关联只忽略协议约定的引用元数据。
        java.util.Map<String, Object> before = inspect(sim, plan, readRequest, token);
        require(Boolean.TRUE.equals(before.get("inspection_complete")), "Modification requires complete catalog reads");
        require(sameValue(identity(resolved.object, token), object(before.get("target"), "before.target").get("reference")),
                "Modification target changed after precondition checks");
        if (!checks.isEmpty()) before.put("checks", checks);
        String adapter = string(writer.get("adapter"), "write.adapter");
        Object expected = request.get("expected"), actual = propertyValue(before, property);
        if (adapter.equals("user_tags")) {
            // 标签关联的旧状态是名称与实际类型集合；读回携带的 token/key 仅为描述。
            // 目标自身的 reference 已由 inspect 严格核对，不在此处削弱其身份前提。
            require(sameValue(tagState(expected), tagState(actual)), "Modification expected tags do not match");
        } else if (adapter.equals("reference")) {
            require(sameValue(referenceState(expected), referenceState(actual)), "Modification expected reference does not match");
        } else if (adapter.equals("object_selection")) {
            require(sameValue(selectionState(expected), selectionState(actual)), "Modification expected selection does not match");
        } else require(sameValue(expected, actual), "Modification expected value does not match");
        resolved = locate(sim, object(plan.get("types"), "plan.types"), target, token, 0);
        require(sameValue(identity(resolved.object, token), object(before.get("target"), "before.target").get("reference")),
                "Modification target changed during preparation");
        Object value = request.get("value");
        java.util.Map<String, Object> values = new java.util.LinkedHashMap<>();
        java.util.List<ReferenceBinding> bindings = new java.util.ArrayList<>();
        java.util.Map<String, Object> writePipeline = null;
        ScalarBoundsCheck boundsCheck = null;
        Object wantedReadback = value;
        // 3. 校验目标数量或枚举状态并绑定参数；解析最终 setter 仍不触发写入。
        try {
            if (adapter.equals("field_definition")) {
                require(resolved.object instanceof star.common.UserFieldFunction,
                        "Field definition writes require a user field function");
                require(value instanceof String && !((String) value).trim().isEmpty(), "Definition must be non-empty");
                values.put("value", value);
            } else if (adapter.equals("primitive")) {
                // JSON 数值共享同一种语义，布尔和文本各自保持类型；数值精度由最终参数转换再核对。
                require(value instanceof Boolean && actual instanceof Boolean
                        || value instanceof String && actual instanceof String
                        || value instanceof Number && actual instanceof Number,
                        "Primitive value must match the current JSON scalar type");
                if (value instanceof Number)
                    require(Double.isFinite(((Number) value).doubleValue()), "Primitive value must be finite");
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
                if (writer.containsKey("bounds")) {
                    String definition = adapter.equals("scalar_expression")
                            ? (String) values.get("definition")
                            : Double.toString(((Number) values.get("number")).doubleValue());
                    boundsCheck = new ScalarBoundsCheck(quantity.getObjectKeyAsString(), definition, units,
                            object(entry.get("read"), "property.read"), object(writer.get("bounds"), "write.bounds"));
                    before.put("bounds_check", boundsCheck.check(sim, resolved));
                }
            } else if (adapter.equals("vector_expression") || adapter.equals("vector_value")) {
                // 分量使用当前数量对象的原坐标约定；这里只更改定义或三个原始分量，不做坐标变换。
                Object raw = pipeline(sim, resolved.object, resolved.parent, object(entry.get("read"), "property.read"));
                require(raw instanceof star.common.VectorPhysicalQuantity, "Vector writes require a vector quantity");
                star.common.VectorPhysicalQuantity quantity = (star.common.VectorPhysicalQuantity) raw;
                finiteVector(quantity.getRawVector().toDoubleArray(), "Current vector");
                java.util.Map<String, Object> input = object(value, "vector value");
                String field = adapter.equals("vector_expression") ? "definition" : "components";
                require(input.keySet().equals(java.util.Set.of(field, "unit")), "Invalid vector value fields");
                require(input.get("unit") instanceof String, "Vector unit must be a string");
                star.common.Units units = uniqueNamed(sim.getUnitsManager().getObjects(), (String) input.get("unit"), star.common.Units.class);
                require(quantity.getUnits().compatible(units), "Incompatible result unit");
                values.put("units", units);
                if (adapter.equals("vector_expression")) {
                    String definition = string(input.get("definition"), "vector definition");
                    require(!definition.trim().isEmpty(), "Vector definition must be non-empty");
                    double[] constant = vectorConstant(definition);
                    require(constant != null || input.get("unit").equals(quantity.getUnits().getSIUnits().getPresentationName()),
                            "Vector expressions require the SI result unit");
                    values.put("definition", definition);
                } else {
                    vectorComponents(input.get("components"), "Vector components");
                    // 保留输入 Number 给 convert 做精度检查，不能预先转成 double 后掩盖损失。
                    java.util.List<?> items = list(input.get("components"), "Vector components");
                    values.put("x", items.get(0)); values.put("y", items.get(1)); values.put("z", items.get(2));
                }
            } else if (adapter.equals("enum")) {
                Object raw = pipeline(sim, resolved.object, resolved.parent, object(entry.get("read"), "property.read"));
                require(raw instanceof star.common.EnumeratedOption<?>, "Enum writes require an EnumeratedOption");
                String name = string(value, "enum value");
                Enum<?> selected = null;
                // 仅使用当前 option 返回的允许实例；不从用户输入推导任意枚举类或常量。
                for (Enum<?> candidate : ((star.common.EnumeratedOption<?>) raw).getElements()) {
                    if (!candidate.name().equals(name)) continue;
                    require(selected == null, "Enum value is ambiguous: " + name);
                    selected = candidate;
                }
                require(selected != null, "Enum value is not currently allowed: " + name);
                values.put("value", selected);
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
            } else if (adapter.equals("reference")) {
                // 先解析新关联，再在被关联对象上核对值条件；此阶段不调用任何 setter。
                java.util.Map<String, Object> input = object(value, "reference target");
                require(list(writer.get("value_types"), "write.value_types").contains(input.get("type")),
                        "Reference target type is not allowed");
                Resolved referenced = bindReference(sim, plan, input, token,
                        list(writer.getOrDefault("value_guards", java.util.List.of()), "write.value_guards"), bindings);
                values.put("value", referenced.object);
                wantedReadback = reference(referenced.object, token);
                // 值条件描述被关联对象，独立于主目标 guards；保留准备阶段实际通过的证据。
                ReferenceBinding binding = bindings.get(bindings.size() - 1);
                before.put("value_checks", java.util.List.of(fields(
                        "target", reference(referenced.object, token), "checks", binding.checks)));
            } else if (adapter.equals("object_selection")) {
                java.util.Map<String, Object> input = object(value, "object selection");
                String mode = string(input.get("mode"), "selection.mode");
                Object raw = pipeline(sim, resolved.object, resolved.parent, object(entry.get("read"), "property.read"));
                require(raw instanceof star.base.query.ManagerWithQuery<?>, "Selection writes require a ManagerWithQuery");
                if (mode.equals("static")) {
                    require(input.keySet().equals(java.util.Set.of("mode", "objects")), "Invalid static selection fields");
                    java.util.List<star.base.neo.ClientServerObject> objects = new java.util.ArrayList<>();
                    java.util.Set<String> seen = new java.util.HashSet<>();
                    for (Object item : list(input.get("objects"), "selection.objects")) {
                        java.util.Map<String, Object> selected = object(item, "selection target");
                        require(list(writer.get("value_types"), "write.value_types").contains(selected.get("type")),
                                "Selection target type is not allowed");
                        Resolved referenced = bindReference(sim, plan, selected, token, java.util.List.of(), bindings);
                        require(seen.add(referenced.object.getObjectKeyAsString()), "Duplicate selected object identity");
                        objects.add(referenced.object);
                    }
                    // PartGroup 的过滤模型定义实际允许对象；合法 Java 类型本身不足以证明可选。
                    // STAR setObjects 内部先清除 query 再替换列表，进入 apply 后失败仍是结果不确定。
                    require(raw instanceof star.common.ManagerWithFilterModel<?>, "Static selection requires a filter model");
                    require(((star.common.ManagerWithFilterModel<?>) raw).isValid(objects), "Selection contains invalid objects");
                    values.put("value", objects);
                    wantedReadback = fields("mode", "static", "objects", collection(objects, token));
                } else if (mode.equals("query")) {
                    require(input.keySet().equals(java.util.Set.of("mode", "predicate", "modifiers")),
                            "Invalid dynamic selection fields");
                    star.base.query.QueryPredicate predicate = buildPredicate(sim, plan, writer,
                            input.get("predicate"), token, bindings, 0, new int[] {0});
                    java.util.EnumSet<star.base.query.Query.Modifier> modifiers = java.util.EnumSet.noneOf(star.base.query.Query.Modifier.class);
                    for (Object modifier : list(input.get("modifiers"), "query.modifiers")) {
                        star.base.query.Query.Modifier selected = star.base.query.Query.Modifier.valueOf(string(modifier, "query modifier"));
                        require(selected == star.base.query.Query.Modifier.PrefilterNamedObjects, "Unsupported query modifier");
                        require(modifiers.add(selected), "Duplicate query modifier");
                    }
                    // 保留规则本身，不求值，也不要求它在当前算例中匹配到对象。
                    star.base.query.Query query = new star.base.query.Query(predicate, modifiers);
                    values.put("value", query);
                    wantedReadback = queryDefinition(query, token);
                } else throw new IllegalArgumentException("Unsupported selection mode: " + mode);
                writePipeline = object(object(writer.get("pipelines"), "write.pipelines").get(mode), "selection write pipeline");
            } else throw new IllegalArgumentException("Unsupported write adapter: " + adapter);
            if (writePipeline == null) writePipeline = object(writer.get("pipeline"), "write.pipeline");
            // 只解析一次最终调用；静态模式由 STAR setObjects 自行清除 query，不能提前额外清除。
            Invocation setter = prepareWrite(sim, resolved, writePipeline, values);
            // 回读固定到本次准备得到的 key，不能让同名重建的对象冒充写入对象。
            java.util.Map<String, Object> fixedTarget = new java.util.LinkedHashMap<>(target);
            fixedTarget.put("reference", identity(resolved.object, token));
            java.util.Map<String, Object> fixedRead = fields("schema_version", 1L, "action", "read", "target", fixedTarget);
            return new PreparedModification(sim, plan, fixedRead, token, property, adapter, wantedReadback,
                    setter, writer, before, bindings, boundsCheck);
        } catch (Exception error) {
            throw new IllegalArgumentException("Modification preparation failed: " + errorText(error), error);
        }
    }

    /**
     * 顺序读取声明式前提并严格比较编码值，返回可审阅的已通过检查记录。
     * 管线仍受只读 effect 限制；前提只约束 setter 调用前状态，不要求写入后继续成立。
     */
    private static java.util.List<Object> checkGuards(star.common.Simulation sim, Resolved resolved,
            java.util.Map<String, Object> writer, String token) {
        java.util.List<Object> checks = new java.util.ArrayList<>();
        java.util.Set<String> ids = new java.util.HashSet<>();
        for (Object raw : list(writer.getOrDefault("guards", java.util.List.of()), "write.guards")) {
            java.util.Map<String, Object> guard = object(raw, "write guard");
            require(guard.keySet().equals(java.util.Set.of("id", "read", "adapter", "expected", "message")),
                    "Invalid write guard fields");
            String id = string(guard.get("id"), "guard.id");
            require(ids.add(id), "Duplicate write guard: " + id);
            String message = string(guard.get("message"), "guard.message");
            try {
                Object actual = encode(pipeline(sim, resolved.object, resolved.parent,
                        object(guard.get("read"), "guard.read")), string(guard.get("adapter"), "guard.adapter"), token);
                require(sameValue(guard.get("expected"), actual),
                        "Write precondition failed [" + id + "]: " + message);
                checks.add(fields("id", id, "expected", guard.get("expected"), "actual", actual));
            } catch (Exception error) {
                throw new IllegalArgumentException("Write precondition rejected [" + id + "]: "
                        + message + " (" + errorText(error) + ")", error);
            }
        }
        return checks;
    }

    /** 保存一个新关联的定位路径及值条件；路径中的每层父对象都带本会话身份。 */
    private static final class ReferenceBinding {
        final java.util.Map<String, Object> target;
        final java.util.List<?> guards;
        final java.util.List<Object> checks;
        ReferenceBinding(java.util.Map<String, Object> target, java.util.List<?> guards, java.util.List<Object> checks) {
            this.target = target;
            this.guards = java.util.List.copyOf(guards);
            this.checks = java.util.List.copyOf(checks);
        }
    }

    /** 解析、检查并固定新关联；被引用对象的值条件同时用于准备和最终调用前。 */
    private static Resolved bindReference(star.common.Simulation sim, java.util.Map<String, Object> plan,
            java.util.Map<String, Object> target, String token, java.util.List<?> guards,
            java.util.List<ReferenceBinding> bindings) {
        java.util.Map<String, Object> types = object(plan.get("types"), "plan.types");
        java.util.Map<String, Object> fixed = pinTarget(sim, types, target, token, 0);
        Resolved resolved = locate(sim, types, fixed, token, 0);
        java.util.List<Object> checks = checkGuards(sim, resolved, fields("guards", guards), token);
        bindings.add(new ReferenceBinding(fixed, guards, checks));
        return resolved;
    }

    /** 逐层固定父路径后再定位当前对象，防止同名父对象在两次解析之间被替换。 */
    private static java.util.Map<String, Object> pinTarget(star.common.Simulation sim,
            java.util.Map<String, Object> types, java.util.Map<String, Object> target, String token, int depth) {
        require(depth < 32, "Reference parent nesting is too deep");
        require(java.util.Set.of("type", "name", "parent", "reference").containsAll(target.keySet()),
                "Invalid reference target fields");
        java.util.Map<String, Object> fixed = new java.util.LinkedHashMap<>(target);
        if (target.containsKey("parent")) fixed.put("parent", pinTarget(sim, types,
                object(target.get("parent"), "reference parent"), token, depth + 1));
        Resolved resolved = locate(sim, types, fixed, token, 0);
        fixed.put("reference", identity(resolved.object, token));
        return fixed;
    }

    /**
     * 在本地构造已支持的规则树；只从写入器声明的对象类型选择 Java 类型。
     * 节点数与深度分别计数，组合分支不能通过大量浅层节点绕过容量上限。
     */
    private static star.base.query.QueryPredicate buildPredicate(star.common.Simulation sim,
            java.util.Map<String, Object> plan, java.util.Map<String, Object> writer, Object value,
            String token, java.util.List<ReferenceBinding> bindings, int depth, int[] nodes) throws Exception {
        checkPredicateBudget(depth, nodes);
        java.util.Map<String, Object> rule = object(value, "query predicate");
        String type = string(rule.get("type"), "predicate.type");
        String operator = string(rule.get("operator"), "predicate.operator");
        if (type.equals("compound")) {
            require(rule.keySet().equals(java.util.Set.of("type", "operator", "predicates")), "Invalid compound predicate fields");
            java.util.List<star.base.query.QueryPredicate> children = new java.util.ArrayList<>();
            for (Object child : list(rule.get("predicates"), "predicate.predicates"))
                children.add(buildPredicate(sim, plan, writer, child, token, bindings, depth + 1, nodes));
            return new star.base.query.CompoundPredicate(star.base.query.CompoundOperator.valueOf(operator), children);
        }
        if (type.equals("includes")) {
            require(rule.keySet().equals(java.util.Set.of("type", "operator")), "Invalid includes predicate fields");
            // Placeholder 是编辑器占位选项，不作为可写规则发布。
            require(operator.equals("All") || operator.equals("None"), "Unsupported includes operator");
            return new star.base.query.IncludesPredicate(star.base.query.IncludesOperator.valueOf(operator));
        }
        require(rule.keySet().equals(java.util.Set.of("type", "operator", "value")), "Invalid predicate fields");
        if (type.equals("comment")) {
            require(rule.get("value") instanceof String, "Predicate comment must be a string");
            return new star.base.query.CommentPredicate(star.base.query.CommentOperator.valueOf(operator),
                    (String) rule.get("value"));
        }
        if (type.equals("identity")) {
            // 完整保留多对象规则，不能用只适用于单对象的 getClientServerObject 截断集合。
            // 每项按目录定位并固定身份，apply 前由公共 ReferenceBinding 再次核对。
            java.util.List<star.base.neo.ClientServerObject> objects = new java.util.ArrayList<>();
            java.util.Set<String> seen = new java.util.HashSet<>();
            for (Object item : list(rule.get("value"), "identity predicate objects")) {
                java.util.Map<String, Object> target = object(item, "identity predicate target");
                require(list(writer.get("value_types"), "write.value_types").contains(target.get("type")),
                        "Identity predicate target type is not allowed");
                Resolved resolved = bindReference(sim, plan, target, token, java.util.List.of(), bindings);
                require(seen.add(resolved.object.getObjectKeyAsString()), "Duplicate identity predicate object");
                objects.add(resolved.object);
            }
            return new star.base.query.IdentityPredicate(star.base.query.IdentityOperator.valueOf(operator), objects);
        }
        if (type.equals("name")) {
            // 空名称也是合法匹配值；只有正则算子才解释模式，其余算子保持原始文本。
            require(rule.get("value") instanceof String, "Predicate name must be a string");
            String name = (String) rule.get("value");
            star.base.query.NameOperator selected = star.base.query.NameOperator.valueOf(operator);
            if (selected == star.base.query.NameOperator.RegexContains
                    || selected == star.base.query.NameOperator.RegexDoesNotContain)
                java.util.regex.Pattern.compile(name);
            return new star.base.query.NamePredicate(selected, name);
        }
        if (type.equals("java_type")) {
            String className = string(rule.get("value"), "predicate Java type");
            java.util.Map<String, Object> types = object(plan.get("types"), "plan.types");
            boolean allowed = false;
            for (Object typeId : list(writer.get("value_types"), "write.value_types")) {
                java.util.Map<String, Object> selected = object(types.get(string(typeId, "value type")), "selected value type");
                allowed |= className.equals(selected.get("java_class"));
            }
            require(allowed, "Query Java type is not allowed");
            Class<?> selected = javaType(className);
            require(star.base.neo.ClientServerObject.class.isAssignableFrom(selected), "Query type must be a STAR object");
            return new star.base.query.TypePredicate(star.base.query.TypeOperator.valueOf(operator),
                    selected.asSubclass(star.base.neo.ClientServerObject.class));
        }
        if (type.equals("tag")) {
            java.util.Map<String, Object> target = object(rule.get("value"), "predicate tag target");
            require("user_tag".equals(target.get("type")), "Tag predicate requires a user_tag target");
            Resolved resolved = bindReference(sim, plan, target, token, java.util.List.of(), bindings);
            require(resolved.object instanceof star.common.UserTag, "Tag predicate requires a UserTag");
            return new star.base.query.TagPredicate(star.base.query.TagOperator.valueOf(operator), (star.common.UserTag) resolved.object);
        }
        throw new IllegalArgumentException("Unsupported query predicate type: " + type);
    }

    /** 根规则深度为零；读取与构造共用同一限额，保证写入结果一定能规范回读。 */
    private static void checkPredicateBudget(int depth, int[] nodes) {
        require(depth <= 16, "Query predicate nesting exceeds 16 levels");
        require(++nodes[0] <= 256, "Query predicate count exceeds 256 nodes");
    }

    /** 旧关联仅忽略本对象的引用元数据，其余字段继续参与严格比较。 */
    private static Object referenceState(Object value) {
        if (value == null) return null;
        java.util.Map<String, Object> result = new java.util.LinkedHashMap<>(object(value, "reference state"));
        result.remove("reference");
        return result;
    }

    /** 静态列表、标签和身份集合中的引用元数据不构成旧规则的业务状态。 */
    private static Object selectionState(Object value) {
        java.util.Map<String, Object> result = new java.util.LinkedHashMap<>(object(value, "selection state"));
        if ("static".equals(result.get("mode"))) {
            java.util.List<Object> objects = new java.util.ArrayList<>();
            for (Object item : list(result.get("objects"), "selection objects")) objects.add(referenceState(item));
            // 旧状态不含身份元数据后按名称和实际类排序；相同项保留数量，不能变成集合。
            objects.sort(java.util.Comparator.comparing((Object item) ->
                    string(object(item, "selected reference").get("name"), "selected name"))
                    .thenComparing(item -> string(object(item, "selected reference").get("java_class"), "selected type")));
            result.put("objects", objects);
        } else if ("query".equals(result.get("mode"))) {
            result.put("predicate", predicateState(result.get("predicate"), 0, new int[] {0}));
        }
        return result;
    }

    /** 只规范标签和身份集合内的引用，保留其他谓词字段和组合顺序。 */
    private static Object predicateState(Object value, int depth, int[] nodes) {
        checkPredicateBudget(depth, nodes);
        java.util.Map<String, Object> result = new java.util.LinkedHashMap<>(object(value, "predicate state"));
        if ("tag".equals(result.get("type"))) result.put("value", referenceState(result.get("value")));
        else if ("identity".equals(result.get("type"))) {
            // 与静态选择共用集合比较：移除身份元数据后排序，保留同名同类项的数量。
            java.util.Map<String, Object> normalized = object(selectionState(
                    fields("mode", "static", "objects", result.get("value"))), "identity predicate state");
            result.put("value", normalized.get("objects"));
        } else if ("compound".equals(result.get("type"))) {
            java.util.List<Object> children = new java.util.ArrayList<>();
            for (Object child : list(result.get("predicates"), "compound predicates"))
                children.add(predicateState(child, depth + 1, nodes));
            result.put("predicates", children);
        }
        return result;
    }

    /** 向量写入只接受三个有限原始分量，二维数据必须由调用者显式补全。 */
    private static double[] finiteVector(double[] values, String location) {
        require(values.length == 3, location + " must contain exactly three components");
        for (double value : values) require(Double.isFinite(value), location + " must be finite");
        return values;
    }

    /** 将 JSON 向量读成三个有限数；拒绝布尔、字符串和隐式缺省分量。 */
    private static double[] vectorComponents(Object value, String location) {
        java.util.List<?> input = list(value, location);
        require(input.size() == 3, location + " must contain exactly three components");
        double[] result = new double[3];
        for (int index = 0; index < result.length; index++) {
            require(input.get(index) instanceof Number, location + " must contain numbers");
            result[index] = ((Number) input.get(index)).doubleValue();
        }
        return finiteVector(result, location);
    }

    /** STAR 2602 的三分量常量解析返回 DoubleVector；非纯常量返回 null。 */
    private static double[] vectorConstant(String definition) {
        star.base.neo.DoubleVector parsed = star.common.PhysicalQuantityParser.parseAsConstant(definition, 3);
        return parsed == null ? null : finiteVector(parsed.toDoubleArray(), "Vector constant");
    }

    /** 浮点回读允许数量 setter 的舍入误差，所有参与比较的分量都必须有限。 */
    private static boolean closeVector(double[] wanted, double[] actual) {
        for (int index = 0; index < wanted.length; index++) {
            double a = wanted[index], b = actual[index];
            if (Math.abs(a - b) > Math.max(1e-12, 1e-12 * Math.max(Math.abs(a), Math.abs(b)))) return false;
        }
        return true;
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
        } else if (adapter.equals("vector_expression") || adapter.equals("vector_value")) {
            java.util.Map<String, Object> input = object(wanted, "vector input"), output = object(actual, "vector output");
            double[] readback = vectorComponents(output.get("components"), "Vector readback");
            matches = sameValue(input.get("unit"), output.get("unit"));
            if (adapter.equals("vector_expression")) {
                String before = string(input.get("definition"), "vector definition");
                String after = string(output.get("definition"), "vector readback definition");
                boolean definitionMatches = before.equals(after);
                if (!definitionMatches) {
                    // 纯常量允许 STAR 调整空白或数字格式；动态表达式仍必须文本完全相同。
                    double[] a = vectorConstant(before), b = vectorConstant(after);
                    definitionMatches = a != null && b != null;
                    if (definitionMatches)
                        for (int index = 0; index < a.length; index++) definitionMatches &= a[index] == b[index];
                }
                matches &= definitionMatches;
            } else matches &= closeVector(vectorComponents(input.get("components"), "Vector input"), readback);
        } else if (adapter.equals("enum")) {
            java.util.Map<String, Object> output = object(actual, "enum output");
            matches = sameValue(wanted, output.get("selected"))
                    && list(output.get("allowed"), "enum allowed").contains(wanted);
        } else if (adapter.equals("reference") || adapter.equals("object_selection")) {
            // 新关联按准备阶段的规范结果完整核对，包含本会话 key，不能只比较名称。
            matches = sameValue(wanted, actual);
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

    /**
     * 读取原 input 单位下的范围；有限端点用 contains 检查实际成员资格。
     * 端点成员资格不试图恢复退化空区间内部保存的开闭标志；无有限界返回 null。
     */
    private static java.util.Map<String, Object> scalarBounds(star.common.BoundedScalarInput input) {
        star.base.neo.ScalarRange range = input.getRange();
        star.common.Units units = input.getUnits();
        require(range != null && units != null, "Scalar bounds require a range and input unit");
        double minimum = range.getMin(), maximum = range.getMax();
        require(!Double.isNaN(minimum) && !Double.isNaN(maximum), "Scalar bounds endpoints must not be NaN");
        return fields("input_unit", units.getPresentationName(),
                "minimum", Double.isFinite(minimum) ? minimum : null,
                "maximum", Double.isFinite(maximum) ? maximum : null,
                "minimum_included", Double.isFinite(minimum) ? range.contains(minimum) : null,
                "maximum_included", Double.isFinite(maximum) ? range.contains(maximum) : null,
                "integral", range.isIntegral());
    }

    /** 按值种类序列化，不依据对象类名猜测未实现的数据格式。 */
    private static Object encode(Object value, String adapter, String sessionToken) {
        require(java.util.List.of("primitive", "reference", "collection", "quantity", "vector", "enum", "query",
                "name", "type_name", "java_class", "names", "enum_name", "presence", "tensor_profile", "tensor_basis", "tensor_method_state", "tensor_method_basis", "tensor_components", "tensor_axes", "tensor_axis_basis", "tensor_layout_valid", "material_coefficient_basis", "material_coefficient_state", "material_method_state", "scalar_bounds")
                .contains(adapter), "Unsupported value adapter: " + adapter);
        // presence 必须先于 null 分支处理，缺失对象明确编码成 false。
        if (adapter.equals("presence")) return value != null;
        // 类型、枚举和名称集合必须有实际值；空集合与缺失集合不能混为一谈。
        // 单对象 name 仍允许 null，以表示报告等对象尚未设置可选单位。
        if (value == null) {
            require(!java.util.List.of("type_name", "java_class", "names", "enum_name", "tensor_profile", "tensor_basis", "tensor_method_state", "tensor_method_basis", "tensor_components", "tensor_axes", "tensor_axis_basis", "tensor_layout_valid", "material_coefficient_basis", "material_coefficient_state", "material_method_state", "scalar_bounds").contains(adapter),
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
            case "java_class": return value.getClass().getName();
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
            case "scalar_bounds":
                require(value instanceof star.common.BoundedScalarInput,
                        "Scalar bounds adapter requires a BoundedScalarInput");
                return scalarBounds((star.common.BoundedScalarInput) value);
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
            case "tensor_profile": return tensorProfile(value, sessionToken);
            case "tensor_basis": return tensorBasis(value, sessionToken, true);
            case "tensor_method_state": return tensorMethodState(value, sessionToken);
            case "tensor_method_basis": return tensorBasis(value, sessionToken, false);
            case "tensor_components": return collection(tensorComponents(value), sessionToken);
            case "tensor_axes": return collection(tensorAxes(value), sessionToken);
            case "tensor_axis_basis": return tensorAxisBasis(value, sessionToken);
            case "tensor_layout_valid": return tensorLayoutValid(value);
            case "material_coefficient_basis": return materialCoefficients(value, false, sessionToken);
            case "material_coefficient_state": return materialCoefficients(value, true, sessionToken);
            case "material_method_state": return materialMethodState(value, sessionToken);
            default: throw new IllegalArgumentException("Unsupported value adapter: " + adapter);
        }
    }

    /**
     * 读取材料当前多系数方法的组织与可选数量，不将系数名称猜成某个矩阵布局。
     * basis 只保存方法、量纲和按 API 顺序配对的名称/子属性元数据，用于单系数写入后的身份核对；
     * state 额外读取各系数的当前常量数量，任一不支持的方法都会令完整状态读取失败。
     */
    private static Object materialCoefficients(Object value, boolean withQuantities, String token) {
        require(value instanceof star.material.MaterialProperty,
                "Material coefficient adapter requires a MaterialProperty");
        star.material.MaterialProperty property = (star.material.MaterialProperty) value;
        return materialCoefficients(property, property.getMethod(), withQuantities, token);
    }

    /** 沿指定材料方法读取系数；供操作预检查复用，所传方法可以尚未活动。 */
    private static java.util.Map<String, Object> materialCoefficients(star.material.MaterialProperty property,
            star.material.MaterialPropertyMethod current, boolean withQuantities, String token) {
        // 1. 不重新取得父物性的活动方法；MultiCoefficient.getMethod(int) 也禁止用于只读路径。
        require(current instanceof star.material.MultiCoefficientMaterialPropertyMethod,
                "Unsupported material coefficient method: " + (current == null ? "null" : current.getClass().getName()));
        star.material.MultiCoefficientMaterialPropertyMethod method =
                (star.material.MultiCoefficientMaterialPropertyMethod) current;
        java.util.List<String> names = method.getCoefficientNames();
        java.util.List<star.material.ScalarMaterialProperty> properties = method.getScalarProperties();
        require(names != null && properties != null && names.size() == properties.size(),
                "Material coefficient names and properties do not have matching lengths");

        // 2. API 的名称顺序与子属性顺序一一对应；显示名称另行保留，供通用定位器唯一匹配。
        // 不补写对称项、不硬编码 3/6/9 项，也不把不同材料的系数解释为相同坐标含义。
        java.util.List<Object> coefficients = new java.util.ArrayList<>();
        for (int index = 0; index < properties.size(); index++) {
            star.material.ScalarMaterialProperty coefficient = properties.get(index);
            String name = names.get(index);
            require(coefficient != null && name != null && !name.isEmpty(),
                    "Material coefficient metadata is missing at index " + index);
            java.util.Map<String, Object> item = fields("index", index, "coefficient_name", name,
                    "name", coefficient.getPresentationName(), "java_class", coefficient.getClass().getName(),
                    "dimensions", coefficient.getDimensions().toString());
            if (withQuantities) {
                // 3. ScalarMaterialProperty 的无参 getter 不改变方法；函数系数不伪装成常量数量。
                star.material.MaterialPropertyMethod scalarMethod = coefficient.getMethod();
                require(scalarMethod instanceof star.material.ConstantMaterialPropertyMethod,
                        "Unsupported material coefficient method for " + name + ": "
                        + (scalarMethod == null ? "null" : scalarMethod.getClass().getName()));
                item.put("method", scalarMethod.getClass().getName());
                item.put("quantity", encode(((star.material.ConstantMaterialPropertyMethod) scalarMethod).getQuantity(),
                        "quantity", token));
            }
            coefficients.add(item);
        }
        return fields("name", property.getPresentationName(), "java_class", property.getClass().getName(),
                "method", current.getClass().getName(), "dimensions", property.getDimensions().toString(),
                "coefficients", coefficients);
    }

    /** 读取当前材料方法的完整设置；使用无参 getter，不为获得状态而改变方法。 */
    private static Object materialMethodState(Object value, String token) {
        require(value instanceof star.material.MaterialProperty,
                "Material method state requires a MaterialProperty");
        star.material.MaterialProperty property = (star.material.MaterialProperty) value;
        return materialMethodState(property, property.getMethod(), token);
    }

    /**
     * 保存指定材料方法的常量或多系数设置，供源旧状态比较与未活动目标的准备检查使用。
     * 两种存储保留同一组顶层字段：常量有 quantity 和空 coefficients，多系数有空 quantity
     * 和完整 coefficients。此处不推导物理合理性，也不保证激活时服务器绝不初始化设置。
     */
    private static Object materialMethodState(star.material.MaterialProperty property,
            star.material.MaterialPropertyMethod method, String token) {
        require(method != null, "Material property method is missing");
        java.util.Map<String, Object> result;
        if (method instanceof star.material.ConstantMaterialPropertyMethod) {
            result = fields("name", property.getPresentationName(), "java_class", property.getClass().getName(),
                    "method", method.getClass().getName(), "dimensions", property.getDimensions().toString(),
                    "storage", "constant", "quantity", encode(
                            ((star.material.ConstantMaterialPropertyMethod) method).getQuantity(), "quantity", token),
                    "coefficients", java.util.List.of());
        } else {
            result = materialCoefficients(property, method, true, token);
            require(!list(result.get("coefficients"), "material coefficients").isEmpty(),
                    "Material method state requires coefficient settings");
            result.put("storage", "coefficients");
            result.put("quantity", null);
        }
        return result;
    }

    /** 保存一次取得的方法及其独立分量布局；这里只描述组织，不访问 quantity 或切换方法。 */
    private static final class TensorLayout {
        final star.common.ProfileMethod method;
        final String storage;
        final int dimension;
        TensorLayout(star.common.ProfileMethod method, String storage, int dimension) {
            this.method = method; this.storage = storage; this.dimension = dimension;
        }
        boolean matrix() { return storage.equals("full") || storage.equals("symmetric_lower"); }
    }

    /** 保存实际标量子 Profile 及输出标签；非矩阵布局不用虚构 row/column。 */
    private static final class TensorComponent {
        final String name;
        final star.common.ScalarProfile profile;
        final int row, column;
        TensorComponent(String name, star.common.ScalarProfile profile, int row, int column) {
            require(profile != null, "Unsupported tensor component: missing " + name);
            this.name = name; this.profile = profile; this.row = row; this.column = column;
        }
        TensorComponent(String name, star.common.ScalarProfile profile) {
            this(name, profile, -1, -1);
        }
    }

    /** 保存方向标签与实际向量 Profile；标签解释用途，显示名称用于子对象定位。 */
    private static final class TensorAxis {
        final String name;
        final star.common.VectorProfile profile;
        TensorAxis(String name, star.common.VectorProfile profile) {
            require(profile != null, "Tensor direction axis is missing: " + name);
            this.name = name; this.profile = profile;
        }
    }

    /**
     * 核对二维或三维及真实方法布局；full 先于 symmetric 判型，避免把上三角独立项丢掉。
     * 矩阵子类范围保持兼容；主方向、各向同性及轴对称布局只接收已核对的精确类。
     * 直接拥有轴 Profile 的方法与 LocalOrientation 关联方法分开标记，避免遗漏轴设置。
     */
    private static TensorLayout tensorLayout(star.common.TensorProfile profile, star.common.ProfileMethod method) {
        int dimension = profile.is3D() ? 3 : 2;
        require(method != null, "Tensor profile method is missing");
        String storage;
        if (method instanceof star.common.CompositeTensorProfileMethod
                || method instanceof star.common.CompositeSymmetricTensorProfileMethodWithCoordinateSystem) {
            star.common.CompositeSymmetricTensorProfileMethod matrix = (star.common.CompositeSymmetricTensorProfileMethod) method;
            // getProfileNum 表示矩阵维数，不是 full/symmetric 的独立分量总数。
            require(matrix.getProfileNum() == dimension,
                    "Tensor profile dimension does not match its matrix method: expected " + dimension);
            storage = method instanceof star.common.CompositeTensorProfileMethod ? "full" : "symmetric_lower";
        } else if (method.getClass() == star.common.IsotropicTensorProfileMethod.class) {
            storage = "isotropic";
        } else if (method.getClass() == star.common.OrthotropicTensorProfileMethod.class) {
            require(((star.common.OrthotropicTensorProfileMethod) method).getProfileNum() == dimension,
                    "Tensor profile dimension does not match its principal method: expected " + dimension);
            storage = "principal";
        } else if (method.getClass() == star.common.PrincipalTensorProfileMethodWithAxes.class) {
            require(((star.common.PrincipalTensorProfileMethodWithAxes) method).getProfileNum() == dimension,
                    "Tensor profile dimension does not match its principal axes method: expected " + dimension);
            storage = "principal_axes";
        } else if (method.getClass() == star.common.TransverseIsotropicTensorProfileMethod.class) {
            storage = "axisymmetric";
        } else if (method.getClass() == star.common.AxisymmetricTensorProfileMethodWithAxis.class) {
            storage = "axisymmetric_axis";
        } else {
            throw new IllegalArgumentException("Unsupported tensor profile method: " + method.getClass().getName());
        }
        return new TensorLayout(method, storage, dimension);
    }

    /** 读取布局与方向；直接拥有的轴保存完整数量，不能把轴内容缩减成关联名称。 */
    private static java.util.Map<String, Object> tensorBasis(star.common.TensorProfile profile,
            TensorLayout layout, String token) {
        return tensorBasis(profile, layout, token, true);
    }

    /** 轴子对象写入只保留各轴元数据；标量分量与结构操作则同时保留完整方向向量。 */
    private static java.util.Map<String, Object> tensorBasis(star.common.TensorProfile profile,
            TensorLayout layout, String token, boolean withAxisQuantities) {
        star.common.ProfileMethod method = layout.method;
        star.base.neo.ClientServerObject coordinateSystem = null;
        star.base.neo.ClientServerObject localOrientation = null;
        if (method instanceof star.common.CompositeTensorProfileMethodWithCoordinateSystem)
            coordinateSystem = ((star.common.CompositeTensorProfileMethodWithCoordinateSystem) method).getCoordinateSystem();
        else if (method instanceof star.common.CompositeSymmetricTensorProfileMethodWithCoordinateSystem)
            coordinateSystem = ((star.common.CompositeSymmetricTensorProfileMethodWithCoordinateSystem) method).getCoordinateSystem();
        if (method instanceof star.common.AnisotropicTensorProfileMethod)
            localOrientation = ((star.common.AnisotropicTensorProfileMethod) method).getLocalOrientation();
        else if (method.getClass() == star.common.OrthotropicTensorProfileMethod.class)
            localOrientation = ((star.common.OrthotropicTensorProfileMethod) method).getLocalOrientation();
        else if (method.getClass() == star.common.TransverseIsotropicTensorProfileMethod.class)
            localOrientation = ((star.common.TransverseIsotropicTensorProfileMethod) method).getLocalOrientation();
        // shape 描述当前维度的二阶张量；各向同性、主方向及轴对称配置项不扩充成完整矩阵。
        // LocalOrientation/坐标系仍只保留关联身份；方法自身拥有的轴需单独展开，不转换坐标。
        java.util.Map<String, Object> result = fields("java_class", profile.getClass().getName(), "method", method.getClass().getName(),
                "dimensions", profile.getDimensions().toString(), "is_3d", layout.dimension == 3,
                "shape", java.util.List.of(layout.dimension, layout.dimension),
                "storage", layout.storage, "coordinate_system", encode(coordinateSystem, "reference", token),
                "local_orientation", encode(localOrientation, "reference", token));
        java.util.List<TensorAxis> entries = tensorAxisEntries(layout);
        if (!entries.isEmpty()) {
            java.util.List<Object> axes = new java.util.ArrayList<>();
            for (TensorAxis axis : entries) axes.add(tensorAxisState(axis, token, withAxisQuantities));
            result.put("direction_axes", axes);
        }
        return result;
    }

    /** 只访问已核对方法直接拥有的方向轴；二维主方向方法仍保留 X、Y 两个轴对象。 */
    private static java.util.List<TensorAxis> tensorAxisEntries(TensorLayout layout) {
        if (layout.storage.equals("principal_axes")) {
            star.common.PrincipalTensorProfileMethodWithAxes method =
                    (star.common.PrincipalTensorProfileMethodWithAxes) layout.method;
            return java.util.List.of(new TensorAxis("X", method.getXAxis()), new TensorAxis("Y", method.getYAxis()));
        }
        if (layout.storage.equals("axisymmetric_axis")) {
            return java.util.List.of(new TensorAxis("AXIAL",
                    ((star.common.AxisymmetricTensorProfileMethodWithAxis) layout.method).getAxiAxis()));
        }
        return java.util.List.of();
    }

    /**
     * 保存轴自身的方法、维数和坐标关联，再按需读取常量向量的定义、单位和原始三项分量。
     * 2602 的二维轴 getSize() 为 2，原始数量仍有三项；不得裁剪、补零或自行归一化。
     */
    private static Object tensorAxisState(TensorAxis axis, String token, boolean withQuantity) {
        star.common.VectorProfile profile = axis.profile;
        star.common.ProfileMethod method = profile.getMethod();
        require(method != null, "Tensor direction axis method is missing: " + axis.name);
        java.util.Map<String, Object> result = fields("axis", axis.name,
                "name", profile.getPresentationName(), "java_class", profile.getClass().getName(),
                "method", method.getClass().getName(), "dimensions", profile.getDimensions().toString(),
                "is_3d", profile.is3D(), "size", profile.getSize(),
                "coordinate_system", encode(profile.getCoordinateSystem(), "reference", token));
        if (withQuantity) {
            require(method.getClass() == star.common.ConstantVectorProfileMethod.class,
                    "Unsupported tensor direction axis method for " + axis.name + ": " + method.getClass().getName());
            Object quantity = encode(((star.common.ConstantVectorProfileMethod) method).getQuantity(), "vector", token);
            require(list(object(quantity, "axis quantity").get("components"), "axis vector components").size() == 3,
                    "Tensor direction axis requires three raw vector components");
            result.put("quantity", quantity);
        }
        return result;
    }

    /** 枚举轴供父属性和子对象名称查询；不读取数量或改变当前轴方法。 */
    private static java.util.List<star.common.VectorProfile> tensorAxes(Object value) {
        require(value instanceof star.common.TensorProfile, "Tensor axes require a TensorProfile");
        star.common.TensorProfile profile = (star.common.TensorProfile) value;
        java.util.List<star.common.VectorProfile> axes = new java.util.ArrayList<>();
        for (TensorAxis axis : tensorAxisEntries(tensorLayout(profile, profile.getMethod()))) axes.add(axis.profile);
        return axes;
    }

    /** 为单轴写入保留父方法、维数及各轴元数据，不把允许修改的向量数量放进不变量。 */
    private static Object tensorAxisBasis(Object value, String token) {
        require(value instanceof star.common.TensorProfile, "Tensor axis basis requires a TensorProfile");
        star.common.TensorProfile profile = (star.common.TensorProfile) value;
        TensorLayout layout = tensorLayout(profile, profile.getMethod());
        require(!tensorAxisEntries(layout).isEmpty(), "Tensor method does not own supported direction axes");
        return tensorBasis(profile, layout, token, false);
    }

    /** 描述当前方法的方向与布局；旧 tensor_basis 保留三维矩阵限定，新入口支持全部已适配布局。 */
    private static Object tensorBasis(Object value, String token, boolean matrixOnly) {
        require(value instanceof star.common.TensorProfile, "Tensor adapter requires a TensorProfile");
        star.common.TensorProfile profile = (star.common.TensorProfile) value;
        TensorLayout layout = tensorLayout(profile, profile.getMethod());
        require(!matrixOnly || layout.dimension == 3, "Unsupported tensor profile: only 3D profiles are supported");
        require(!matrixOnly || layout.matrix(), "Unsupported tensor profile method: " + layout.method.getClass().getName());
        return tensorBasis(profile, layout, token);
    }

    /** 枚举指定布局实际拥有的独立分量，不读取分量的方法、quantity，也不包含未激活的其他方法。 */
    private static java.util.List<TensorComponent> tensorComponentEntries(TensorLayout layout) {
        star.common.ProfileMethod method = layout.method;
        java.util.List<TensorComponent> components = new java.util.ArrayList<>();
        if (layout.matrix()) {
            star.common.CompositeSymmetricTensorProfileMethod matrix = (star.common.CompositeSymmetricTensorProfileMethod) method;
            String axes = "XYZ";
            for (int row = 0; row < layout.dimension; row++) {
                for (int column = 0; column < layout.dimension; column++) {
                    if (layout.storage.equals("symmetric_lower") && column > row) continue;
                    components.add(new TensorComponent("" + axes.charAt(row) + axes.charAt(column),
                            matrix.getProfile(row, column), row, column));
                }
            }
        } else if (layout.storage.equals("isotropic")) {
            components.add(new TensorComponent("ISOTROPIC",
                    ((star.common.IsotropicTensorProfileMethod) method).getIsotropicProfile()));
        } else if (layout.storage.equals("principal") || layout.storage.equals("principal_axes")) {
            star.common.PrincipalTensorProfileMethod principal = (star.common.PrincipalTensorProfileMethod) method;
            components.add(new TensorComponent("X", principal.getXProfile()));
            components.add(new TensorComponent("Y", principal.getYProfile()));
            // 二维只具有两个主方向配置项，不能访问或补写第三个分量。
            if (layout.dimension == 3) components.add(new TensorComponent("Z", principal.getZProfile()));
        } else {
            star.common.AxisymmetricTensorProfileMethod axial = (star.common.AxisymmetricTensorProfileMethod) method;
            components.add(new TensorComponent("AXIAL", axial.getAxiProfile()));
            components.add(new TensorComponent("CROSS_STREAM", axial.getCrossStreamProfile()));
        }
        return components;
    }

    /** 从当前无参方法枚举可定位的实际子 Profile；此结果不依赖分量数量的读取适配器。 */
    private static java.util.List<star.common.ScalarProfile> tensorComponents(Object value) {
        require(value instanceof star.common.TensorProfile, "Tensor components require a TensorProfile");
        star.common.TensorProfile profile = (star.common.TensorProfile) value;
        TensorLayout layout = tensorLayout(profile, profile.getMethod());
        java.util.List<star.common.ScalarProfile> profiles = new java.util.ArrayList<>();
        for (TensorComponent component : tensorComponentEntries(layout)) profiles.add(component.profile);
        return profiles;
    }

    /** 只校验当前布局和维度供写入前提使用；不读取方向、分量或 quantity，未知布局明确报错。 */
    private static boolean tensorLayoutValid(Object value) {
        require(value instanceof star.common.TensorProfile, "Tensor layout requires a TensorProfile");
        star.common.TensorProfile profile = (star.common.TensorProfile) value;
        tensorLayout(profile, profile.getMethod());
        return true;
    }

    /** 原完整张量读取入口仍只接受三维 full/symmetric；字段、分量顺序与常量方法约束保持不变。 */
    private static Object tensorProfile(Object value, String token) {
        require(value instanceof star.common.TensorProfile, "Tensor adapter requires a TensorProfile");
        star.common.TensorProfile profile = (star.common.TensorProfile) value;
        TensorLayout layout = tensorLayout(profile, profile.getMethod());
        require(layout.dimension == 3, "Unsupported tensor profile: only 3D profiles are supported");
        require(layout.matrix(), "Unsupported tensor profile method: " + layout.method.getClass().getName());
        return tensorMethodState(profile, layout, token);
    }

    /** 读取方法切换需要核对的当前活动设置；无参 getter 不会切换当前方法。 */
    private static Object tensorMethodState(Object value, String token) {
        require(value instanceof star.common.TensorProfile, "Tensor method state requires a TensorProfile");
        star.common.TensorProfile profile = (star.common.TensorProfile) value;
        return tensorMethodState(profile, profile.getMethod(), token);
    }

    /**
     * 读取指定方法的独立设置，供结构操作在 setter 前验证将要选择的方法能完整回读。
     * 调用方从目标 Profile 的可选方法中取得 method；此处不重新获取目标 Profile 的当前方法，
     * 只用无参 getter 读取其标量子 Profile 的方法，不提前激活目标方法。
     * 返回值不保证激活后设置绝不被 STAR 初始化；实际修改仍须重新读取。
     */
    private static Object tensorMethodState(star.common.TensorProfile profile,
            star.common.ProfileMethod method, String token) {
        return tensorMethodState(profile, tensorLayout(profile, method), token);
    }

    /** 在共同元数据和分量枚举后读取标量数量；非常量分量明确失败，不把错误当成零值。 */
    private static Object tensorMethodState(star.common.TensorProfile profile, TensorLayout layout, String token) {
        java.util.Map<String, Object> result = tensorBasis(profile, layout, token);
        java.util.List<Object> components = new java.util.ArrayList<>();
        for (TensorComponent component : tensorComponentEntries(layout)) {
            star.common.ProfileMethod method = component.profile.getMethod();
            require(method instanceof star.common.ConstantScalarProfileMethod,
                    "Unsupported tensor component method for " + component.name + ": "
                    + (method == null ? "null" : method.getClass().getName()));
            java.util.Map<String, Object> item = fields("name", component.name);
            if (component.row >= 0) {
                item.put("row", component.row);
                item.put("column", component.column);
            }
            item.put("method", method.getClass().getName());
            item.put("quantity", encode(((star.common.ConstantScalarProfileMethod) method).getQuantity(), "quantity", token));
            components.add(item);
        }
        result.put("components", components);
        return result;
    }

    /** 查询保留规则本身；未知谓词明确失败，不能把动态规则变成一次性的对象列表。 */
    private static Object query(Object value, String sessionToken) {
        require(value instanceof star.base.query.ManagerWithQuery<?>, "Query adapter requires a ManagerWithQuery");
        star.base.query.ManagerWithQuery<?> manager = (star.base.query.ManagerWithQuery<?>) value;
        star.base.query.Query query = manager.getQuery();
        if (query == null) {
            return fields("mode", "static", "objects", collection(manager.getObjects(), sessionToken));
        }
        return queryDefinition(query, sessionToken);
    }

    /** 动态选择以规则与 modifiers 回读，不把当前求值结果写成静态对象列表。 */
    private static Object queryDefinition(star.base.query.Query query, String sessionToken) {
        Object rule = encodePredicate(query.getPredicate(), sessionToken, 0, new int[] {0});
        java.util.List<String> modifiers = new java.util.ArrayList<>();
        for (star.base.query.Query.Modifier modifier : query.getModifiers()) modifiers.add(modifier.name());
        java.util.Collections.sort(modifiers);
        return fields("mode", "query", "predicate", rule, "modifiers", modifiers);
    }

    /** 仅编码公开 getter 已核对的精确谓词类；未知子类不能假装成已支持规则。 */
    private static Object encodePredicate(star.base.query.QueryPredicate predicate, String token, int depth, int[] nodes) {
        checkPredicateBudget(depth, nodes);
        if (predicate != null && predicate.getClass() == star.base.query.CommentPredicate.class) {
            star.base.query.CommentPredicate comment = (star.base.query.CommentPredicate) predicate;
            return fields("type", "comment", "operator", comment.getOperator().name(), "value", comment.getText());
        }
        if (predicate != null && predicate.getClass() == star.base.query.IncludesPredicate.class) {
            star.base.query.IncludesPredicate includes = (star.base.query.IncludesPredicate) predicate;
            require(includes.getOperator() != star.base.query.IncludesOperator.Placeholder, "Unsupported includes placeholder");
            return fields("type", "includes", "operator", includes.getOperator().name());
        }
        if (predicate != null && predicate.getClass() == star.base.query.IdentityPredicate.class) {
            star.base.query.IdentityPredicate identity = (star.base.query.IdentityPredicate) predicate;
            return fields("type", "identity", "operator", identity.getOperator().name(),
                    "value", collection(identity.getObjects(), token));
        }
        if (predicate != null && predicate.getClass() == star.base.query.NamePredicate.class) {
            star.base.query.NamePredicate name = (star.base.query.NamePredicate) predicate;
            return fields("type", "name", "operator", name.getOperator().name(), "value", name.getName());
        }
        if (predicate != null && predicate.getClass() == star.base.query.TypePredicate.class) {
            star.base.query.TypePredicate type = (star.base.query.TypePredicate) predicate;
            return fields("type", "java_type", "operator", type.getOperator().name(), "value", type.getType().getName());
        }
        if (predicate != null && predicate.getClass() == star.base.query.CompoundPredicate.class) {
            star.base.query.CompoundPredicate compound = (star.base.query.CompoundPredicate) predicate;
            java.util.List<Object> children = new java.util.ArrayList<>();
            for (star.base.query.QueryPredicate child : compound.getPredicates())
                children.add(encodePredicate(child, token, depth + 1, nodes));
            return fields("type", "compound", "operator", compound.getOperator().name(), "predicates", children);
        }
        if (predicate != null && predicate.getClass() == star.base.query.TagPredicate.class) {
            star.base.query.TagPredicate tag = (star.base.query.TagPredicate) predicate;
            return fields("type", "tag", "operator", tag.getOperator().name(), "value", encode(tag.getTag(), "reference", token));
        }
        throw new IllegalArgumentException("Unsupported query predicate: "
                + (predicate == null ? "null" : predicate.getClass().getName()));
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

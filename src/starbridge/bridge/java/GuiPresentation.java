import java.util.*;
import org.openide.nodes.Node;
import star.base.neo.ClientServerObject;
import star.base.neo.NamedObject;
import star.common.Simulation;
import star.common.ui.RootProcessNode;
import star.common.ui.RootProcessNodeManager;
import star.common.ui.SimulationProcessNode;
import star.coremodule.SimulationProcessObject;
import star.coremodule.StarBeanNode;

/** 查询官方节点模型中的位置与显示元数据，不请求打开视图或选择节点，不返回业务属性值。
 * 原生节点和动作构造可能读取所需状态；本方法不调用 Property.getValue，也不以显示元数据代替当前值。
 * 此辅助类只由显式的 GUI 呈现方法引入；普通宏不因此依赖 GUI 模块。
 * 结果来自本客户端的标准 Simulation 树，不是另一个 GUI 窗口的当前选择或自定义布局。
 */
public final class GuiPresentation {
    /** 只把已有 Simulation 关联到本地表示对象，不连接新服务器、不重载文件。
     * setRootObject 是官方文档列出的 protected 扩展点；这里不调用会预加载视图的 getRootProcessNode。
     */
    private static final class PresentationProcess extends SimulationProcessObject {
        PresentationProcess(Simulation simulation) {
            super(simulation.getServer());
            setRootObject(simulation);
        }
    }

    private static Map<String,Object> fields(Object... values) {
        Map<String,Object> result = new LinkedHashMap<>();
        for (int i = 0; i < values.length; i += 2) result.put((String)values[i], values[i + 1]);
        return result;
    }

    private static Map<String,Object> error(Throwable error) {
        return fields("type", error.getClass().getName(), "message", String.valueOf(error.getMessage()));
    }

    /** 每次请求共用一个根表示；逐目标处理错误，避免一个不可呈现对象抹掉其他已取得的位置。 */
    public static Map<String,Object> inspect(Simulation simulation, List<?> targets,
            boolean includeProperties, boolean includeActions, int limit) throws Exception {
        RootProcessNode root = RootProcessNodeManager.getSingleton().getRootProcessNode(simulation);
        String rootSource = "existing_current_client";
        if (root == null) {
            // 直接构建官方根节点即可读取模型。getRootProcessNode 会额外 preLoad 窗口，批处理中不能调用。
            root = new SimulationProcessNode(new PresentationProcess(simulation));
            rootSource = "constructed_without_views";
        }
        if (root.getRootProcessObject().getRootObject() != simulation)
            throw new IllegalStateException("GUI root is not associated with the bound simulation");
        List<Object> items = new ArrayList<>();
        boolean complete = true;
        for (int index = 0; index < targets.size(); index++) {
            Map<?,?> request = (Map<?,?>)targets.get(index);
            ClientServerObject target = (ClientServerObject)request.get("object");
            Map<String,Object> item = fields("target_index", index, "java_class", target.getClass().getName());
            try {
                if (target.getServer() != simulation.getServer())
                    throw new IllegalArgumentException("GUI target belongs to another server connection");
                if (target instanceof NamedObject named) item.put("name", named.getPresentationName());
                StarBeanNode node = target == simulation ? root : StarBeanNode.getNode(root, target);
                if (node == null) {
                    item.putAll(fields("status", "unavailable", "reason", "No official GUI node was returned"));
                } else {
                    List<?> childPath = request.get("child_path") instanceof List<?> path ? path : List.of();
                    node = selectChild(node, childPath, limit, item);
                    if (node != null) locate(root, node, request, includeProperties, includeActions, limit, item);
                }
            } catch (Exception | LinkageError | java.awt.AWTError failure) {
                item.putAll(fields("status", "error", "error", error(failure)));
            }
            if (!"ok".equals(item.get("status"))) complete = false;
            items.add(item);
        }
        return fields("read_status", complete ? "complete" : "partial", "source", "official_gui_node_model",
                "tree_scope", "standard_simulation_tree", "root_source", rootSource,
                "locale", Locale.getDefault().toLanguageTag(), "remote_gui_observed", false,
                "view_open_requested", false, "property_values_requested", false, "actions_invoked", false,
                "validity", "Current-client model observation; not an atomic snapshot or a remote window layout",
                "targets", items);
    }

    /** 虚拟分组按当前节点的直接 GUI 子项定位；同类多项须再给当前名称，不使用旧序号猜目标。 */
    private static StarBeanNode selectChild(StarBeanNode parent, List<?> selectors, int limit,
            Map<String,Object> result) {
        for (int depth = 0; depth < selectors.size(); depth++) {
            Map<?,?> selector = (Map<?,?>)selectors.get(depth);
            Node[] children = parent.getChildren().getNodes(true);
            if (children.length > limit) {
                result.putAll(fields("status", "partial", "reason", "GUI child selection exceeds the item budget",
                        "child_depth", depth, "observed_child_count", children.length));
                return null;
            }
            List<StarBeanNode> matches = new ArrayList<>();
            for (Node child : children) {
                if (!(child instanceof StarBeanNode bean) || bean.getObject() == null) continue;
                if (!bean.getObject().getClass().getName().equals(selector.get("java_class"))) continue;
                if (selector.containsKey("name") && !child.getDisplayName().equals(selector.get("name"))) continue;
                matches.add(bean);
            }
            if (matches.size() != 1) {
                result.putAll(fields("status", matches.isEmpty() ? "not_found" : "ambiguous",
                        "reason", "GUI child selector must match exactly one current direct child",
                        "child_depth", depth, "matches", matches.size()));
                return null;
            }
            parent = matches.get(0);
        }
        return parent;
    }

    /** 只有真实父链到达当前官方根节点，才返回已解析路径；断链和循环不回退为拥有者路径。 */
    private static void locate(RootProcessNode root, StarBeanNode node, Map<?,?> request,
            boolean includeProperties, boolean includeActions, int limit, Map<String,Object> result) {
        List<Object> path = new ArrayList<>();
        Set<Node> seen = Collections.newSetFromMap(new IdentityHashMap<>());
        Node current = node;
        while (current != null && seen.add(current) && path.size() < 64) {
            Object bean = current instanceof StarBeanNode star ? star.getObject() : null;
            path.add(0, fields("label", current.getDisplayName(), "node_class", current.getClass().getName(),
                    "bean_class", bean == null ? null : bean.getClass().getName()));
            if (current == root) break;
            current = current.getParentNode();
        }
        if (current != root) {
            result.putAll(fields("status", "unavailable", "reason", "GUI ancestry did not reach the current root",
                    "observed_ancestry", path));
            return;
        }
        result.putAll(fields("status", "ok", "gui_path_status", "resolved", "path", path));
        String propertyName = request.get("property_name") instanceof String name ? name : "";
        Map<String,Object> properties = includeProperties || !propertyName.isEmpty()
                ? properties(node, propertyName, limit) : fields("status", "not_requested");
        Map<String,Object> actions = includeActions ? actions(node, limit) : fields("status", "not_requested");
        result.put("properties", properties);
        result.put("context_menu", actions);
        for (Map<String,Object> section : List.of(properties, actions)) {
            if (!Set.of("complete", "not_requested").contains(section.get("status"))) result.put("status", "partial");
        }
    }

    /** 读取节点属性栏的名称和类型，不调用 Property.getValue，也不把可写性当成当前值。 */
    private static Map<String,Object> properties(StarBeanNode node, String name, int limit) {
        List<Object> values = new ArrayList<>();
        Map<String,Object> result = fields("status", "complete", "scope", "node_property_sheet", "items", values);
        int inspected = 0;
        try {
            for (Node.PropertySet set : node.getPropertySets()) {
                for (Node.Property<?> property : set.getProperties()) {
                    if (++inspected > limit) {
                        result.putAll(fields("status", "partial", "reason", "Property inspection budget exhausted"));
                        return result;
                    }
                    if (property.isHidden() || (!name.isEmpty() && !name.equals(property.getName()))) continue;
                    values.add(fields("name", property.getName(), "label", property.getDisplayName(),
                            "property_set", set.getName(), "property_set_label", set.getDisplayName(),
                            "java_type", property.getValueType().getName(),
                            "readable", property.canRead(), "writable", property.canWrite()));
                }
            }
            if (!name.isEmpty() && values.isEmpty()) result.putAll(fields("status", "not_found",
                    "reason", "No matching visible property in this node property sheet"));
        } catch (Exception | LinkageError | java.awt.AWTError failure) {
            result.putAll(fields("status", "error", "error", error(failure)));
        }
        return result;
    }

    /** 构建但不显示本节点的轻量弹出菜单，读取组件文本，不把 Action.NAME 猜成实际菜单标签。
     * 自定义 presenter 可改变文案；未展开子菜单也不能被解释为空菜单。AWT 初始化失败局部保留。
     */
    private static Map<String,Object> actions(StarBeanNode node, int limit) {
        List<Object> values = new ArrayList<>();
        Map<String,Object> result = fields("status", "complete", "scope", "context_menu_root_components",
                "source", "local_node_popup", "submenus_expanded", false,
                "enabled_state_observed", false, "display_requested", false, "items", values);
        try {
            javax.swing.JPopupMenu popup = node.getContextMenu();
            java.awt.Component[] components = popup.getComponents();
            for (int index = 0; index < components.length; index++) {
                if (index >= limit) {
                    result.putAll(fields("status", "partial", "reason", "Context menu inspection budget exhausted"));
                    break;
                }
                java.awt.Component component = components[index];
                if (component instanceof javax.swing.JSeparator) {
                    values.add(fields("kind", "separator"));
                } else if (component instanceof javax.swing.JMenuItem item) {
                    String label = item.getText();
                    boolean available = label != null && !label.isBlank();
                    Map<String,Object> entry = fields("kind", item instanceof javax.swing.JMenu ? "submenu" : "item",
                            "label", label, "label_status", available ? "available" : "unavailable",
                            "label_source", "popup_component_text", "component_class", component.getClass().getName(),
                            "visible_in_model", component.isVisible());
                    if (item instanceof javax.swing.JMenu) entry.put("children_state", "not_requested");
                    values.add(entry);
                    if (!available) result.put("status", "partial");
                } else {
                    values.add(fields("kind", "unsupported_component", "component_class", component.getClass().getName()));
                    result.put("status", "partial");
                }
            }
        } catch (Exception | LinkageError | java.awt.AWTError failure) {
            result.putAll(fields("status", "error", "error", error(failure)));
        }
        return result;
    }
}

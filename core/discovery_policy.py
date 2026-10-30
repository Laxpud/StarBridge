"""集中登记发现提供器、值类型规则、精确版本与禁止项。

规则描述可调用机制，不宣称任意 getter 无副作用。执行前仍需实际 Bean
描述符、规则条件及本机官方成员声明全部一致；新类型默认仅保留元数据。
"""

TARGET = {'release': '2602', 'build': '21.02.007'}
POLICY_VERSION = 'discovery-policy-v1'
PRIMITIVES = {'boolean', 'byte', 'short', 'int', 'long', 'float', 'double', 'char',
              'java.lang.Boolean', 'java.lang.Byte', 'java.lang.Short', 'java.lang.Integer',
              'java.lang.Long', 'java.lang.Float', 'java.lang.Double', 'java.lang.Character', 'java.lang.String'}
INPUTS = {
    'star.common.ScalarPhysicalQuantityInput': ('quantity', 'star.common.CompiledValueFunctionInput', 'getQuantity'),
    'star.common.BoundedScalarInput': ('quantity', 'star.common.CompiledValueFunctionInput', 'getQuantity'),
    'star.common.VectorPhysicalQuantityInput': ('vector', 'star.common.CompiledValueFunctionInput', 'getQuantity'),
    'star.common.EnumeratedOptionInput': ('enum', 'star.common.EnumeratedOptionInput', 'getEnumeratedOption'),
}
# 声明返回基类不能证明运行时包装器类型；解包前只接受这些已登记的精确类。
# 不自动纳入 Javadoc 列出的其他子类，避免其覆盖方法扩大实际调用范围。
INPUT_RECEIVER_TYPES = {
    'quantity': ['star.common.ScalarPhysicalQuantityInput', 'star.common.BoundedScalarInput'],
    'vector': ['star.common.VectorPhysicalQuantityInput'],
    'enum': ['star.common.EnumeratedOptionInput'],
}
PROVIDERS = {
    'cso_children': {'target': TARGET, 'owner': 'star.base.neo.ClientServerObject',
        'member': 'getChildren()', 'evidence': '2602 实际树遍历与公开 CSO 接口；非 CSO 子项仅返回代理元数据'},
    'bean_descriptors': {'target': TARGET, 'evidence': '真实 Bean 描述符与 StarBeanProperty 注解；发现阶段不调用属性 getter'},
}
READ_RULES = {
    'primitive': {'id': 'bean-primitive-v1', 'target': TARGET, 'types': sorted(PRIMITIVES),
        'evidence': '公开无参 Bean 属性的 JSON 基础值适配；需逐成员核对官方声明',
        'unsupported': '未声明基础类型或规则禁止项'},
    **{kind: {'id': 'bean-input-' + kind + '-v1', 'target': TARGET,
             'types': sorted(t for t, value in INPUTS.items() if value[0] == kind),
             'evidence': '2602 已登记 input 类型与固定解包成员；执行时先核对包装器精确类型，未知子类拒绝',
             'unsupported': '未知 input 类型或解包声明缺失'} for kind in ('quantity', 'vector', 'enum')},
}
# 禁止项先于类型规则判断；维护者可按精确 owner/member 登记例外，不靠返回类型放行。
DENY = {'members': set(), 'owners': set(), 'annotation_names': {'Internal', 'Deprecated'},
        'hidden': True, 'descriptor_forbidden': True}
DYNAMIC_RANGES = {('star.resurfacer.PartsResurfacerAnisotropicSizing', 'ratioRange')}
DYNAMIC_RANGE_EVIDENCE = {
    'target': TARGET, 'evidence': '已核验 ratioRange 字节码仅由 MinRatio/MaxRatio 创建 ScalarRange；其他动态方法不调用'}


def rule_evidence(adapter):
    """给能力说明返回可审阅的机制依据，实际成员验证状态由调用方另行报告。"""
    rule = READ_RULES[adapter]
    return {key: rule[key] for key in ('id', 'target', 'evidence', 'unsupported')}

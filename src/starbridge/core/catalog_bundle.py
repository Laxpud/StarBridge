"""按明确产品版本与 Build 选择随附目录，统一文件、会话和兼容入口的版本绑定。"""

from pathlib import Path

from .catalog import CatalogError


# 此表只登记已提供独立目录的安装版本，不按版本号接近程度推测兼容性。
BUNDLES = {'2602': '21.02.007', '2510': '20.06.007'}
DEFAULT_RELEASE = '2602'


def bundle_target(release=None):
    """将 CLI 的明确 release 转为完整目标；省略时保留原入口的 2602 默认行为。"""
    release = DEFAULT_RELEASE if release is None else release
    if not isinstance(release, str) or release not in BUNDLES:
        raise CatalogError(f'Unsupported bundled catalog release: {release}')
    return {'release': release, 'build': BUNDLES[release]}


def bundle_root(target=None):
    """仅为登记的精确 release/build 返回路径；拒绝未知版本和同 release 的其他 Build。"""
    target = bundle_target() if target is None else target
    if not isinstance(target, dict) or target != bundle_target(target.get('release')):
        raise CatalogError(f'Unsupported bundled catalog target: {target}')
    return Path(__file__).resolve().parents[1] / 'catalogs' / target['release']


def check_plan_targets(*plans, target=None):
    """在创建输出目录或会话活动标记前，核对本次所有执行计划来自相同精确版本。"""
    selected = target
    for plan in plans:
        if plan is None:
            continue
        current = plan.get('target')
        if not isinstance(current, dict):
            raise CatalogError('Execution plan requires an explicit catalog target')
        bundle_root(current)
        if selected is None:
            selected = current
        if selected != current:
            raise CatalogError(f'Execution plan target mismatch: expected {selected}, got {current}')
    if selected is not None:
        bundle_root(selected)
    return selected


def session_target(state):
    """旧会话没有版本字段时沿用原固定 2602 契约；显式字段损坏或未知时拒绝。"""
    target = state.get('catalog_target', bundle_target())
    if target is None:
        raise CatalogError('Session catalog_target must not be null')
    bundle_root(target)
    return target

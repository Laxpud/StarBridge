#!/usr/bin/env python3
"""提供离线目录生成、查询、人工规则合并、版本比较及分项覆盖报告。"""

import argparse
import json
from pathlib import Path
import sys

# 入口可从任意工作目录执行；核心模块不依赖本机安装路径。
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.catalog import compare, describe, load, read_json, summary, validate
from core.coverage import coverage
from javadoc import generate, installation_version


def output_json(value, path=None):
    """输出 JSON；文件必须不存在，防止生成过程覆盖人工目录或已有结果。"""
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if path is None:
        print(text, end='')
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x', encoding='utf-8') as stream:
            stream.write(text)


def main():
    """先校验输入和版本，再输出候选或合并目录；不连接算例、修改 .sim 或启动 STAR。"""
    parser = argparse.ArgumentParser(description='Generate and inspect offline STAR API catalogs.')
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('generate', help='Generate candidates from one STAR installation.')
    create.add_argument('--install', type=Path, required=True)
    scope = create.add_mutually_exclusive_group(required=True)
    scope.add_argument('--selection', type=Path, help='JSON array of fully qualified Java types.')
    scope.add_argument('--all', action='store_true', help='Include all indexed STAR types.')
    create.add_argument('--output', type=Path, required=True)
    for action in ('check', 'describe', 'merge'):
        command = commands.add_parser(action)
        command.add_argument('--catalog', type=Path, required=True)
        command.add_argument('--overrides', type=Path)
        command.add_argument('--install', type=Path, help='Require an exact installation version match.')
        if action == 'describe':
            command.add_argument('--type', required=True)
        if action == 'merge':
            command.add_argument('--output', type=Path, required=True)
    diff = commands.add_parser('diff', help='Compare two catalogs; never infer compatibility.')
    diff.add_argument('before', type=Path)
    diff.add_argument('after', type=Path)
    diff.add_argument('--output', type=Path)
    report = commands.add_parser('coverage', help='Separate discovery, implementation and observed runtime evidence.')
    report.add_argument('--catalog', type=Path, required=True)
    report.add_argument('--execution', type=Path)
    report.add_argument('--overrides', type=Path)
    report.add_argument('--install', type=Path, help='Require an exact installation version match.')
    report.add_argument('--result', type=Path, action='append', default=[],
                        help='Existing Runner JSON result; repeat to add evidence.')
    report.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'generate':
            selected = read_json(args.selection) if args.selection else None
            if args.selection is not None and (not isinstance(selected, list) or not selected
                    or any(not isinstance(name, str) or not name for name in selected)):
                raise ValueError('Selection must be a non-empty JSON array of type names')
            data = validate(generate(args.install, selected))
            output_json(data, args.output)
            output_json(summary(data))
        elif args.command == 'diff':
            output_json(compare(load(args.before), load(args.after)), args.output)
        elif args.command == 'coverage':
            target = installation_version(args.install)[0] if args.install else {}
            output_json(coverage(args.catalog, execution_path=args.execution, overrides=args.overrides,
                                 results=args.result, **target), args.output)
        else:
            target = installation_version(args.install)[0] if args.install else {}
            data = load(args.catalog, overrides=args.overrides, **target)
            if args.command == 'merge':
                if args.overrides is None:
                    raise ValueError('merge requires --overrides')
                output_json(data, args.output)
                output_json(summary(data))
            elif args.command == 'describe':
                output_json(describe(data, args.type))
            else:
                output_json(summary(data))
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f'StarBridge catalog error: {error}\n')


if __name__ == '__main__':
    main()

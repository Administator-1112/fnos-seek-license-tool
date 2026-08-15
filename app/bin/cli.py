#!/usr/bin/env python3
"""seek-license-tool CLI 入口"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'core'))

import manager
import monitor
import payload


def cmd_status(args):
    s = manager.get_status()
    if args.json:
        print(json.dumps(s, ensure_ascii=False, indent=2))
        return
    print("=== Seek 许可证工具状态 ===")
    print(f"时间: {s['time']}")
    print(f"trim_license 运行: {'是' if s['trim_license_running'] else '否'}")
    print(f"二进制已 patch: {'是' if s['binary']['patched'] else '否'}")
    lic = s['license']
    if lic:
        print(f"授权码: {lic['license_code']}")
        print(f"名称: {lic['name']}")
        print(f"等级: {lic.get('edition', lic['tag'])}")
        print(f"状态: {lic['status']}")
        from datetime import datetime
        print(f"生效: {datetime.fromtimestamp(lic['valid_from']/1000)}" if lic['valid_from'] else "生效: 1970-01-01")
        print(f"截至: {datetime.fromtimestamp(lic['valid_to']/1000)}")
    print(f"官方备份: {'存在' if s['official_backup_exists'] else '无'}")


def cmd_apply(args):
    print(f"应用破解...")
    ok, steps = manager.apply_license(
        edition=args.edition,
        license_code=args.license_code,
        name=args.name,
        valid_from=args.valid_from,
        valid_to=args.valid_to,
    )
    for st in steps:
        print(f"  {st}")
    return 0 if ok else 1


def cmd_remove(args):
    print("移除破解...")
    ok, steps = manager.remove_license()
    for st in steps:
        print(f"  {st}")
    return 0 if ok else 1


def cmd_editions(args):
    print("可用权益等级:")
    for e, info in payload.EDITIONS.items():
        print(f"  {e:<20} {info['label']}  用户={info['userLimit']} 项目={info['projectLimit']}")


def cmd_monitor(args):
    m = monitor.get_seek_metrics()
    print(json.dumps(m, ensure_ascii=False, indent=2))


def cmd_interactive(args):
    print("=== 交互式配置 ===")
    edition = input(f"权益等级 {list(payload.EDITIONS.keys())} [{args.edition}]: ") or args.edition
    code = input(f"授权码 [{args.license_code}]: ") or args.license_code
    name = input(f"许可证名称 [{args.name}]: ") or args.name
    vf = input(f"生效时间(ms, 0=1970) [{args.valid_from}]: ") or str(args.valid_from)
    vt = input(f"截至时间(ms, 默认2100) [{args.valid_to}]: ") or str(args.valid_to)
    print(f"\n确认配置:")
    print(f"  等级: {edition}")
    print(f"  授权码: {code}")
    print(f"  名称: {name}")
    print(f"  生效: {vf}")
    print(f"  截至: {vt}")
    c = input("执行破解? [y/N]: ")
    if c.lower() == 'y':
        ok, steps = manager.apply_license(
            edition=edition, license_code=code, name=name,
            valid_from=int(vf), valid_to=int(vt)
        )
        for st in steps:
            print(f"  {st}")
        return 0 if ok else 1
    print("已取消")
    return 0


def main():
    ap = argparse.ArgumentParser(prog='seek-license-tool', description='素材库 Seek 许可证工具')
    sub = ap.add_subparsers(dest='cmd')

    p_status = sub.add_parser('status', help='查看状态')
    p_status.add_argument('--json', action='store_true', help='JSON 输出')

    p_apply = sub.add_parser('apply', help='应用破解')
    p_apply.add_argument('--edition', default='enterprise_ultimate', choices=list(payload.EDITIONS.keys()))
    p_apply.add_argument('--license-code', default='L-ENTERPRISE')
    p_apply.add_argument('--name', default='飞牛素材库企业旗舰版')
    p_apply.add_argument('--valid-from', type=int, default=0)
    p_apply.add_argument('--valid-to', type=int, default=payload.VALID_TO_SAFE)

    sub.add_parser('remove', help='移除破解')

    p_editions = sub.add_parser('editions', help='列出权益等级')

    p_monitor = sub.add_parser('monitor', help='实时资源监控')

    p_inter = sub.add_parser('config', help='交互式配置')
    p_inter.add_argument('--edition', default='enterprise_ultimate')
    p_inter.add_argument('--license-code', default='L-ENTERPRISE')
    p_inter.add_argument('--name', default='飞牛素材库企业旗舰版')
    p_inter.add_argument('--valid-from', type=int, default=0)
    p_inter.add_argument('--valid-to', type=int, default=payload.VALID_TO_SAFE)

    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        return 1
    if args.cmd == 'status':
        cmd_status(args)
    elif args.cmd == 'apply':
        return cmd_apply(args)
    elif args.cmd == 'remove':
        return cmd_remove(args)
    elif args.cmd == 'editions':
        cmd_editions(args)
    elif args.cmd == 'monitor':
        cmd_monitor(args)
    elif args.cmd == 'config':
        return cmd_interactive(args)
    return 0


if __name__ == '__main__':
    sys.exit(main())

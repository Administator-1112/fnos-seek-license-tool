#!/usr/bin/env python3
"""
manager.py - Seek 许可证管理协调模块
整合 patcher / payload / db / preserve，提供 apply/remove/status。
"""
import os
import time

import pclntab
import patcher
import payload
import db

TRIM_BIN = "/usr/trim/bin/trim_license"
BACKUP_DIR = "backup"


def _backup_path():
    """应用数据目录下的备份目录"""
    env_dir = os.environ.get('TRIM_PKGVAR', '')
    if env_dir:
        return os.path.join(env_dir, BACKUP_DIR)
    # 默认: 项目根/var/backup (manager.py 在 app/bin/core/，向上3级到项目根)
    project_root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
    return os.path.join(project_root, 'var', BACKUP_DIR)


def get_status():
    """获取完整状态"""
    status = {
        'time': time.strftime('%Y-%m-%d %H:%M:%S'),
        'binary': {
            'patched': False,
            'path': TRIM_BIN,
            'md5': None,
        },
        'license': None,
        'official_backup_exists': False,
        'trim_license_running': False,
    }
    # 二进制状态
    try:
        status['binary']['md5'] = patcher.md5_file(TRIM_BIN)
        status['binary']['patched'] = patcher.is_patched(TRIM_BIN)
    except Exception:
        pass
    # 许可证
    try:
        lic = db.get_license()
        if lic:
            info = {
                'license_code': lic['license_code'],
                'name': lic['name'],
                'tag': lic['tag'],
                'status': lic['status'],
                'valid_from': lic['valid_from'],
                'valid_to': lic['valid_to'],
                'period': lic['period'],
            }
            try:
                p = payload.parse_payload(lic['payload'])
                info['edition'] = p['feature']['edition']
                info['payload_valid_to'] = p['validTo']
                info['payload_license_code'] = p['licenseCode']
            except Exception:
                pass
            status['license'] = info
    except Exception:
        pass
    # 官方备份
    bdir = _backup_path()
    try:
        if os.path.isdir(bdir):
            files = [f for f in os.listdir(bdir) if f.startswith('official_')]
            status['official_backup_exists'] = len(files) > 0
    except Exception:
        pass
    # 服务
    try:
        r = os.popen("pgrep -f '/usr/trim/bin/trim_license'").read().strip()
        status['trim_license_running'] = bool(r)
    except Exception:
        pass
    return status


def apply_license(edition='enterprise_ultimate', license_code='L-ENTERPRISE',
                  name='飞牛素材库企业旗舰版', valid_from=0,
                  valid_to=payload.VALID_TO_SAFE,
                  enterprise_id='ENT-LOCAL', group_key='seek_app',
                  product_id=9, sku_id=14, salt='VK9GHEdQo3'):
    """执行破解：patch 二进制 + 留存官方 + 写库"""
    steps = []
    try:
        # 1. 留存官方许可证
        steps.append('留存官方许可证...')
        bdir = _backup_path()
        os.makedirs(bdir, exist_ok=True)
        backed = db.backup_official_license(bdir)
        steps.append(f'  已留存 {len(backed)} 个备份文件')

        # 1.5 停止 trim_license（避免 Text file busy）
        steps.append('停止 trim_license 服务...')
        os.system('systemctl stop trim_license')
        time.sleep(2)
        steps.append('  已停止')

        # 2. patch 二进制
        steps.append('patch trim_license 二进制（跳过云端检查）...')
        bin_backup = os.path.join(bdir, 'trim_license.bak.pre_patch')
        ok, calls, err = patcher.patch_binary(TRIM_BIN, bin_backup)
        if not ok:
            raise Exception(f"patch 失败: {err}")
        steps.append(f'  已 patch {len(calls)} 个调用点')

        # 3. 构造 payload
        steps.append('构造 license payload（AES 加密）...')
        payload_hex, payload_json = payload.build_payload(
            edition=edition, license_code=license_code,
            valid_from=valid_from, valid_to=valid_to,
            enterprise_id=enterprise_id, group_key=group_key,
            product_id=product_id, sku_id=sku_id, salt=salt
        )
        steps.append(f'  edition={edition} validFrom={valid_from} validTo={valid_to}')

        # 4. 写入数据库
        steps.append('写入数据库 license 表...')
        db.write_license(
            payload_hex=payload_hex,
            sign='L' * 128,
            license_code=license_code,
            name=name,
            tag='Enterprise',
            valid_from=valid_from,
            valid_to=valid_to,
            period=0,
            group_key=group_key, product_id=product_id, sku_id=sku_id, salt=salt,
            status=1
        )
        steps.append('  已写入')

        # 5. 重启 trim_license 让变更生效
        steps.append('重启 trim_license 服务...')
        os.system('systemctl restart trim_license')
        time.sleep(3)
        steps.append('  已重启')

        steps.append('破解完成')
        return True, steps
    except Exception as e:
        steps.append(f'错误: {e}')
        return False, steps


def remove_license():
    """移除破解：恢复二进制 + 恢复官方许可证"""
    steps = []
    try:
        bdir = _backup_path()

        # 0. 停止 trim_license（避免 Text file busy）
        steps.append('停止 trim_license 服务...')
        os.system('systemctl stop trim_license')
        time.sleep(2)
        steps.append('  已停止')

        # 1. 恢复二进制
        steps.append('恢复 trim_license 二进制...')
        bin_backup = os.path.join(bdir, 'trim_license.bak.pre_patch')
        if os.path.exists(bin_backup):
            patcher.restore_binary(TRIM_BIN, bin_backup)
            steps.append('  已恢复原始二进制')
        else:
            steps.append('  未找到二进制备份，跳过')

        # 2. 从官方备份恢复许可证
        steps.append('恢复官方许可证...')
        restored = False
        if os.path.isdir(bdir):
            files = sorted([f for f in os.listdir(bdir) if f.startswith('official_license_')])
            if files:
                newest = os.path.join(bdir, files[-1])
                db.restore_official_license(newest)
                steps.append(f'  已从 {files[-1]} 恢复')
                restored = True
        if not restored:
            steps.append('  未找到官方备份，重置为默认 trial...')
            db.set_status(3)
        else:
            db.set_status(1)

        # 3. 重启
        steps.append('重启 trim_license...')
        os.system('systemctl start trim_license')
        time.sleep(3)
        steps.append('  已重启')

        steps.append('移除完成')
        return True, steps
    except Exception as e:
        steps.append(f'错误: {e}')
        return False, steps


if __name__ == '__main__':
    import json
    s = get_status()
    print(json.dumps(s, ensure_ascii=False, indent=2))

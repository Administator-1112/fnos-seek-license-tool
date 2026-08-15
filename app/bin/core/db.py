#!/usr/bin/env python3
"""
db.py - trim_license 数据库操作 + 官方许可证留存

数据库：trim_license_admin@/var/run/postgresql/trim_license
表：license (id, license_code, name, type, product_id, sku_id, group_key,
           salt, sign, payload, valid_from, valid_to, period, status,
           created_at, updated_at, sku_name, tag, expire_soon_notify)
"""
import json
import os
import subprocess
import time

import payload

DB_HOST = "/var/run/postgresql"
DB_USER = "trim_license_admin"
DB_PASS = "5NiZskHRrv6FZqijDgXm"
DB_NAME = "trim_license"


class DbError(Exception):
    pass


def _psql(sql):
    """执行 psql 查询，返回 (stdout, stderr)"""
    cmd = [
        'psql', '-h', DB_HOST, '-U', DB_USER, '-d', DB_NAME,
        '-t', '-A', '-c', sql
    ]
    env = dict(os.environ, PGPASSWORD=DB_PASS)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15, env=env)
        if r.returncode != 0:
            raise DbError(f"psql 失败: {r.stderr.strip()}")
        return r.stdout.strip()
    except subprocess.TimeoutExpired:
        raise DbError("psql 超时")
    except FileNotFoundError:
        raise DbError("psql 不可用")


def get_license():
    """读取当前 license 记录，返回 dict 或 None"""
    sql = "SELECT id, license_code, name, type, product_id, sku_id, group_key, salt, sign, payload, valid_from, valid_to, period, status, tag, expire_soon_notify FROM license ORDER BY id LIMIT 1;"
    try:
        out = _psql(sql)
    except DbError:
        return None
    if not out:
        return None
    parts = out.split('|')
    if len(parts) < 16:
        return None
    return {
        'id': int(parts[0]),
        'license_code': parts[1],
        'name': parts[2],
        'type': parts[3],
        'product_id': int(parts[4]) if parts[4] else 0,
        'sku_id': int(parts[5]) if parts[5] else 0,
        'group_key': parts[6],
        'salt': parts[7],
        'sign': parts[8],
        'payload': parts[9],
        'valid_from': int(parts[10]) if parts[10] else 0,
        'valid_to': int(parts[11]) if parts[11] else 0,
        'period': int(parts[12]) if parts[12] else 0,
        'status': int(parts[13]) if parts[13] else 0,
        'tag': parts[14],
        'expire_soon_notify': parts[15],
    }


def backup_official_license(backup_dir):
    """
    留存官方许可证到备份目录（破解前调用）。
    备份内容：
      1. license 表完整记录 (JSON)
      2. payload 解密明文 (JSON)
    返回备份文件路径列表
    """
    os.makedirs(backup_dir, exist_ok=True)
    ts = time.strftime('%Y%m%d_%H%M%S')
    lic = get_license()
    files = []
    if not lic:
        return files

    # 1. 完整记录备份
    rec_path = os.path.join(backup_dir, f'official_license_{ts}.json')
    with open(rec_path, 'w') as f:
        json.dump(lic, f, ensure_ascii=False, indent=2)
    files.append(rec_path)

    # 2. payload 明文备份
    try:
        plain = payload.decrypt_payload(lic['payload'])
        plain_path = os.path.join(backup_dir, f'official_payload_{ts}.json')
        with open(plain_path, 'w') as f:
            f.write(plain)
        files.append(plain_path)
    except Exception:
        pass

    return files


def write_license(payload_hex, sign, license_code, name, tag,
                  valid_from, valid_to, period=0,
                  group_key='seek_app', product_id=9, sku_id=14,
                  salt='VK9GHEdQo3', status=1):
    """写入破解后的 license（若已有记录则 UPDATE，否则 INSERT）"""
    lic = get_license()
    sign_sql = sign if sign else 'x' * 128
    if lic:
        sql = f"""UPDATE license SET
            license_code='{license_code}',
            name='{name}',
            tag='{tag}',
            status={int(status)},
            valid_from={int(valid_from)},
            valid_to={int(valid_to)},
            period={int(period)},
            payload='{payload_hex}',
            sign='{sign_sql}',
            group_key='{group_key}',
            product_id={int(product_id)},
            sku_id={int(sku_id)},
            salt='{salt}'
            WHERE id={lic['id']};"""
    else:
        sql = f"""INSERT INTO license
            (license_code, name, type, product_id, sku_id, group_key, salt, sign, payload,
             valid_from, valid_to, period, status, tag, expire_soon_notify)
            VALUES ('{license_code}', '{name}', 'Soft', {int(product_id)}, {int(sku_id)},
                    '{group_key}', '{salt}', '{sign_sql}', '{payload_hex}',
                    {int(valid_from)}, {int(valid_to)}, {int(period)}, {int(status)},
                    '{tag}', 0);"""
    _psql(sql)
    return True


def restore_official_license(backup_file):
    """
    从备份文件恢复官方许可证。
    backup_file: backup_official_license 生成的 JSON 文件
    """
    if not os.path.exists(backup_file):
        raise DbError(f"备份文件不存在: {backup_file}")
    with open(backup_file) as f:
        lic = json.load(f)
    _psql(f"""UPDATE license SET
        license_code='{lic['license_code']}',
        name='{lic['name']}',
        type='{lic.get('type','Soft')}',
        tag='{lic['tag']}',
        status={lic['status']},
        valid_from={lic['valid_from']},
        valid_to={lic['valid_to']},
        period={lic['period']},
        payload='{lic['payload']}',
        sign='{lic['sign']}',
        group_key='{lic['group_key']}',
        product_id={lic['product_id']},
        sku_id={lic['sku_id']},
        salt='{lic['salt']}'
        WHERE id={lic['id']};""")
    return True


def set_status(status):
    """设置 license 状态（1=有效，3=无效）"""
    _psql(f"UPDATE license SET status={int(status)};")
    return True


if __name__ == '__main__':
    lic = get_license()
    if lic:
        print(f"当前 license: {lic['license_code']} | tag={lic['tag']} | status={lic['status']}")
        try:
            p = payload.parse_payload(lic['payload'])
            print(f"  edition={p['feature']['edition']} validTo={p['validTo']}")
        except Exception as e:
            print(f"  payload 解析失败: {e}")
    else:
        print("无 license 记录")

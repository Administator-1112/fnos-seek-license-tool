#!/usr/bin/env python3
"""
payload.py - Seek license payload 构造与 AES 加解密

数据库 license 表的 payload 字段是 AES-256-CBC 加密的 JSON：
  {"enterpriseID","groupKey","productID","skuID","licenseCode",
   "validFrom","validTo","salt","period","feature":{"edition","period"}}

加密密钥（已逆向）："2NGvk4D5VH4pu72YDiPJmeo3ee4TLervrb"[:32]
IV 前缀模式：密文前 16 字节是 IV，剩余是 AES-CBC 密文
"""
import json
import os
import subprocess

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding as sym_padding
    HAVE_CRYPTO = True
except ImportError:
    HAVE_CRYPTO = False

AES_KEY = b"2NGvk4D5VH4pu72YDiPJmeo3ee4TLervrb"[:32]

# 权益等级定义
EDITIONS = {
    "free":                {"userLimit": 1,   "projectLimit": 1,  "label": "免费版"},
    "trial":               {"userLimit": 100, "projectLimit": -1, "label": "体验版"},
    "team":                {"userLimit": 5,   "projectLimit": -1, "label": "团队版"},
    "enterprise":          {"userLimit": 100, "projectLimit": -1, "label": "企业版"},
    "enterprise_ultimate": {"userLimit": -1,  "projectLimit": -1, "label": "企业旗舰版"},
}

# 时间边界（毫秒）
VALID_FROM_MIN = 0                     # 1970-01-01
VALID_TO_SAFE = 4102444800000          # 2100-01-01 (安全值)
VALID_TO_MAX = 8639999999999999        # JS Date 上限附近


class PayloadError(Exception):
    pass


def encrypt_payload(plaintext: str) -> str:
    """AES-256-CBC 加密，IV 前缀模式，返回 hex"""
    if not HAVE_CRYPTO:
        raise PayloadError("cryptography 库不可用")
    plain = plaintext.encode('utf-8')
    padder = sym_padding.PKCS7(128).padder()
    padded = padder.update(plain) + padder.finalize()
    iv = os.urandom(16)
    c = Cipher(algorithms.AES(AES_KEY), modes.CBC(iv)).encryptor()
    ct = c.update(padded) + c.finalize()
    return (iv + ct).hex()


def decrypt_payload(payload_hex: str) -> str:
    """AES-256-CBC 解密，IV 前缀模式，返回明文 JSON"""
    if not HAVE_CRYPTO:
        raise PayloadError("cryptography 库不可用")
    try:
        data = bytes.fromhex(payload_hex)
    except ValueError:
        raise PayloadError("payload 不是有效 hex")
    if len(data) < 32:
        raise PayloadError("payload 过短")
    iv = data[:16]
    ct = data[16:]
    d = Cipher(algorithms.AES(AES_KEY), modes.CBC(iv)).decryptor()
    out = d.update(ct) + d.finalize()
    # 去 PKCS7 padding
    pad = out[-1]
    if 1 <= pad <= 16 and all(b == pad for b in out[-pad:]):
        out = out[:-pad]
    return out.decode('utf-8', errors='replace')


def build_payload(edition="enterprise_ultimate",
                  license_code="L-ENTERPRISE",
                  valid_from=0,
                  valid_to=VALID_TO_SAFE,
                  enterprise_id="ENT-LOCAL",
                  group_key="seek_app",
                  product_id=9,
                  sku_id=14,
                  salt="VK9GHEdQo3"):
    """构造 license payload JSON 并加密，返回 (payload_hex, payload_json)"""
    if edition not in EDITIONS:
        raise PayloadError(f"未知权益等级: {edition}，可选: {list(EDITIONS.keys())}")
    payload = {
        "enterpriseID": enterprise_id,
        "groupKey": group_key,
        "productID": product_id,
        "skuID": sku_id,
        "licenseCode": license_code,
        "validFrom": int(valid_from),
        "validTo": int(valid_to),
        "salt": salt,
        "period": 0,
        "feature": {"edition": edition, "period": 0}
    }
    plain = json.dumps(payload, separators=(',', ':'))
    payload_hex = encrypt_payload(plain)
    return payload_hex, payload


def parse_payload(payload_hex):
    """解密并解析 payload 为 dict"""
    try:
        plain = decrypt_payload(payload_hex)
        return json.loads(plain)
    except Exception as e:
        raise PayloadError(f"payload 解析失败: {e}")


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'test':
        # 自测
        hex_p, js = build_payload()
        print(f"加密 payload: {len(hex_p)} hex")
        back = parse_payload(hex_p)
        print(f"解密还原: edition={back['feature']['edition']} code={back['licenseCode']}")
        print(f"测试通过" if back == js else "测试失败")

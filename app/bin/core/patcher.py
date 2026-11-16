#!/usr/bin/env python3
"""
patcher.py - trim_license 二进制 patch 引擎
定位 softLicenseCheckInit 中调用 CheckLicense 的 call 指令，改为 NOP，
从而跳过云端检查，使伪造 license 不被标记为无效。
多版本自适应：pclntab 解析 + 字节模式兜底。
"""
import bisect
import hashlib
import os
import shutil
import struct
import sys

import pclntab

TRIM_LICENSE_BIN = "/usr/trim/bin/trim_license"
NOP = b"\x90\x90\x90\x90\x90"

VERIFY_FUNCS = (
    'app/core/pkg/trimlic.LicenseVerify',
    'app/core/service.verifySignedLicense',
    'app/core/service.hardwareBindingMatches',
)


class PatchError(Exception):
    pass


def md5_file(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def backup_binary(bin_path, backup_path):
    """备份二进制（若备份不存在或内容不同）"""
    if os.path.exists(backup_path):
        if md5_file(backup_path) == md5_file(bin_path):
            return backup_path  # 备份已是最新
    shutil.copy2(bin_path, backup_path)
    return backup_path


def is_verify_bypassed(bin_path):
    """检查签名/硬件校验是否已被绕过"""
    try:
        funcs = pclntab.parse_pclntab(bin_path)
        items = sorted(funcs.items(), key=lambda kv: kv[1])
        addrs = [va for _, va in items]
        data = open(bin_path, 'rb').read()
        diff = 0x400000
        for name in VERIFY_FUNCS:
            va = funcs.get(name)
            if va is None:
                continue
            i = bisect.bisect_right(addrs, va)
            end = addrs[i] if i < len(addrs) else va + 0x20000
            for off in range(va - diff, min(end - diff, len(data) - 11)):
                if (data[off] == 0xB0 and data[off + 1] == 0x01
                        and data[off + 2] == 0x48 and data[off + 3] == 0x81
                        and data[off + 4] == 0xC4
                        and data[off + 9] == 0x5D and data[off + 10] == 0xC3):
                    return True
    except Exception:
        pass
    return False


def is_patched(bin_path):
    """检查是否已 patch（call 指令是否已是 NOP）"""
    try:
        funcs = pclntab.parse_pclntab(bin_path)
        slci = funcs.get('app/core/task.softLicenseCheckInit')
        cl = funcs.get('app/core/service.(*LicenseService).CheckLicense')
        if not slci or not cl:
            return False
        calls = pclntab.find_call_in_function(bin_path, slci, cl)
        if not calls:
            # 找不到 call → 可能已 patch 或结构变化
            # 检查 NOP 特征
            data = open(bin_path, 'rb').read()
            diff = 0x400000
            for va in [slci + 0x15, slci + 0x58]:  # 典型 call 位置
                off = va - diff
                if 0 <= off < len(data) - 5:
                    if data[off:off+5] == NOP:
                        return is_verify_bypassed(bin_path)
            return False
        return False
    except Exception:
        return False


def patch_binary(bin_path, backup_path=None):
    """
    patch trim_license：softLicenseCheckInit 中 call CheckLicense → NOP
    返回 (是否成功, patch点列表, 错误信息)
    """
    if not os.path.exists(bin_path):
        raise PatchError(f"二进制不存在: {bin_path}")

    # 备份
    if backup_path:
        backup_binary(bin_path, backup_path)

    # 解析定位
    funcs = pclntab.parse_pclntab(bin_path)
    slci = funcs.get('app/core/task.softLicenseCheckInit')
    cl = funcs.get('app/core/service.(*LicenseService).CheckLicense')
    if not slci or not cl:
        # 兜底：字节模式匹配
        return _patch_by_pattern(bin_path, backup_path)

    # 找 call 指令
    calls = pclntab.find_call_in_function(bin_path, slci, cl)
    if not calls:
        # 已 patch 或结构不同，尝试字节模式
        if is_patched(bin_path):
            return True, ["already_patched"], None
        return _patch_by_pattern(bin_path, backup_path)

    # 写 NOP
    data = bytearray(open(bin_path, 'rb').read())
    diff = 0x400000
    for va in calls:
        off = va - diff
        if 0 <= off < len(data) - 5:
            if data[off:off+5] != NOP:
                data[off:off+5] = NOP

    open(bin_path, 'wb').write(bytes(data))

    # 验证
    new_data = open(bin_path, 'rb').read()
    patched_offs = [va - diff for va in calls]
    for off in patched_offs:
        if new_data[off:off+5] != NOP:
            raise PatchError(f"patch 验证失败 @ 0x{off:x}")
    return True, [hex(va) for va in calls], None


def patch_verify_bypass(bin_path):
    """
    绕过 Ed25519 签名与硬件绑定校验。
    在 LicenseVerify / verifySignedLicense / hardwareBindingMatches 内，
    把「xor eax,eax + 函数尾声」的失败返回改写为「mov al,1 + 函数尾声」，
    使验证恒为成功。伪造 sign 无法通过官方私钥验签，故必须绕过此层。
    返回被改写的 VA 列表。
    """
    if not os.path.exists(bin_path):
        raise PatchError(f"二进制不存在: {bin_path}")
    funcs = pclntab.parse_pclntab(bin_path)
    items = sorted(funcs.items(), key=lambda kv: kv[1])
    addrs = [va for _, va in items]
    data = bytearray(open(bin_path, 'rb').read())
    diff = 0x400000
    patched = []

    for name in VERIFY_FUNCS:
        va = funcs.get(name)
        if va is None:
            continue
        i = bisect.bisect_right(addrs, va)
        end = addrs[i] if i < len(addrs) else va + 0x20000
        for off in range(va - diff, min(end - diff, len(data) - 11)):
            if (data[off] == 0x31 and data[off + 1] == 0xC0
                    and data[off + 2] == 0x48 and data[off + 3] == 0x81
                    and data[off + 4] == 0xC4
                    and data[off + 9] == 0x5D and data[off + 10] == 0xC3):
                data[off] = 0xB0
                data[off + 1] = 0x01
                patched.append(off + diff)

    if patched:
        open(bin_path, 'wb').write(bytes(data))
    return patched


def _patch_by_pattern(bin_path, backup_path):
    """
    兜底：通过字节模式匹配定位 softLicenseCheckInit 中的 call CheckLicense。
    模式：在函数入口附近搜索 E8 相对调用，目标为 CheckLicense。
    """
    raise PatchError("pclntab 解析失败且字节模式匹配未实现（二进制结构异常）")


def restore_binary(bin_path, backup_path):
    """从备份恢复二进制"""
    if not os.path.exists(backup_path):
        raise PatchError(f"备份不存在: {backup_path}")
    shutil.copy2(backup_path, bin_path)
    return True


if __name__ == '__main__':
    test = sys.argv[1] if len(sys.argv) > 1 else '/usr/trim/bin/trim_license.bak.pre_patch'
    print(f"测试检测 patch 状态: {test}")
    print(f"是否已 patch: {is_patched(test)}")

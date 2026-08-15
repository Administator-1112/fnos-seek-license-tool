#!/usr/bin/env python3
"""
pclntab.py - Go pclntab 符号表解析器（多版本自适应核心）
用于从 trim_license 二进制中动态定位函数地址，适应不同版本。
"""
import struct
import subprocess
import re


class PclntabError(Exception):
    pass


def find_gopclntab(binary_path):
    """定位 .gopclntab 段的 VMA 和文件偏移"""
    try:
        out = subprocess.run(
            ['readelf', '-S', binary_path],
            capture_output=True, text=True, timeout=10
        ).stdout
        for line in out.split('\n'):
            if '.gopclntab' in line:
                parts = line.split()
                # 格式: [21] .gopclntab PROGBITS 000000000145e0a0 0105e0a0 ...
                # 找到 4 个 hex 值：VMA, 文件偏移, 大小, 对齐
                hex_vals = [p for p in parts if re.match(r'^[0-9a-fA-F]+$', p)]
                if len(hex_vals) >= 2:
                    vma = int(hex_vals[0], 16)
                    file_off = int(hex_vals[1], 16)
                    return vma, file_off
        raise PclntabError("未找到 .gopclntab 段")
    except subprocess.TimeoutExpired:
        raise PclntabError("readelf 超时")
    except FileNotFoundError:
        raise PclntabError("readelf 不可用")


def parse_pclntab(binary_path):
    """
    解析 Go pclntab，返回 {函数完整名: 函数入口VA}
    支持 Go 1.20 - 1.24
    """
    data = open(binary_path, 'rb').read()
    vma, pc_off = find_gopclntab(binary_path)

    if pc_off + 72 > len(data):
        raise PclntabError("pclntab 段过小")

    # 解析 header
    hdr = data[pc_off:pc_off + 72]
    magic = struct.unpack_from('<I', hdr, 0)[0]
    if magic not in (0xfffffff0, 0xfffffff1, 0xfffffff2, 0xfffffff3, 0xfffffff4, 0xfffffff5):
        raise PclntabError(f"未知 pclntab magic: 0x{magic:x}")

    nfunc = struct.unpack_from('<q', hdr, 8)[0]
    text_start = struct.unpack_from('<Q', hdr, 24)[0]
    funcname_offset = struct.unpack_from('<Q', hdr, 32)[0]
    pcln_offset = struct.unpack_from('<Q', hdr, 64)[0]

    if nfunc <= 0 or nfunc > 500000:
        raise PclntabError(f"异常 nfunc: {nfunc}")

    functab_off = pc_off + pcln_offset
    funcname_off = pc_off + funcname_offset

    result = {}
    # 遍历 functab（交错模式: {entryoff, funcoff} 每8字节）
    for i in range(nfunc):
        pos = functab_off + i * 8
        if pos + 8 > len(data):
            break
        entryoff, funcoff = struct.unpack_from('<II', data, pos)
        if funcoff == 0:
            continue
        _func_off = functab_off + funcoff
        if _func_off + 8 > len(data):
            continue
        _entry, _nameoff = struct.unpack_from('<II', data, _func_off)
        name_abs = funcname_off + _nameoff
        if name_abs >= len(data):
            continue
        end = data.find(b'\x00', name_abs)
        if end == -1:
            continue
        try:
            name = data[name_abs:end].decode('utf-8')
        except UnicodeDecodeError:
            continue
        va = text_start + entryoff
        result[name] = va

    return result


def locate_function(binary_path, func_names):
    """
    定位目标函数。func_names 为候选名列表（兼容不同版本命名）。
    返回 (函数名, VA) 或 (None, None)
    """
    funcs = parse_pclntab(binary_path)
    for name in func_names:
        if name in funcs:
            return name, funcs[name]
    # 模糊匹配：函数名结尾匹配
    for name, va in funcs.items():
        for target in func_names:
            if target in name or name.endswith(target.split('.')[-1]):
                return name, va
    return None, None


def find_call_targets(binary_path, func_va, target_va):
    """
    在指定函数（func_va）的反汇编中查找所有 call target_va 的位置。
    返回 [call指令的VA, ...]
    """
    data = open(binary_path, 'rb').read()
    # text 段: VMA 0x4035c0 文件偏移 0x35c0 (差 0x400000)
    diff = 0x400000
    func_off = func_va - diff
    # 反汇编函数（限制范围，假设函数 < 64KB）
    try:
        out = subprocess.run(
            ['objdump', '-d', '--start-address=0x%x' % func_va,
             '--stop-address=0x%x' % (func_va + 0x10000), binary_path],
            capture_output=True, text=True, timeout=15
        ).stdout
    except Exception:
        return []

    calls = []
    # 解析 objdump 输出的 call 指令
    for line in out.split('\n'):
        m = re.match(r'\s*([0-9a-f]+):\s+([0-9a-f ]+)\s+call\s+([0-9a-f]+)', line)
        if m:
            addr = int(m.group(1), 16)
            if addr == target_va or (addr & 0xffffffff) == target_va:
                calls.append(int(m.group(1), 16))
    return calls


def find_call_in_function(binary_path, func_va, target_va):
    """在函数中找 call target_va 的指令起始 VA（通过 E8 相对调用直接扫描）"""
    data = open(binary_path, 'rb').read()
    diff = 0x400000
    func_off = func_va - diff
    calls = []
    # 扫描函数代码区（限制 32KB）
    for i in range(func_off, func_off + 0x8000):
        if i + 5 > len(data):
            break
        if data[i] == 0xE8:  # call rel32
            rel = struct.unpack_from('<i', data, i + 1)[0]
            call_site_va = i + diff + 5
            target = call_site_va + rel
            if target == target_va:
                calls.append(i + diff)  # 返回 call 指令起始 VA
    return calls


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("用法: pclntab.py <binary> [函数名]")
        sys.exit(1)
    bin_path = sys.argv[1]
    funcs = parse_pclntab(bin_path)
    if len(sys.argv) > 2:
        name, va = locate_function(bin_path, [sys.argv[2]])
        if va:
            print(f"{name}: 0x{va:x}")
        else:
            print("未找到")
    else:
        print(f"解析到 {len(funcs)} 个函数")
        # 打印关键函数
        for n, v in funcs.items():
            if 'softLicense' in n or 'CheckLicense' in n or 'checkLicense' in n:
                print(f"  0x{v:x}  {n}")

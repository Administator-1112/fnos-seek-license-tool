#!/usr/bin/env python3
"""
monitor.py - seek 应用资源占用与数据库统计采集
"""
import os
import subprocess
import time


def find_seek_pid():
    """查找 seek 主进程 PID"""
    try:
        r = subprocess.run(
            ['pgrep', '-f', '/usr/local/apps/@appcenter/trim.seek/trim.seek'],
            capture_output=True, text=True, timeout=5
        )
        pids = [p for p in r.stdout.strip().split('\n') if p]
        # 排除 postgres 等（返回第一个非 postgres 进程）
        for pid in pids:
            try:
                comm = open(f'/proc/{pid}/comm').read().strip()
                if 'trim.seek' in comm or 'trim' in comm:
                    return int(pid)
            except Exception:
                continue
        return int(pids[0]) if pids else None
    except Exception:
        return None


def read_proc_stat(pid):
    """读取 /proc/PID/stat，返回 dict"""
    try:
        with open(f'/proc/{pid}/stat') as f:
            parts = f.read().split()
        # comm 可能含空格，解析: pid (comm) state ppid ...
        comm_end = -1
        for i, p in enumerate(parts):
            if p.endswith(')'):
                comm_end = i
                break
        if comm_end == -1:
            return None
        rest = parts[comm_end+1:]
        # 索引: state=0 ppid=1 ... utime=11 stime=12 ... starttime=19 rss=21
        def g(i):
            try:
                return int(rest[i])
            except Exception:
                return 0
        return {
            'state': rest[0] if rest else '?',
            'utime': g(11),
            'stime': g(12),
            'starttime': g(19),
            'rss_pages': g(21),
            'threads': g(17) if len(rest) > 17 else 0,
        }
    except Exception:
        return None


def read_proc_status(pid):
    """读取 /proc/PID/status 关键字段"""
    info = {}
    try:
        with open(f'/proc/{pid}/status') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    info['vmrss_kb'] = int(line.split()[1])
                elif line.startswith('Threads:'):
                    info['threads'] = int(line.split()[1])
                elif line.startswith('Name:'):
                    info['name'] = line.split(':', 1)[1].strip()
    except Exception:
        pass
    return info


def get_cpu_percent(pid, interval=1.0):
    """计算进程 CPU 使用率（% of one core）"""
    s1 = read_proc_stat(pid)
    if not s1:
        return 0
    t1 = time.time()
    time.sleep(interval)
    s2 = read_proc_stat(pid)
    if not s2:
        return 0
    t2 = time.time()
    cpu_time1 = s1['utime'] + s1['stime']
    cpu_time2 = s2['utime'] + s2['stime']
    hz = os.sysconf('SC_CLK_TCK')
    elapsed = t2 - t1
    if elapsed <= 0:
        return 0
    return round((cpu_time2 - cpu_time1) / hz / elapsed * 100, 1)


def get_gpu_info():
    """读取 GPU 信息（nvidia-smi 或忽略）"""
    gpus = []
    try:
        r = subprocess.run(
            ['nvidia-smi', '--query-gpu=index,name,utilization.gpu,memory.used,memory.total',
             '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=5
        )
        for line in r.stdout.strip().split('\n'):
            if line:
                parts = [p.strip() for p in line.split(',')]
                if len(parts) >= 5:
                    gpus.append({
                        'index': parts[0],
                        'name': parts[1],
                        'util': parts[2],
                        'mem_used': parts[3],
                        'mem_total': parts[4],
                    })
    except Exception:
        pass
    return gpus


def _seek_db_query(sql):
    """查询 seek 自己的数据库"""
    cmd = ['psql', '-h', '/usr/local/apps/@appdata/trim.seek/pgsql_data/sock',
           '-U', 'postgres', '-d', 'postgres', '-t', '-A', '-c', sql]
    env = dict(os.environ, PGPASSWORD='123456')
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10, env=env)
        return r.stdout.strip()
    except Exception:
        return None


def get_db_stats():
    """采集数据库统计（seek 用户数据 + trim_license）"""
    import db
    stats = {}
    # seek 自己的数据库
    for key, sql in [
        ('seek_users', 'SELECT count(*) FROM "user";'),
        ('seek_projects', 'SELECT count(*) FROM project;'),
        ('seek_assets', 'SELECT count(*) FROM fs_entry;'),
    ]:
        try:
            out = _seek_db_query(sql)
            stats[key] = int(out) if out else 0
        except Exception:
            stats[key] = None
    # trim_license 数据库
    try:
        out = db._psql("SELECT count(*) FROM license;")
        stats['license_records'] = int(out) if out else 0
    except Exception:
        stats['license_records'] = None
    return stats


def get_seek_metrics(pid=None):
    """采集 seek 实时资源（不阻塞，CPU 用最近 0.5s 采样）"""
    if pid is None:
        pid = find_seek_pid()
    if not pid:
        return {'pid': None, 'running': False}

    st = read_proc_stat(pid)
    sts = read_proc_status(pid)
    rss_mb = sts.get('vmrss_kb', 0) / 1024 if 'vmrss_kb' in sts else 0
    threads = sts.get('threads', st.get('threads', 0)) if st else 0

    # CPU：短采样
    cpu = get_cpu_percent(pid, 0.3)

    # 运行时长（基于 starttime 与系统启动时间）
    uptime = 0
    try:
        with open('/proc/uptime') as f:
            sys_uptime = float(f.read().split()[0])
        hz = os.sysconf('SC_CLK_TCK')
        start_ticks = st['starttime'] / hz
        uptime = max(0, sys_uptime - start_ticks)
    except Exception:
        pass

    return {
        'pid': pid,
        'running': True,
        'cpu_percent': cpu,
        'ram_mb': round(rss_mb, 1),
        'threads': threads,
        'uptime_sec': round(uptime),
        'state': st.get('state', '?') if st else '?',
        'gpus': get_gpu_info(),
    }


if __name__ == '__main__':
    import json
    m = get_seek_metrics()
    print("seek 资源:", json.dumps(m, ensure_ascii=False, indent=2))
    print("数据库:", json.dumps(get_db_stats(), ensure_ascii=False))

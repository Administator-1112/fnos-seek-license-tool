#!/usr/bin/env python3
"""
web.py - Seek 许可证工具 Web UI 服务
通过 TCP 端口直连提供 HTTP 服务（默认 17202），不依赖统一网关。
路由:
  GET  /            → 首页（状态概览 + 监控 + 免责声明）
  GET  /how-it-works → 破解原理页
  GET  /operate     → 操作页
  GET  /api/status  → 状态 JSON
  GET  /api/monitor → 实时资源监控 JSON
  POST /api/apply   → 执行破解
  POST /api/remove  → 移除破解
"""
import base64
import json
import os
import re
import socket
import sys
import threading
import traceback
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'core'))

import manager
import monitor
import payload

DISCLAIMER = "本工具仅供学习交流使用，请于下载后 24 小时内删除。使用本工具破解软件许可证可能违反软件许可协议及当地法律法规，由此产生的任何后果由使用者自行承担。请尊重软件开发者的劳动成果，支持正版。本工具不用于任何商业用途，不用于侵犯他人合法权益。"

WEB_PORT = int(os.environ.get('WEB_PORT', '17202'))
BIND_HOST = os.environ.get('BIND_HOST', '0.0.0.0')

CSS = """
:root { --bg:#0f1115; --card:#1a1d24; --border:#2a2e37; --text:#e4e7ec; --dim:#8b93a1; --accent:#4f8cff; --green:#34d399; --red:#f87171; --amber:#fbbf24; }
* { margin:0; padding:0; box-sizing:border-box; }
body { background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; line-height:1.6; }
.topbar { background:var(--card); border-bottom:1px solid var(--border); padding:14px 28px; display:flex; align-items:center; gap:14px; position:sticky; top:0; z-index:10; }
.topbar h1 { font-size:18px; font-weight:600; }
.topbar .badge { font-size:11px; padding:3px 10px; border-radius:20px; background:#1e3a5f; color:#7eb2ff; }
.topbar nav { margin-left:auto; display:flex; gap:6px; }
.topbar nav a { color:var(--dim); text-decoration:none; padding:6px 14px; border-radius:6px; font-size:13px; }
.topbar nav a:hover, .topbar nav a.active { color:var(--text); background:var(--border); }
.container { max-width:1100px; margin:0 auto; padding:24px 28px; }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:16px; }
.card { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:18px; }
.card h3 { font-size:13px; color:var(--dim); text-transform:uppercase; letter-spacing:.5px; margin-bottom:12px; }
.kv { display:flex; justify-content:space-between; padding:7px 0; border-bottom:1px solid #23272f; font-size:13px; }
.kv:last-child { border-bottom:none; }
.kv .k { color:var(--dim); }
.kv .v { font-weight:500; }
.btn { display:inline-block; padding:9px 20px; border-radius:6px; border:none; cursor:pointer; font-size:13px; font-weight:500; text-decoration:none; }
.btn-primary { background:var(--accent); color:#fff; }
.btn-danger { background:#7f1d1d; color:#fca5a5; }
.btn-sm { padding:5px 12px; font-size:12px; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th,td { padding:8px 10px; text-align:left; border-bottom:1px solid #23272f; }
th { color:var(--dim); font-weight:500; }
.alert { padding:12px 16px; border-radius:8px; margin:12px 0; font-size:13px; }
.alert-warn { background:#3a2e12; border:1px solid #6b4e16; color:#fbbf24; }
.mono { font-family:ui-monospace,Consolas,monospace; font-size:12px; }
.disclaimer { margin-top:30px; padding:16px; background:#1a1820; border:1px solid #3a2e2e; border-radius:8px; color:#c9b8b8; font-size:12px; }
.log-box { background:#0a0c10; border:1px solid var(--border); border-radius:8px; padding:14px; max-height:280px; overflow-y:auto; font-family:ui-monospace,Consolas,monospace; font-size:12px; white-space:pre-wrap; }
.log-box .ok { color:var(--green); }
.log-box .err { color:var(--red); }
.step-desc { margin:18px 0; }
.step-desc .step { display:flex; gap:12px; margin-bottom:14px; }
.step-desc .num { width:24px; height:24px; border-radius:50%; background:var(--accent); color:#fff; display:flex; align-items:center; justify-content:center; font-size:12px; flex-shrink:0; }
.step-desc h4 { font-size:14px; margin-bottom:4px; }
.step-desc p { color:var(--dim); font-size:13px; }
form label { display:block; font-size:13px; color:var(--dim); margin:10px 0 4px; }
form input, form select { width:100%; padding:9px 12px; border:1px solid var(--border); border-radius:6px; background:var(--bg); color:var(--text); font-size:13px; }
form .row { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
footer { text-align:center; color:var(--dim); font-size:12px; padding:30px 0; }
.spin { display:inline-block; width:14px; height:14px; border:2px solid var(--border); border-top-color:var(--accent); border-radius:50%; animation:spin 1s linear infinite; vertical-align:middle; }
@keyframes spin { to { transform:rotate(360deg); } }
"""

PAGE_HEAD = """
<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Seek 许可证工具</title><style>{css}</style></head><body>
<div class="topbar"><h1>WARN Seek 许可证工具</h1><span class="badge">仅供学习交流</span>
<nav><a href="/" {h1}>首页</a><a href="/operate" {h2}>操作</a><a href="/how-it-works" {h3}>破解原理</a></nav></div>
<div class="container">
"""

PAGE_FOOT = f"""
<div class="disclaimer">WARN <strong>免责声明</strong>：{DISCLAIMER}</div>
<footer>Seek License Tool · 仅供学习交流</footer>
</div></body></html>
"""


def render_status():
    s = manager.get_status()
    lic = s.get('license') or {}
    patched = s['binary']['patched']
    patch_badge = '<span style="color:var(--green)">已破解</span>' if patched else '<span style="color:var(--dim)">未破解</span>'
    edition_label = payload.EDITIONS.get(lic.get('edition', ''), {}).get('label', lic.get('edition', 'N/A'))
    vt = lic.get('valid_to', 0)
    vt_str = datetime.fromtimestamp(vt/1000).strftime('%Y-%m-%d') if vt else 'N/A'

    MONITOR_JS = """
async function refresh(){
  try {
    const r = await fetch('/api/monitor'); const d = await r.json();
    let gpuHtml = d.gpus && d.gpus.length ? d.gpus.map(g=>`<span class="v">GPU ${g.index} ${g.name} ${g.util}%</span>`).join('<br>') : 'N/A';
    document.getElementById('monitor').innerHTML = `
    <div class="grid" style="margin-top:16px">
      <div class="card"><h3>数据库统计</h3>
        <div class="kv"><span class="k">Seek 用户</span><span class="v">${d.db.seek_users ?? 'N/A'}</span></div>
        <div class="kv"><span class="k">Seek 项目</span><span class="v">${d.db.seek_projects ?? 'N/A'}</span></div>
        <div class="kv"><span class="k">Seek 资产</span><span class="v">${d.db.seek_assets ?? 'N/A'}</span></div>
        <div class="kv"><span class="k">License 记录</span><span class="v">${d.db.license_records ?? 'N/A'}</span></div>
      </div>
      <div class="card"><h3>Seek 实时资源</h3>
        <div class="kv"><span class="k">进程</span><span class="v">${d.seek.pid ? '运行中 (PID '+d.seek.pid+')' : '未运行'}</span></div>
        <div class="kv"><span class="k">CPU</span><span class="v">${d.seek.cpu_percent ?? 0}%</span></div>
        <div class="kv"><span class="k">内存</span><span class="v">${d.seek.ram_mb ?? 0} MB</span></div>
        <div class="kv"><span class="k">线程数</span><span class="v">${d.seek.threads ?? 0}</span></div>
        <div class="kv"><span class="k">GPU</span><span>${gpuHtml}</span></div>
      </div>
    </div>`;
  } catch(e) { document.getElementById('monitor').innerHTML = '<div class="card" style="margin-top:16px">监控加载失败</div>'; }
}
refresh(); setInterval(refresh, 3000);
"""

    html = PAGE_HEAD.format(css=CSS, h1='class="active"', h2='', h3='')
    html += f"""
<h2 style="margin-bottom:16px">系统概览 {patch_badge}</h2>
<div class="grid">
  <div class="card">
    <h3>许可证状态</h3>
    <div class="kv"><span class="k">授权码</span><span class="v mono">{lic.get('license_code','N/A')}</span></div>
    <div class="kv"><span class="k">名称</span><span class="v">{lic.get('name','N/A')}</span></div>
    <div class="kv"><span class="k">权益等级</span><span class="v">{edition_label} ({lic.get('edition','?')})</span></div>
    <div class="kv"><span class="k">状态</span><span class="v">{lic.get('status','?')}</span></div>
    <div class="kv"><span class="k">生效时间</span><span class="v">{vt_str if lic.get('valid_from')==0 else datetime.fromtimestamp(lic.get('valid_from',0)/1000).strftime('%Y-%m-%d')}</span></div>
    <div class="kv"><span class="k">截至时间</span><span class="v">{vt_str}</span></div>
  </div>
  <div class="card">
    <h3>系统信息</h3>
    <div class="kv"><span class="k">trim_license 服务</span><span class="v">{'运行中' if s['trim_license_running'] else '停止'}</span></div>
    <div class="kv"><span class="k">二进制已 patch</span><span class="v">{'是' if patched else '否'}</span></div>
    <div class="kv"><span class="k">二进制 MD5</span><span class="v mono">{s['binary']['md5'][:16] or 'N/A'}…</span></div>
    <div class="kv"><span class="k">官方备份</span><span class="v">{'存在' if s['official_backup_exists'] else '无'}</span></div>
    <div class="kv"><span class="k">当前时间</span><span class="v">{s['time']}</span></div>
  </div>
</div>
<div id="monitor"></div>
<script>
"""
    html += MONITOR_JS
    html += "</script>"
    html += PAGE_FOOT
    return html


def render_operate():
    html = PAGE_HEAD.format(css=CSS, h1='', h2='class="active"', h3='')
    edition_opts = ''.join(f'<option value="{e}">{info["label"]} ({e})</option>' for e, info in payload.EDITIONS.items())

    OPERATE_JS = """
const log = document.getElementById('log');
function logLine(t, cls) { const d = document.createElement('div'); if(cls) d.className=cls; d.textContent = t; log.appendChild(d); log.scrollTop = log.scrollHeight; }
document.getElementById('applyForm').onsubmit = async (e) => {
  e.preventDefault(); log.innerHTML='';
  const body = {
    edition: document.getElementById('edition').value,
    license_code: document.getElementById('licenseCode').value,
    name: document.getElementById('name').value,
    enterprise_id: document.getElementById('entId').value,
    valid_from: parseInt(document.getElementById('validFrom').value)||0,
    valid_to: parseInt(document.getElementById('validTo').value)||4102444800000
  };
  logLine('开始执行破解...');
  try {
    const r = await fetch('/api/apply', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    const d = await r.json();
    (d.steps||[]).forEach(s=>logLine(s, s.includes('错误')?'err':s.includes('完成')?'ok':''));
    logLine(d.success ? '[OK] 破解完成' : '[X] 破解失败', d.success?'ok':'err');
  } catch(err) { logLine('请求失败: '+err, 'err'); }
};
document.getElementById('removeBtn').onclick = async () => {
  if(!confirm('确定移除破解并恢复官方许可证？')) return;
  log.innerHTML=''; logLine('开始移除...');
  try {
    const r = await fetch('/api/remove', {method:'POST'});
    const d = await r.json();
    (d.steps||[]).forEach(s=>logLine(s, s.includes('错误')?'err':s.includes('完成')?'ok':''));
    logLine(d.success ? '[OK] 移除完成' : '[X] 移除失败', d.success?'ok':'err');
  } catch(err) { logLine('请求失败: '+err, 'err'); }
};
"""

    html += f"""
<h2 style="margin-bottom:16px">许可证操作</h2>
<div class="alert alert-warn">WARN 本工具仅供学习交流。破解软件许可证可能违反许可协议，请自行评估风险。</div>
<div class="grid">
  <div class="card">
    <h3>应用破解</h3>
    <form id="applyForm">
      <div class="row">
        <div><label>权益等级</label><select id="edition">{edition_opts}</select></div>
        <div><label>授权码</label><input id="licenseCode" value="L-ENTERPRISE"></div>
      </div>
      <div class="row">
        <div><label>许可证名称</label><input id="name" value="飞牛素材库企业旗舰版"></div>
        <div><label>企业ID</label><input id="entId" value="ENT-LOCAL"></div>
      </div>
      <div class="row">
        <div><label>生效时间 (ms, 0=1970)</label><input id="validFrom" type="number" value="0"></div>
        <div><label>截至时间 (ms, 默认2100)</label><input id="validTo" type="number" value="{payload.VALID_TO_SAFE}"></div>
      </div>
      <div style="margin-top:14px"><button type="submit" class="btn btn-primary">执行破解</button></div>
    </form>
  </div>
  <div class="card">
    <h3>移除破解</h3>
    <p style="color:var(--dim);font-size:13px;margin-bottom:14px">恢复原始二进制，并从留存备份还原官方许可证。</p>
    <button class="btn btn-danger" id="removeBtn">移除破解</button>
  </div>
</div>
<div style="margin-top:16px">
  <h3 style="font-size:13px;color:var(--dim);margin-bottom:8px">操作日志</h3>
  <div class="log-box" id="log">等待操作...</div>
</div>
<script>
"""
    html += OPERATE_JS
    html += "</script>"
    html += PAGE_FOOT
    return html


def render_how_it_works():
    html = PAGE_HEAD.format(css=CSS, h1='', h2='', h3='class="active"')
    html += """
<h2 style="margin-bottom:16px">破解原理</h2>
<div class="card">
  <h3>Seek 许可证体系架构</h3>
  <p style="font-size:13px;color:var(--dim);margin-bottom:12px">素材库 Seek 是飞牛 fnOS 官方应用，其许可证验证链路如下：</p>
  <div class="mono" style="background:#0a0c10;padding:14px;border-radius:8px;line-height:1.8">
Seek (Go 应用)<br>
  └─ 内嵌 IPC 客户端 ──&gt; trim_license 服务（系统级）<br>
       ├─ 数据库 license 表（AES 加密 payload + Ed25519 签名）<br>
       └─ 云端校验：向 swl.fnnas.com 定期验证（经 trim-connect 隧道）<br>
  &nbsp;&nbsp;&nbsp;&nbsp;→ 云端找不到 → license 被标记 status=3（无效）
  </div>
</div>
<div class="step-desc" style="margin-top:20px">
  <h3 style="margin-bottom:12px">破解原理（三步）</h3>
  <div class="step"><div class="num">1</div><div>
    <h4>patch trim_license 二进制</h4>
    <p>定位 <span class="mono">softLicenseCheckInit</span> 函数中调用 <span class="mono">CheckLicense</span> 的 call 指令，改写为 NOP。这样云端检查不再执行，伪造的 license 不会被标记为无效。</p>
  </div></div>
  <div class="step"><div class="num">2</div><div>
    <h4>构造 enterprise payload</h4>
    <p>用逆向得到的 AES-256-CBC 密钥加密构造 license JSON（含 edition、licenseCode、validFrom、validTo、feature），写入数据库 license 表的 payload 字段。</p>
  </div></div>
  <div class="step"><div class="num">3</div><div>
    <h4>写入数据库</h4>
    <p>更新 license 表：payload（加密数据）+ 伪造 sign + 自定义授权码/名称/等级/时间。Seek 显示的数据来自 payload 解密结果，因此会显示 enterprise 版。</p>
  </div></div>
</div>
<div class="card">
  <h3>多版本自适应</h3>
  <table>
    <tr><th>方法</th><th>说明</th></tr>
    <tr><td>pclntab 解析</td><td>解析 Go 二进制的符号表（.gopclntab 段），动态定位函数地址，适配任意版本</td></tr>
    <tr><td>字节模式兜底</td><td>解析失败时，通过 call 指令特征字节序列匹配定位 patch 点</td></tr>
  </table>
</div>
"""
    html += PAGE_FOOT
    return html


def json_resp(obj, code=200):
    body = json.dumps(obj, ensure_ascii=False).encode()
    return b"HTTP/1.1 %d OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % (code, len(body)) + body


def html_resp(html):
    body = html.encode()
    return b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(body) + body


def is_admin(headers):
    # 端口直连模式：统一网关不再注入 X-Trim-Isadmin。
    # 放行本地/内网访问（WebUI 本身带免责声明，且依赖 root 权限操作）。
    # 若上层网关仍注入该 header，则以其为准；否则默认放行。
    v = headers.get('x-trim-isadmin', '')
    if v == '':
        return True
    return v.lower() == 'true'


def handle_request(data):
    """处理单个 HTTP 请求"""
    lines = data.split(b'\r\n')
    if not lines:
        return json_resp({'error': 'bad request'}, 400)
    req_line = lines[0].decode('utf-8', errors='replace')
    parts = req_line.split()
    if len(parts) < 2:
        return json_resp({'error': 'bad request'}, 400)
    method, path = parts[0], parts[1]
    headers = {}
    for line in lines[1:]:
        if b':' in line:
            k, v = line.split(b':', 1)
            headers[k.decode().strip().lower()] = v.decode().strip()

    # 解析 body
    body = b''
    idx = data.find(b'\r\n\r\n')
    if idx >= 0:
        body = data[idx+4:]
    clen = int(headers.get('content-length', '0') or 0)
    if clen > len(body):
        # 需读更多 body（此处由调用方处理，先截取已有）
        pass

    path = path.split('?')[0]

    if not is_admin(headers):
        return html_resp("<html><body><h1>403 需要管理员权限</h1></body></html>")

    if method == 'GET' and path in ('/', '/index.html'):
        return html_resp(render_status())
    if method == 'GET' and path == '/operate':
        return html_resp(render_operate())
    if method == 'GET' and path == '/how-it-works':
        return html_resp(render_how_it_works())
    if method == 'GET' and path == '/api/status':
        return json_resp(manager.get_status())
    if method == 'GET' and path == '/api/monitor':
        return json_resp({
            'seek': monitor.get_seek_metrics(),
            'db': monitor.get_db_stats(),
        })
    if method == 'POST' and path == '/api/apply':
        try:
            params = json.loads(body.decode('utf-8'))
            ok, steps = manager.apply_license(
                edition=params.get('edition', 'enterprise_ultimate'),
                license_code=params.get('license_code', 'L-ENTERPRISE'),
                name=params.get('name', '飞牛素材库企业旗舰版'),
                enterprise_id=params.get('enterprise_id', 'ENT-LOCAL'),
                valid_from=int(params.get('valid_from', 0)),
                valid_to=int(params.get('valid_to', payload.VALID_TO_SAFE)),
            )
            return json_resp({'success': ok, 'steps': steps})
        except Exception as e:
            return json_resp({'success': False, 'steps': [f'错误: {e}']})
    if method == 'POST' and path == '/api/remove':
        try:
            ok, steps = manager.remove_license()
            return json_resp({'success': ok, 'steps': steps})
        except Exception as e:
            return json_resp({'success': False, 'steps': [f'错误: {e}']})

    return json_resp({'error': 'not found'}, 404)


def server_loop(port):
    """启动 TCP 端口服务器（多线程处理，避免阻塞）"""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((BIND_HOST, port))
    server.listen(16)
    print(f"[web] 监听 {BIND_HOST}:{port}", flush=True)
    while True:
        conn, addr = server.accept()
        threading.Thread(target=_handle_conn, args=(conn,), daemon=True).start()


def _handle_conn(conn):
    """处理单个连接（线程内）"""
    conn.settimeout(10)
    try:
        data = b''
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                break
            data += chunk
            if b'\r\n\r\n' in data:
                head, _, rest = data.partition(b'\r\n\r\n')
                clen = 0
                for line in head.split(b'\r\n'):
                    if line.lower().startswith(b'content-length:'):
                        clen = int(line.split(b':', 1)[1].strip() or 0)
                if len(rest) >= clen:
                    break
        if data:
            resp = handle_request(data)
            conn.sendall(resp)
    except Exception:
        traceback.print_exc()
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else WEB_PORT
    server_loop(port)

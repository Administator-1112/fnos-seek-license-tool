# 🔧 Seek 许可证工具 (seek-license-tool)

> ⚠️ **免责声明**
>
> 本工具仅供**学习交流**使用，请于下载后 **24 小时内删除**。
>
> 使用本工具破解软件许可证可能违反软件许可协议及当地法律法规，**由此产生的任何后果由使用者自行承担**。请尊重软件开发者的劳动成果，**支持正版**。本工具不用于任何商业用途，不用于侵犯他人合法权益。

---

## 简介

**Seek 许可证工具** 是飞牛 fnOS 上的一款第三方应用，用于管理素材库 Seek 的许可证。

它提供图形化界面（Web UI）和命令行（CLI）两种操作方式，支持：

- **一键破解**：自动分析并 patch trim_license 二进制，跳过云端校验，写入自定义许可证
- **移除破解**：恢复原始二进制，从留存备份还原官方许可证
- **自定义配置**：授权码、许可证名称、权益等级、生效/截至时间
- **多版本自适应**：通过 Go pclntab 符号表动态解析，自动适配不同版本的 trim_license
- **官方许可证留存**：破解前自动备份官方许可证，可随时完整恢复

---

## 功能特性

### 破解（apply）

自动完成以下步骤：

1. **留存官方许可证**：破解前备份当前官方许可证（数据库记录 + payload 明文）
2. **patch trim_license 二进制**：定位 `softLicenseCheckInit` 中调用 `CheckLicense` 的指令并改写为 NOP，跳过云端检查
3. **构造许可证 payload**：AES-256-CBC 加密构造自定义许可证数据
4. **写入数据库**：更新 license 表（授权码、名称、等级、时间）
5. **重启服务**：让变更生效

### 移除破解（remove）

1. 停止 trim_license 服务
2. 恢复原始二进制
3. 从留存备份恢复官方许可证
4. 重启服务

### 权益等级

| 等级 | 中文名 | 用户数 | 项目数 |
|------|--------|--------|--------|
| `free` | 免费版 | 1 | 1 |
| `trial` | 体验版 | 100 | 无限 |
| `team` | 团队版 | 5 | 无限 |
| `enterprise` | 企业版 | 100 | 无限 |
| `enterprise_ultimate` | 企业旗舰版 | 无限 | 无限 |

---

## 安装

1. 下载 `seek-license-tool.fpk`
2. 在飞牛 fnOS 应用中心点击"手动安装"，选择该 fpk 文件
3. 安装完成后，在桌面或应用中心打开"Seek 许可证工具"

## 使用

### Web UI（推荐）

安装后，在桌面或应用中心点击"Seek 许可证工具"，浏览器会直接打开：

```
http://<NAS-IP>:17202
```

通过图形界面操作：

- **首页**：查看当前许可证状态、系统信息、数据库统计、Seek 实时资源占用（CPU/内存/GPU）
- **操作页**：执行破解、移除破解，配置授权码/名称/等级/时间
- **破解原理**：了解 Seek 许可证体系与破解原理

### CLI

```bash
# 查看状态
seek-license-tool status

# 一键破解（默认企业旗舰版）
seek-license-tool apply

# 自定义破解
seek-license-tool apply \
  --edition enterprise \
  --license-code "L-CUSTOM-2026" \
  --name "我的许可证" \
  --valid-from 0 \
  --valid-to 4102444800000

# 列出可用等级
seek-license-tool editions

# 移除破解
seek-license-tool remove

# 实时监控
seek-license-tool monitor
```

---

## 破解原理

素材库 Seek 的许可证验证链路：

```
Seek (Go 应用)
  └─ 内嵌 IPC 客户端 ──> trim_license 服务（系统级）
       ├─ 数据库 license 表（AES 加密 payload + 签名）
       └─ 云端校验：向 swl.fnnas.com 定期验证（经 trim-connect 隧道）
            → 云端找不到 → license 被标记无效
```

**破解三步**：

1. **patch trim_license 二进制**：改写调用 `CheckLicense` 的指令为 NOP，云端检查不再执行，伪造许可证不被标记无效
2. **构造许可证 payload**：用 AES-256-CBC 加密构造自定义许可证数据
3. **写入数据库**：更新 license 表

**多版本自适应**：通过解析 Go 二进制的 pclntab 符号表动态定位函数地址，自动适配任意版本；解析失败时回退字节模式匹配。

---

## 技术说明

- **运行环境**：飞牛 fnOS 1.2.0+
- **架构**：x86 / ARM（`platform=all`）
- **权限**：root（需要 patch 系统二进制、操作系统数据库）
- **访问**：TCP 端口 `17202` 直接访问（`http://<NAS-IP>:17202`）

## 项目结构

```
seek-license-tool/
├── app/
│   ├── bin/
│   │   ├── cli.py              # CLI 入口
│   │   ├── web.py              # Web UI 服务
│   │   ├── seek-license-tool   # CLI 可执行脚本
│   │   └── core/
│   │       ├── pclntab.py      # Go pclntab 解析（多版本自适应）
│   │       ├── patcher.py      # 二进制 patch 引擎
│   │       ├── payload.py      # AES 加解密
│   │       ├── db.py           # 数据库操作
│   │       ├── manager.py      # 协调模块
│   │       ├── preserve.py     # 官方许可证留存
│   │       └── monitor.py      # 资源监控
│   └── ui/
│       ├── config              # 桌面入口（type=url + port 17202）
│       └── images/             # 图标
├── cmd/                        # 生命周期脚本
├── config/                     # 权限与资源
├── manifest                    # 应用元数据
└── ICON.PNG / ICON_256.PNG     # 应用图标
```

---

## 许可证

本项目仅用于学习交流。使用本工具即表示您同意：

- 不将本工具用于任何商业用途
- 不利用本工具从事任何违法或侵权活动
- 下载后 24 小时内删除
- 自行承担使用本工具的一切后果

**请支持正版软件！**

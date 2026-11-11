<p align="center">
  <img src="docs/banner.png" alt="CleanYourMail — 你的收件箱，减去噪音" width="100%">
</p>

<p align="center">
  <a href="https://github.com/jparedesDS/cleanyourmail-app/actions/workflows/tests.yml"><img src="https://github.com/jparedesDS/cleanyourmail-app/actions/workflows/tests.yml/badge.svg" alt="测试"></a>
  <img src="https://img.shields.io/badge/license-MIT-b9f36a?labelColor=08110d" alt="MIT">
  <img src="https://img.shields.io/badge/python-3.12%2B-b9f36a?labelColor=08110d" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/windows-10%2F11%20x64-b9f36a?labelColor=08110d" alt="Windows 10/11 x64">
  <img src="https://img.shields.io/badge/local--by--default-opt%20in%20feedback-b9f36a?labelColor=08110d" alt="默认本地，可选反馈">
</p>

<p align="center">
  <a href="README.md">English</a> ·
  <a href="README.es.md">Español</a> ·
  <a href="README.pt-BR.md">Português (BR)</a> ·
  <a href="README.fr.md">Français</a> ·
  <a href="README.de.md">Deutsch</a> ·
  <a href="README.it.md">Italiano</a> ·
  <a href="README.ja.md">日本語</a> ·
  <b>简体中文</b> ·
  <a href="README.zh-TW.md">繁體中文</a> ·
  <a href="README.ko.md">한국어</a>
</p>

# CleanYourMail 应用

**你的收件箱，减去噪音——一款原生 Windows 应用。** CleanYourMail 应用是 CleanYourMail CLI 的 PySide6 前端。它会引导你连接邮箱、选择要清理的内容、审阅可撤销的计划并撤销操作。

没有浏览器，没有本地服务器，没有账号，没有遥测，不读取邮件正文，也不会永久删除。应用自身发出的唯一网络请求，就是你主动发送的反馈 POST。

> **状态：** `0.4.0` 是当前 Windows 早期 MVP 版本。它新增了从应用顶栏和网站发送的可选反馈。安装程序捆绑了冻结的 CleanYourMail CLI `1.2.2` sidecar。Gmail 已验证；Outlook 取决于 Microsoft 的同意模式。见[提供商状态](#provider-status)。

## 下载

[适用于 Windows 10/11 x64 的 CleanYourMail 应用 0.4.0](https://github.com/jparedesDS/cleanyourmail-app/releases/latest) 是每用户安装程序，捆绑固定版本的 CleanYourMail CLI `1.2.2` sidecar，无需管理员权限。

0.4.0 安装程序未进行代码签名。首次启动时，Windows SmartScreen 可能显示“未知发布者”警告：请选择**更多信息**，再选择**仍要运行**，并将随版本发布的 SHA-256 与 `CleanYourMail-Setup-0.4.0.exe` 进行比对：

```powershell
Get-FileHash .\CleanYourMail-Setup-0.4.0.exe -Algorithm SHA256
```

发布页还提供 `.sha256` 文件，格式为 `HASH  filename`。

Gmail 可通过应用专用密码和两步验证使用。Outlook / Microsoft 365 无法一键完成：Microsoft 365 需要租户管理员同意，个人 Outlook.com 账户需要已验证的发布者。macOS 和 Linux 不在 0.4.0 的支持范围内。

## 为什么做这个应用

CleanYourMail CLI 是引擎，也是唯一事实来源。它已经负责 IMAP 访问、分类、计划、可撤销的移动和撤销日志。它缺少的是一条捷径，让不想使用终端或编辑 TOML 文件的人也能完成操作。

这个应用在不重复实现引擎的前提下补上了这条路：

- 选择提供商并连接，无需手写配置文件。
- 用复选框和单选按钮选择分类和模式。
- 在发生任何更改之前扫描、阅读报告并检查计划。
- 只有在明确审阅后才应用，然后从同一窗口撤销。
- 所有界面都可使用英语或西班牙语。

应用本身从不实现 IMAP、计划、移动、撤销或退订。它调用冻结的 CleanYourMail CLI sidecar 并呈现结果，因此只有一套安全模型和一套规则。

## 截图

<p align="center">
  <img src="docs/images/app-provider.png" alt="选择提供商并输入邮箱地址" width="49%">
  <img src="docs/images/app-review.png" alt="在应用更改前审阅计划" width="49%">
</p>

## 要求

- 安装程序需要 Windows 10/11 x64。
- 仅从源码运行时需要 Python **3.12+**。
- CleanYourMail CLI `1.2.2` sidecar。安装程序已捆绑；开发时，请将 `CYM_CLI` 指向具有相同 JSON 契约的已构建 `cym-cli.exe`。应用不会直接运行 `mail.py`。

## 开发

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[dev]"
python -m cleanyourmail_app --version
```

`python -m cleanyourmail_app --version` 会输出 `CleanYourMail app 0.4.0`。

运行测试：

```bash
python -m pytest -q
```

测试套件使用模拟 CLI 测试夹具，从不需要真实邮箱、凭据或网络访问。

## 应用功能

1. **欢迎 / 提供商。** 选择 Gmail、Outlook / Microsoft 365、Yahoo、iCloud、Fastmail、Proton Bridge 或自定义 IMAP，并输入邮箱地址。
2. **连接。** Gmail 使用引导式应用专用密码流程，Outlook 使用设备代码流程，其余提供商提供各自的应用专用密码帮助。应用绝不会要求输入常规密码。
3. **偏好设置。** 要清理的分类、文件夹或归档、保护项、限制和语言。
4. **审阅并清理。** 扫描、报告、计划、审阅关卡、按限制应用，以及撤销日志。计划中的退订列仅供参考：此版本从不发送退订请求，应用始终以 `--action move` 执行。

## 反馈

反馈是**可选且手动**的。点击应用顶栏中的**反馈**按钮，或使用[网站表单](https://cleanyourmail.org/#feedback)。应用不会在后台收集任何内容；在你点击**发送**并接受同意声明之前，它不会发送任何内容。

- 应用会预填一份**可编辑的清单**，包含应用和 sidecar 版本、Windows 版本、提供商名称、文件夹/归档模式、所选分类和语言。
- 不想分享的内容可以修改或删除。请**不要**在消息或清单中填写密码、令牌、邮箱地址、邮件主题、消息 ID 或文件路径。
- 可选的联系方式字段是唯一可以留下 Discord 账号、GitHub 用户名或邮箱地址的地方。它从来不是必填项。
- 请求会发送到 Cloudflare Worker（`cleanyourmail-feedback`），由它校验后转发到私有 Discord 频道。Discord webhook 是 Cloudflare 机密，绝不会随应用或网站发布。
- **没有账号、没有遥测、没有分析，也没有崩溃报告。** Worker 不存储消息正文，并会按经过加盐处理的 IP 实施短时频率限制。

<a id="provider-status"></a>

## 提供商状态

| 提供商 | 应用内方式 | 状态 |
|---|---|---|
| Gmail | 应用专用密码 + 两步验证 | 通过，已用 CLI 1.2.2 验证 |
| Outlook / Microsoft 365 | 设备代码 | 部分可用：Microsoft 365 需要租户管理员同意；Outlook.com 个人账户需要已验证的发布者 |
| Yahoo, iCloud, Fastmail | 应用专用密码 | 已有文档，未做冒烟测试 |
| Proton Bridge | Bridge 密码 | 已有文档，未做冒烟测试 |
| 自定义 IMAP | 主机；固定端口 993，启用 TLS | 已有文档，未做冒烟测试 |

应用会如实报告这些状态。它不会声称 Outlook 支持一键连接。

## 安全模型

- **除可选反馈外，仅限本地。** 没有账号、云服务、遥测或正文访问。应用不会在后台发起网络请求；它自身发出的唯一请求，是你点击发送并接受同意声明后的反馈 POST。
- **仅通过 CLI。** 应用无法添加 CLI 不具备的能力。
- **命令行参数中不含机密。** 应用专用密码会写入 CLI 的 `password_file`；应用绝不会将其作为命令行参数传递。
- **应用设置中不存储机密。** 机密绝不会进入 QSettings、日志、错误对话框或测试输出。
- **先审阅。** 没有经过审阅的计划就不会写入；撤销始终只需点击一次。
- **不永久删除。** 移动和归档均可撤销。
- **0.4.0 不支持退订。** 计划中可能显示退订模式，但应用只会移动邮件。
- **英语和西班牙语都是完整支持的语言。** 所有字符串都位于 `i18n/*.json`。

见 [SECURITY.md](SECURITY.md) 了解如何报告漏洞。

## 项目结构

| 路径 | 说明 |
|---|---|
| `src/cleanyourmail_app/` | 原生应用包。 |
| `src/cleanyourmail_app/version.py` | 应用版本的唯一来源。 |
| `src/cleanyourmail_app/__main__.py` | `python -m cleanyourmail_app` 入口点。 |
| `src/cleanyourmail_app/app.py` | 构建本地服务并打开向导。 |
| `src/cleanyourmail_app/ui/` | PySide6 窗口、页面、控件、主题和资源。 |
| `src/cleanyourmail_app/domain/` | 提供商目录、设置、偏好设置和计划模型。 |
| `src/cleanyourmail_app/services/` | sidecar 客户端（`cli.py`）、配置（`config.py`）、机密（`secrets.py`）、OAuth（`oauth.py`）和设置（`settings.py`）。 |
| `src/cleanyourmail_app/i18n/` | 英语和西班牙语字符串。 |
| `scripts/` | sidecar/应用构建和安装程序冒烟测试。 |
| `packaging/` | Inno Setup 脚本和图标。 |
| `tests/` | 使用模拟 CLI 测试夹具的 pytest 和 pytest-qt 套件。 |
| `docs/superpowers/specs/` | 设计文档（0.3.0 应用、0.4.0 反馈）。 |
| `docs/superpowers/plans/` | 逐项任务的实现计划。 |

## 链接

- 应用版本发布：<https://github.com/jparedesDS/cleanyourmail-app/releases/latest>
- Skill 与 CLI：<https://github.com/jparedesDS/cleanyourmail>
- 网站：<https://cleanyourmail.org/>
- 安全模型：<https://github.com/jparedesDS/cleanyourmail/blob/master/docs/SAFETY.md>

## 许可证

MIT。见 [LICENSE](LICENSE)。

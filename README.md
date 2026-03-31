# Lunes Host Auto Login

使用 Playwright + Camoufox 反检测浏览器自动登录 Mondays Host，解决 Cloudflare Turnstile 验证。

## 功能特性

- **Camoufox 反检测浏览器** - 提供真实浏览器指纹伪装
- **人类鼠标移动** - 模拟人类点击 Turnstile 验证框的行为
- **多账号/多服务器支持** - 支持配置不同服务器ID
- 支持代理配置
- 支持 GitHub Actions 定时任务

## 核心方案

### 成功关键点

1. **Camoufox 反检测浏览器** - 提供 Canvas、WebGL、UA 等指纹伪装
2. **人类鼠标移动** - 分步骤移动，带随机抖动
3. **点击前犹豫** - 等待 300-800ms 模拟人类行为
4. **验证等待** - 点击后等待 12 秒让 Cloudflare 验证完成

### 工作原理

```python
# 1. 找到 Turnstile 验证框位置
# 2. 模拟人类鼠标移动到验证框（带随机抖动）
# 3. 等待一小段时间（模拟人类犹豫）
# 4. 点击验证框
# 5. 等待 Cloudflare 验证完成
# 6. 填写表单并登录
```

## 本地运行

### 前置要求

- Python 3.11+
- Camoufox 浏览器（需手动下载）

### 安装依赖

```bash
pip install playwright
playwright install firefox
```

### 下载 Camoufox

```bash
# 使用代理下载
curl -x http://127.0.0.1:10808 -L -o camoufox.zip "https://github.com/daijro/camoufox/releases/download/v135.0.1-beta.24/camoufox-135.0.1-beta.24-linux.x86_64.zip"
unzip -o camoufox.zip -d camoufox
rm camoufox.zip
```

### 运行

```bash
# 配置环境变量（必须）
export LOGIN_EMAIL=your_email@example.com
export LOGIN_PASSWORD=your_password

# 运行登录脚本
python scripts/login.py

# 指定服务器ID（可选）
export SERVER_ID=73546
python scripts/login.py
```

## 环境变量

| 变量 | 必需 | 说明 |
|------|------|------|
| LOGIN_EMAIL | ✅ | 登录邮箱 |
| LOGIN_PASSWORD | ✅ | 登录密码 |
| SERVER_ID | ❌ | 服务器ID，默认为空（登录页面） |
| CAMOUFOX_PATH | ❌ | Camoufox 浏览器路径，默认 ./camoufox/camoufox |
| HEADLESS | ❌ | 无头模式，默认 true |

## GitHub Actions

工作流文件：`.github/workflows/lunes-login.yml`

### Secrets 配置

| Secret | 必需 | 说明 |
|--------|------|------|
| LOGIN_EMAIL | ✅ | 登录邮箱 |
| LOGIN_PASSWORD | ✅ | 登录密码 |
| SERVER_ID | ❌ | 服务器ID |
| TELEGRAM_BOT_TOKEN | ❌ | Telegram Bot Token（用于通知） |
| TELEGRAM_CHAT_ID | ❌ | Telegram Chat ID（用于通知） |

### 多账号配置

在 GitHub Secrets 中设置 `ACCOUNTS_JSON`（JSON数组格式）：

```json
[
  {"email": "user1@example.com", "password": "pass1", "server_id": "73546"},
  {"email": "user2@example.com", "password": "pass2", "server_id": "73547"}
]
```

### 定时任务

- 每天 03:17 UTC 执行

## 项目结构

```
lunes-host-auto-login/
├── .github/workflows/   # GitHub Actions 工作流
├── artifacts/           # 输出目录
│   └── screenshots/   # 截图
├── camoufox/           # Camoufox 浏览器（需下载）
├── scripts/
│   └── login.py        # 主登录脚本
└── package.json
```

## 测试结果

| 方法 | 结果 |
|------|------|
| Camoufox + 鼠标移动 | ✅ 成功 |
| 普通 Firefox + 鼠标移动 | ❌ 失败 |
| 仅 Camoufox | ❌ 失败 |
| 仅鼠标移动 | ❌ 失败 |

**结论**：Camoufox 的反检测功能 + 人类鼠标移动必须配合使用才能成功绕过 Turnstile。
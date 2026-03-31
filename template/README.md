# CF Turnstile 绕过登录模板

一套可复用的 Cloudflare Turnstile 绕过登录解决方案，使用 Camoufox 反检测浏览器 + 人类鼠标移动。

## 快速开始

### 1. 复制模板文件

```bash
# 复制到目标项目
mkdir -p your-project/template
cp cf-bypass-login.py your-project/template/
cp workflow-template.yml your-project/.github/workflows/
```

### 2. 配置 GitHub Secrets

| Secret | 说明 |
|--------|------|
| LOGIN_URL | 登录页面URL |
| LOGIN_EMAIL | 登录邮箱 |
| LOGIN_PASSWORD | 登录密码 |
| SUCCESS_URL_PATTERN | 成功后URL关键字（逗号分隔） |
| TELEGRAM_BOT_TOKEN | Telegram Bot Token（可选） |
| TELEGRAM_CHAT_ID | Telegram Chat ID（可选） |

### 3. 运行

**本地运行：**
```bash
pip install playwright
playwright install firefox

# 下载 Camoufox
curl -L -o camoufox.zip "https://github.com/daijro/camoufox/releases/download/v135.0.1-beta.24/camoufox-135.0.1-beta.24-lin.x86_64.zip"
unzip camoufox.zip -d camoufox

# 运行
LOGIN_URL=https://example.com/login \
LOGIN_EMAIL=user@example.com \
LOGIN_PASSWORD=yourpassword \
SUCCESS_URL_PATTERN=dashboard,account \
python template/cf-bypass-login.py
```

**GitHub Actions：**
```bash
gh workflow run workflow-template.yml
```

## 自定义配置

### 修改选择器

编辑 `cf-bypass-login.py` 中的 `CONFIG` 字典：

```python
CONFIG = {
    "email_selectors": 'input[name="email"], input[type="email"]',
    "password_selectors": 'input[name="password"], input[type="password"]',
    "submit_selectors": 'button[type="submit"]',
    "turnstile_selectors": [
        'iframe[src*="turnstile"]',
        'iframe[class*="turnstile"]',
        '[data-sitekey]',
        '.cf-turnstile',
        '[class*="turnstile"]'
    ],
    "success_patterns": [],  # 从环境变量读取
    "error_indicators": [
        "Internal Server Error",
        "Error",
        "error",
        "failed"
    ]
}
```

### 修改运行时间

编辑 workflow 文件中的 cron 表达式：

```yaml
schedule:
  - cron: '0 3 * * *'  # UTC 03:00
```

## 技术原理

### 为什么有效？

1. **Camoufox 反检测浏览器**
   - Canvas、WebGL、AudioContext 指纹伪装
   - Navigator 属性伪装
   - 自动化检测规避

2. **人类鼠标移动**
   - 15步分步移动，每步随机抖动 ±5px
   - 点击前犹豫 300-800ms
   - 模拟真实用户行为

3. **关键时序**
   - 访问页面后等待 5 秒
   - Turnstile 点击后等待 12 秒
   - 提交后等待 10 秒

### 测试结果

| 方法 | 结果 |
|------|------|
| Camoufox + 鼠标移动 | ✅ 成功 |
| 普通 Firefox + 鼠标移动 | ❌ 失败 |
| 仅 Camoufox | ❌ 失败 |
| 仅鼠标移动 | ❌ 失败 |

**结论**：反检测 + 人类行为必须配合使用。

## 依赖

- Python 3.11+
- Playwright
- Camoufox 浏览器

## 文件结构

```
template/
├── cf-bypass-login.py    # 核心登录脚本
├── workflow-template.yml # GitHub Actions 模板
└── README.md             # 本文档
```

## 常见问题

### Q: 截图显示 500 错误？

A: 这是服务端问题，不是脚本问题。登录可能已成功，但服务器内部错误。

### Q: Turnstile 未找到？

A: 页面可能没有 CF 保护，或选择器需要调整。检查页面源码。

### Q: 点击按钮超时？

A: 正常现象，说明页面已在跳转。脚本会继续等待。

## License

MIT

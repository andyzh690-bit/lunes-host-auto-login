# Lunes Host Auto Login

使用 SeleniumBase UC/CDP 模式自动登录 Lunes Host，并在 GitHub Actions 中定时运行。

## Cloudflare 验证

项目内置 MV3 扩展，在所有 frame 的 `document_start` 阶段修正 CDP 鼠标事件的 `screenX/screenY` 坐标。登录脚本先执行快速点击并在 5 秒窗口内轮询 Turnstile token；未成功时再执行兼容性回退。

实现参考：[ObjectAscended/CDP-bug-MouseEvent-.screenX-.screenY-patcher](https://github.com/ObjectAscended/CDP-bug-MouseEvent-.screenX-.screenY-patcher)。

## GitHub Actions

工作流每周一 `07:00` 按 `Asia/Shanghai` 时区运行，也支持手动启动。

需要配置以下 Repository Secrets：

| Secret | 必需 | 说明 |
| --- | --- | --- |
| `LOGIN_EMAIL` | 是 | 登录邮箱 |
| `LOGIN_PASSWORD` | 是 | 登录密码 |
| `SERVER_ID` | 否 | 登录后打开的服务器 ID |
| `PROXY_URL` | 否 | Sing-box 支持的代理链接 |
| `TELEGRAM_BOT_TOKEN` | 否 | Telegram 通知 token |
| `TELEGRAM_CHAT_ID` | 否 | Telegram 通知目标 |

## 本地验证

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
$env:LOGIN_EMAIL = 'user@example.com'
$env:LOGIN_PASSWORD = 'password'
python scripts/login.py
Remove-Item Env:\LOGIN_EMAIL, Env:\LOGIN_PASSWORD
```

运行证据保存在 `artifacts/login-result.json` 和 `artifacts/screenshots/login-result.png`。

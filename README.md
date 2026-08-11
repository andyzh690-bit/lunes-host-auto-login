# Lunes Host Auto Login

使用 Microsoft Edge 与 DrissionPage CDP 模式自动登录 Lunes Host，并在 GitHub Actions 中定时运行。

## Cloudflare 验证

项目内置 MV3 扩展，在所有 frame 的 `document_start` 阶段修正 CDP 鼠标事件的 `screenX/screenY` 坐标。脚本进入 Turnstile shadow root 与 iframe，修补 iframe 事件坐标后仅点击一次真实 checkbox；前 5 秒作为快速窗口，之后继续校验 token，避免重复点击重启验证。

GitHub Actions 使用 `windows-latest` 和系统自带 Microsoft Edge。代理链接由 `scripts/proxy_handler.py` 转换为本地 `http://127.0.0.1:8080`，浏览器启动后会再次验证实际出口 IP。VLESS XHTTP 使用 Xray，VLESS WebSocket 及其他支持协议使用 Sing-box。

实现参考：[ObjectAscended/CDP-bug-MouseEvent-.screenX-.screenY-patcher](https://github.com/ObjectAscended/CDP-bug-MouseEvent-.screenX-.screenY-patcher)。

## GitHub Actions

工作流每周一 `07:00` 按 `Asia/Shanghai` 时区运行，也支持手动启动。

需要配置以下 Repository Secrets：

| Secret | 必需 | 说明 |
| --- | --- | --- |
| `LOGIN_EMAIL` | 是 | 登录邮箱 |
| `LOGIN_PASSWORD` | 是 | 登录密码 |
| `SERVER_ID` | 否 | 登录后打开的服务器 ID |
| `PROXY_URL` | 否 | HTTP、SOCKS5、VLESS、VMess、Hysteria2 或 TUIC 代理链接 |
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

运行证据保存在 `artifacts/login-result.json` 和 `artifacts/screenshots/`。登录成功时会额外生成 `login-success.png`，上传到 Actions Artifacts 并发送至 Telegram。

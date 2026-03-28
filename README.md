# Lunes Host Auto Login

This project uses Playwright and GitHub Actions to log into `https://betadash.lunes.host/servers/73546`, wait for the Cloudflare Turnstile challenge to be solved, capture success or failure screenshots, log out after a successful login, and optionally notify Telegram.

## Features

- Single-account login with `LOGIN_EMAIL` and `LOGIN_PASSWORD`
- Multi-account login with `ACCOUNTS_JSON`
- Proxy support for browser traffic
- `vmess://`, `vless://`, `trojan://`, and `hy2://` node support through sing-box in GitHub Actions
- Raw `sing-box` outbound JSON support for other proxy types
- Telegram summary and screenshot notification
- GitHub Actions workflow with manual runs and a daily schedule guarded by a 13-day interval check
- Screenshot artifacts for every run

## Login flow captured from the page

The target page currently renders a login screen with these steps:

1. Open `https://betadash.lunes.host/servers/73546`
2. The site redirects to a login form when the session is not authenticated
3. Fill `Email address`
4. Fill `Password`
5. Wait for the Cloudflare Turnstile widget to finish
6. Click `Continue to dashboard`
7. After success, the browser returns to `/servers/73546`
8. Click a `Logout` or `Sign out` action and confirm the session ends

The script implements the same flow with a few fallback selectors so it tolerates small UI changes.

## Required GitHub Secrets

### Single account

- `LOGIN_EMAIL`
- `LOGIN_PASSWORD`

### Multiple accounts

Use `ACCOUNTS_JSON` instead of the two secrets above.

Example:

```json
[
  {
    "email": "primary@example.com",
    "password": "example-password",
    "name": "primary-account"
  },
  {
    "email": "second@example.com",
    "password": "example-password",
    "name": "backup"
  }
]
```

## Optional GitHub Secrets

- `TARGET_URL` default: `https://betadash.lunes.host/servers/73546`
- `LOGIN_PROXY_SERVER` example: `http://host:port` or `socks5://host:port`
- `LOGIN_PROXY_USERNAME`
- `LOGIN_PROXY_PASSWORD`
- `LOGIN_PROXY_BYPASS` example: `.local,127.0.0.1`
- `VMESS_URL` full `vmess://...` link for automatic sing-box bootstrap in GitHub Actions
- `VLESS_URL` full `vless://...` link for automatic sing-box bootstrap in GitHub Actions
- `TROJAN_URL` full `trojan://...` link for automatic sing-box bootstrap in GitHub Actions
- `HY2_URL` or `HYSTERIA2_URL` full `hy2://...` or `hysteria2://...` link for automatic sing-box bootstrap in GitHub Actions
- `SINGBOX_OUTBOUND_JSON` raw sing-box outbound JSON for any other supported sing-box protocol
- `LOCAL_HTTP_PROXY_PORT` optional, default `7890`
- `LOCAL_SOCKS_PROXY_PORT` optional, default `7891`
- `S5_PROXY_HOST` for SOCKS5 host
- `S5_PROXY_PORT` for SOCKS5 port
- `S5_PROXY_USERNAME`
- `S5_PROXY_PASSWORD`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `HEADLESS` default: `true`
- `RUN_TIMEOUT_MS` default: `120000`
- `SUCCESS_URL_PATTERN` default: `/servers/73546`

## Local run

```bash
npm install
npx playwright install --with-deps chromium
LOGIN_EMAIL="your-email@example.com" LOGIN_PASSWORD="your-password" npm run login
```

With proxy:

```bash
LOGIN_PROXY_SERVER="http://host:port" npm run login
```

With `vmess://` in GitHub Actions:

```text
VMESS_URL=vmess://eyJ2IjoiMiIsInBzIjoiLi4uIn0=
```

With `vless://` in GitHub Actions:

```text
VLESS_URL=vless://uuid@example.com:443?security=tls&type=ws&host=example.com&path=%2Fws&sni=example.com#node-name
```

With `trojan://` in GitHub Actions:

```text
TROJAN_URL=trojan://password@example.com:443?security=tls&type=ws&host=example.com&path=%2Ftrojan&sni=example.com#node-name
```

With `hy2://` in GitHub Actions:

```text
HY2_URL=hy2://password@example.com:443?sni=example.com&insecure=0#node-name
```

With raw sing-box outbound JSON:

```json
{
  "type": "shadowsocks",
  "tag": "proxy-out",
  "server": "1.2.3.4",
  "server_port": 443,
  "method": "2022-blake3-aes-128-gcm",
  "password": "your-password"
}
```

The workflow will:

1. install `sing-box`
2. convert the provided node secret into `runtime/sing-box.json`
3. start a local mixed proxy on `127.0.0.1:7890`
4. set `LOGIN_PROXY_SERVER=http://127.0.0.1:7890`
5. run the Playwright login script through that proxy

## Schedule behavior

- The workflow cron runs once per day.
- Scheduled runs only proceed when at least 13 days have passed since the last successful run of `lunes-login.yml`.
- Manual `workflow_dispatch` runs ignore the 13-day gate and run immediately.
- The interval check uses the GitHub Actions API, so no extra state file needs to be committed.

With SOCKS5 proxy:

```bash
S5_PROXY_HOST="127.0.0.1" S5_PROXY_PORT="1080" npm run login
```

With authenticated SOCKS5 proxy:

```bash
S5_PROXY_HOST="127.0.0.1" S5_PROXY_PORT="1080" S5_PROXY_USERNAME="user" S5_PROXY_PASSWORD="pass" npm run login
```

With multiple accounts:

```bash
ACCOUNTS_JSON='[{"email":"your-email@example.com","password":"your-password","name":"main-account"}]' npm run login
```

## Output

- Screenshots are written to `artifacts/screenshots/`
- A machine-readable summary is written to `artifacts/login-results.json`
- GitHub Actions uploads the entire `artifacts/` directory

## Notes

- Cloudflare checks can be stricter in CI than on a local machine; using a stable proxy usually improves success rate.
- Telegram notification is skipped automatically when bot token or chat id is missing.
- If you use SOCKS5 in GitHub Actions, add `S5_PROXY_HOST`, `S5_PROXY_PORT`, and optionally `S5_PROXY_USERNAME` and `S5_PROXY_PASSWORD` as repository secrets.
- If you use `VMESS_URL`, store the full `vmess://...` string as a GitHub secret named `VMESS_URL`.
- If you use one of the sing-box node secrets, set only one of `VMESS_URL`, `VLESS_URL`, `TROJAN_URL`, `HY2_URL`, `HYSTERIA2_URL`, or `SINGBOX_OUTBOUND_JSON` per workflow run.
- The default daily cron is `17 3 * * *`, but the actual login only runs when the 13-day interval gate allows it.
- For `vmess://...?...ed=NNNN` links, the generator strips the `ed` query from the WebSocket path and maps it to sing-box early data fields to avoid common `404` handshake issues.

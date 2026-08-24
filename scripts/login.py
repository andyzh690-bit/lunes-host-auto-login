#!/usr/bin/env python3
"""Lunes Host login automation using DrissionPage and a Turnstile patch."""

from __future__ import annotations

import ipaddress
import json
import os
import random
import sys
import time
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
SERVER_ID = os.getenv("SERVER_ID", "").strip()
EMAIL = os.getenv("LOGIN_EMAIL", "").strip()
PASSWORD = os.getenv("LOGIN_PASSWORD", "")
PROXY_SERVER = os.getenv("PROXY_SERVER", "").strip()
BROWSER_PATH = os.getenv("BROWSER_PATH", "").strip()

LOGIN_URL = "https://betadash.lunes.host/login"
TARGET_URL = (
    f"https://betadash.lunes.host/servers/{SERVER_ID}"
    if SERVER_ID
    else LOGIN_URL
)

ARTIFACTS_DIR = ROOT_DIR / "artifacts"
SCREENSHOT_DIR = ARTIFACTS_DIR / "screenshots"
SCREENSHOT_PATH = SCREENSHOT_DIR / "login-result.png"
SUCCESS_SCREENSHOT_PATH = SCREENSHOT_DIR / "login-success.png"
FAST_CLICK_SCREENSHOT_PATH = SCREENSHOT_DIR / "turnstile-fast-click.png"
RESULT_PATH = ARTIFACTS_DIR / "login-result.json"
TURNSTILE_EXTENSION_DIR = ROOT_DIR / "extensions" / "turnstile-screenxy"
TURNSTILE_PATCH_PATH = TURNSTILE_EXTENSION_DIR / "screenxy.js"

NAVIGATION_ATTEMPTS = 3
NAVIGATION_RETRY_SECONDS = 10
TURNSTILE_FAST_TIMEOUT_SECONDS = float(
    os.getenv("TURNSTILE_FAST_TIMEOUT_SECONDS", "5")
)
TOKEN_POLL_SECONDS = 0.25
TURNSTILE_TOTAL_TIMEOUT_SECONDS = 35


def take_screenshot(tab, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tab.get_screenshot(path=str(path.parent), name=path.name, full_page=True)


def take_success_screenshot(tab) -> None:
    try:
        take_screenshot(tab, SUCCESS_SCREENSHOT_PATH)
        print(f"[Screenshot] Login success: {SUCCESS_SCREENSHOT_PATH}")
    except Exception as exc:
        print(f"[Screenshot] Login success capture failed: {exc}")


def save_result(tab, success: bool, error: str | None = None, **details) -> None:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    url = ""
    if tab is not None:
        try:
            url = tab.url
        except Exception:
            pass
        try:
            take_screenshot(tab, SCREENSHOT_PATH)
        except Exception as exc:
            print(f"[Screenshot] Failed: {exc}")

    result = {
        "success": success,
        "url": url,
        "server_id": SERVER_ID,
        "error": error,
        **details,
    }
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[Result] {result}")


def page_text(tab) -> str:
    try:
        body = tab.ele("tag:body", timeout=2)
        return (body.text or "") if body else ""
    except Exception:
        return ""


def browser_network_error(tab) -> str | None:
    try:
        title = (tab.title or "").lower()
        source = (tab.html or "")[:50000].lower()
    except Exception:
        title = ""
        source = ""
    content = "\n".join((title, source, page_text(tab).lower()))
    markers = (
        ("err_proxy_connection_failed", "proxy_connection_failed"),
        ("err_tunnel_connection_failed", "proxy_tunnel_failed"),
        ("err_connection_refused", "connection_refused"),
        ("err_name_not_resolved", "dns_failed"),
        ("err_internet_disconnected", "internet_disconnected"),
        ("you're not connected", "proxy_connection_failed"),
        ("this site can't be reached", "site_unreachable"),
        ("this site can’t be reached", "site_unreachable"),
    )
    return next((error for marker, error in markers if marker in content), None)


def has_upstream_error(tab) -> bool:
    try:
        title = (tab.title or "").lower()
        source = (tab.html or "")[:10000].lower()
    except Exception:
        return False

    markers = (
        "bad gateway",
        "host error",
        "internal server error",
        "error code 502",
        "error code 503",
        "error code 504",
    )
    return any(marker in title or marker in source for marker in markers)


def parse_exit_ip(value: str) -> str | None:
    candidate = (value or "").strip()
    try:
        decoded = json.loads(candidate)
        if isinstance(decoded, dict):
            candidate = str(decoded.get("ip", "")).strip()
    except (json.JSONDecodeError, TypeError):
        pass
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def is_authenticated_target(tab) -> bool:
    if browser_network_error(tab):
        return False
    try:
        current_url = tab.url or ""
    except Exception:
        return False
    if "/login" in current_url.lower():
        return False
    if SERVER_ID and f"/servers/{SERVER_ID}" not in current_url:
        return False
    try:
        if tab.ele(
            "css:input#password, input[name='password'], input[type='password']",
            timeout=1,
        ):
            return False
    except Exception:
        return False
    return len(page_text(tab).strip()) >= 20


def navigate_with_retry(tab, url: str) -> tuple[bool, str | None]:
    last_error = "navigation_failed"
    for attempt in range(1, NAVIGATION_ATTEMPTS + 1):
        try:
            tab.get(url, retry=0, timeout=30)
            time.sleep(4)
            network_error = browser_network_error(tab)
            if network_error:
                last_error = f"browser_network_error:{network_error}"
                print(
                    f"[Navigation] {last_error} "
                    f"(attempt {attempt}/{NAVIGATION_ATTEMPTS})"
                )
            elif not has_upstream_error(tab):
                return True, None
            else:
                last_error = "upstream_server_error"
                print(
                    "[Navigation] Target returned a server error "
                    f"(attempt {attempt}/{NAVIGATION_ATTEMPTS})"
                )
        except Exception as exc:
            last_error = f"navigation_exception:{type(exc).__name__}"
            print(
                f"[Navigation] {last_error} "
                f"(attempt {attempt}/{NAVIGATION_ATTEMPTS}): {exc}"
            )

        if attempt < NAVIGATION_ATTEMPTS:
            time.sleep(NAVIGATION_RETRY_SECONDS * attempt)

    return False, last_error


def get_turnstile_token(tab) -> str:
    script = """
        try {
          if (window.turnstile && typeof window.turnstile.getResponse === 'function') {
            const response = window.turnstile.getResponse();
            if (response) return response;
          }
        } catch (error) {}
        const names = ['cf-turnstile-response', 'g-recaptcha-response'];
        for (const name of names) {
          const element = document.querySelector(`[name="${name}"]`);
          if (element && element.value) return element.value;
        }
        return '';
    """
    try:
        return tab.run_js(script) or ""
    except Exception:
        return ""


def patch_and_click_turnstile(tab) -> dict:
    response = tab.ele("@name=cf-turnstile-response", timeout=3)
    if not response:
        raise RuntimeError("turnstile_response_missing")

    # 多策略定位挑战 iframe：不再假设 response.parent() 就是 shadow host。
    # 隐藏 input 在轻 DOM 中，其直接父节点通常是内层 div，shadow root 实际
    # 挂在 .cf-turnstile 组件或更外层祖先上（beta 面板改版后尤为常见）。
    challenge_iframe = None
    try:
        node = response.parent()
        for _ in range(4):                      # a) 向上查找带 shadow root 的祖先
            if node is None:
                break
            sr = getattr(node, "shadow_root", None)
            if sr:
                iframe = sr.ele("tag:iframe", timeout=2)
                if iframe:
                    challenge_iframe = iframe
                    break
            node = node.parent()
        if not challenge_iframe:                # b) 直接取 .cf-turnstile 组件的 shadow root
            widget = tab.ele('css:.cf-turnstile', timeout=2)
            if widget:
                sr = getattr(widget, "shadow_root", None)
                if sr:
                    challenge_iframe = sr.ele("tag:iframe", timeout=2)
        if not challenge_iframe:                # c) 按 src 匹配 cloudflare/turnstile iframe
            for sel in (
                'xpath://iframe[contains(@src, "cloudflare") or contains(@src, "turnstile") or contains(@src, "challenge")]',
                'css:iframe[src*="challenges.cloudflare.com"]',
                'css:iframe[src*="turnstile"]',
                'tag:iframe',
            ):
                try:
                    f = tab.ele(sel, timeout=2)
                    if f:
                        challenge_iframe = f
                        break
                except Exception:
                    continue
    except Exception:
        challenge_iframe = None

    if not challenge_iframe:
        raise RuntimeError("turnstile_iframe_missing")

    patch_source = TURNSTILE_PATCH_PATH.read_text(encoding="utf-8")
    challenge_iframe.run_js(patch_source)
    diagnostics = challenge_iframe.run_js(
        """
        const probe = new MouseEvent('lunes-screenxy-probe', {
          clientX: 7,
          clientY: 9,
        });
        return {
          patch: window.__lunesScreenXYPatchVersion || '',
          eventScreenX: probe.screenX,
          eventScreenY: probe.screenY,
          patchActive: probe.screenX > 50 && probe.screenY > 50,
        };
        """
    )

    # 定位并点击 checkbox（增加兜底，避免 body shadow 缺失即崩溃）
    body = challenge_iframe.ele("tag:body", timeout=3)
    body_shadow = body.shadow_root if body else None
    button = None
    if body_shadow:
        button = body_shadow.ele("tag:input", timeout=3) or body_shadow.ele("css:input[type=checkbox]", timeout=3)
    if not button and body:
        button = body.ele("tag:input", timeout=3) or body.ele("css:input[type=checkbox]", timeout=3)
    if not button:
        try:
            challenge_iframe.click(by_js=False)          # 兜底：直接点 iframe
            return diagnostics if isinstance(diagnostics, dict) else {}
        except Exception:
            raise RuntimeError("turnstile_button_missing")

    button.click(by_js=False)
    return diagnostics if isinstance(diagnostics, dict) else {}


def solve_turnstile(tab) -> tuple[bool, float, str]:
    started = time.monotonic()
    if len(get_turnstile_token(tab)) > 20:
        return True, 0.0, "automatic"

    print(
        "[Turnstile] Starting patched fast path "
        f"({TURNSTILE_FAST_TIMEOUT_SECONDS:g}s)"
    )
    clicked = False
    fast_window_reported = False
    deadline = started + TURNSTILE_TOTAL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        token = get_turnstile_token(tab)
        if len(token) > 20:
            duration = time.monotonic() - started
            mode = (
                "screenxy_fast"
                if duration <= TURNSTILE_FAST_TIMEOUT_SECONDS
                else "screenxy_wait"
            )
            print(f"[Turnstile] Token received in {duration:.2f}s")
            return True, duration, mode

        elapsed = time.monotonic() - started
        if elapsed >= TURNSTILE_FAST_TIMEOUT_SECONDS and not fast_window_reported:
            print("[Turnstile] Five-second window elapsed; continuing token polling")
            fast_window_reported = True

        if clicked:
            time.sleep(TOKEN_POLL_SECONDS)
            continue

        try:
            diagnostics = patch_and_click_turnstile(tab)
            print(f"[Turnstile] Iframe patch diagnostics: {diagnostics}")
            clicked = True
            time.sleep(1)
            take_screenshot(tab, FAST_CLICK_SCREENSHOT_PATH)
        except Exception as exc:
            print(
                f"[Turnstile] Widget context unavailable; retrying: "
                f"{type(exc).__name__}: {exc}"
            )
            time.sleep(TOKEN_POLL_SECONDS)

    duration = time.monotonic() - started
    print(f"[Turnstile] Token missing after {duration:.2f}s")
    return False, duration, "failed"


def human_type(element, value: str) -> None:
    element.clear()
    for character in value:
        element.input(character, clear=False)
        time.sleep(random.uniform(0.04, 0.12))


def fill_login_form(tab) -> None:
    email = tab.ele(
        "css:input#email, input[name='email'], input[type='email']", timeout=20
    )
    password = tab.ele(
        "css:input#password, input[name='password'], input[type='password']",
        timeout=20,
    )
    if not email or not password:
        raise RuntimeError("login_form_missing")
    human_type(email, EMAIL)
    time.sleep(random.uniform(0.3, 0.7))
    human_type(password, PASSWORD)
    time.sleep(random.uniform(0.6, 1.2))


def login(tab) -> tuple[bool, str | None, dict]:
    navigation_ok, navigation_error = navigate_with_retry(tab, TARGET_URL)
    if not navigation_ok:
        return False, navigation_error, {}

    if is_authenticated_target(tab):
        take_success_screenshot(tab)
        return True, None, {"turnstile_mode": "not_required"}

    try:
        fill_login_form(tab)
    except Exception as exc:
        return False, f"login_form_missing:{type(exc).__name__}", {}

    solved, duration, mode = solve_turnstile(tab)
    details = {
        "turnstile_solved": solved,
        "turnstile_mode": mode,
        "turnstile_seconds": round(duration, 2),
    }
    if not solved:
        return False, "turnstile_token_missing", details

    try:
        submit = tab.ele("css:button[type='submit']", timeout=10)
        if not submit:
            raise RuntimeError("submit_button_missing")
        submit.click()
    except Exception as exc:
        return False, f"submit_failed:{type(exc).__name__}", details

    time.sleep(10)
    network_error = browser_network_error(tab)
    if network_error:
        return False, f"browser_network_error:{network_error}", details
    if has_upstream_error(tab):
        return False, "upstream_server_error", details
    if "/login" in tab.url:
        return False, "login_rejected", details

    if SERVER_ID and f"/servers/{SERVER_ID}" not in tab.url:
        navigation_ok, navigation_error = navigate_with_retry(tab, TARGET_URL)
        if not navigation_ok:
            return False, navigation_error, details

    if not is_authenticated_target(tab):
        return False, "authenticated_page_not_verified", details
    take_success_screenshot(tab)
    return True, None, details


def run_browser(proxy_server: str) -> tuple[bool, str | None]:
    from DrissionPage import Chromium, ChromiumOptions

    if not TURNSTILE_PATCH_PATH.is_file():
        error = "turnstile_extension_missing"
        save_result(None, False, error)
        return False, error

    options = ChromiumOptions(read_file=False).auto_port()
    options.add_extension(str(TURNSTILE_EXTENSION_DIR))
    options.set_argument("--window-size=1440,900")
    if BROWSER_PATH:
        options.set_browser_path(BROWSER_PATH)
    if proxy_server:
        options.set_proxy(proxy_server)
        print("[Browser] Proxy enabled")
    else:
        print("[Browser] Direct connection")

    browser = None
    try:
        browser = Chromium(options)
        tab = browser.latest_tab
        try:
            tab.get("https://api.ipify.org/?format=json", retry=0, timeout=20)
            exit_response = page_text(tab)
            exit_ip = parse_exit_ip(exit_response)
            if not exit_ip:
                network_error = browser_network_error(tab)
                reason = network_error or "invalid_exit_response"
                error = f"browser_proxy_check_failed:{reason}"
                print(f"[Browser] {error}: {exit_response[:200]!r}")
                save_result(tab, False, error)
                return False, error
            print(f"[Browser] Exit IP: {exit_ip}")
        except Exception as exc:
            error = f"browser_proxy_check_failed:{type(exc).__name__}"
            print(f"[Browser] {error}: {exc}")
            save_result(tab, False, error)
            return False, error
        success, error, details = login(tab)
        save_result(tab, success, error, **details)
        return success, error
    except Exception as exc:
        error = f"browser_exception:{type(exc).__name__}"
        print(f"[Browser] {error}: {exc}")
        save_result(None, False, error)
        return False, error
    finally:
        if browser is not None:
            try:
                browser.quit()
            except Exception:
                pass


def run_attempts() -> int:
    mode = "proxy" if PROXY_SERVER else "direct"
    print(f"[Browser] Connection mode: {mode}")
    success, _ = run_browser(PROXY_SERVER)
    return 0 if success else 1


def main() -> int:
    if not EMAIL or not PASSWORD:
        save_result(None, False, "credentials_missing")
        return 1
    if TURNSTILE_FAST_TIMEOUT_SECONDS <= 0:
        save_result(None, False, "invalid_fast_timeout")
        return 1

    return run_attempts()


if __name__ == "__main__":
    sys.exit(main())

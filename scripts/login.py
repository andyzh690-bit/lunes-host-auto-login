#!/usr/bin/env python3
"""Lunes Host login automation using SeleniumBase UC/CDP mode."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
SERVER_ID = os.getenv("SERVER_ID", "").strip()
EMAIL = os.getenv("LOGIN_EMAIL", "").strip()
PASSWORD = os.getenv("LOGIN_PASSWORD", "")
PROXY_SERVER = os.getenv("PROXY_SERVER", "").strip()

LOGIN_URL = "https://betadash.lunes.host/login"
TARGET_URL = (
    f"https://betadash.lunes.host/servers/{SERVER_ID}"
    if SERVER_ID
    else LOGIN_URL
)

ARTIFACTS_DIR = ROOT_DIR / "artifacts"
SCREENSHOT_PATH = ARTIFACTS_DIR / "screenshots" / "login-result.png"
RESULT_PATH = ARTIFACTS_DIR / "login-result.json"
TURNSTILE_EXTENSION_DIR = ROOT_DIR / "extensions" / "turnstile-screenxy"

NAVIGATION_ATTEMPTS = 3
NAVIGATION_RETRY_SECONDS = 10
TURNSTILE_FAST_TIMEOUT_SECONDS = float(
    os.getenv("TURNSTILE_FAST_TIMEOUT_SECONDS", "5")
)
TURNSTILE_FALLBACK_ATTEMPTS = 2
TURNSTILE_FALLBACK_TIMEOUT_SECONDS = 10
TOKEN_POLL_SECONDS = 0.25


def save_result(sb, success: bool, error: str | None = None, **details) -> None:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)

    url = ""
    if sb is not None:
        try:
            url = sb.get_current_url()
        except Exception:
            pass
        try:
            sb.save_screenshot(str(SCREENSHOT_PATH))
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


def has_upstream_error(sb) -> bool:
    try:
        title = (sb.get_title() or "").lower()
        source = (sb.get_page_source() or "")[:10000].lower()
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


def navigate_with_retry(sb, url: str) -> tuple[bool, str | None]:
    last_error = "navigation_failed"
    for attempt in range(1, NAVIGATION_ATTEMPTS + 1):
        try:
            if getattr(sb, "_lunes_cdp_active", False):
                sb.cdp.open(url)
            else:
                sb.activate_cdp_mode(url)
                sb._lunes_cdp_active = True
            sb.sleep(4)
            if not has_upstream_error(sb):
                return True, None
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


def get_turnstile_token(sb) -> str:
    expression = """(() => {
        const names = ['cf-turnstile-response', 'g-recaptcha-response'];
        for (const name of names) {
          const element = document.querySelector(`[name="${name}"]`);
          if (element && element.value) return element.value;
        }
        return '';
    })()"""
    try:
        value = sb.execute_script(expression)
        if value is None:
            value = sb.execute_script(f"return {expression}")
        return value or ""
    except Exception:
        return ""


def wait_for_turnstile(sb, timeout: float) -> bool:
    deadline = time.monotonic() + max(0, timeout)
    while True:
        if get_turnstile_token(sb):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(TOKEN_POLL_SECONDS, remaining))


def get_turnstile_click_info(sb) -> dict:
    expression = """(() => {
        const roots = [document];
        const elements = [...document.querySelectorAll('*')];
        for (const element of elements) {
          if (element.shadowRoot) roots.push(element.shadowRoot);
        }

        const candidates = [];
        for (const root of roots) {
          candidates.push(...root.querySelectorAll(
            'iframe[src*="challenges.cloudflare.com"], ' +
            'iframe[src*="turnstile"], .cf-turnstile, [data-sitekey]'
          ));
        }

        let target = candidates.find((element) => {
          const rect = element.getBoundingClientRect();
          return rect.width >= 250 && rect.height >= 50;
        });

        if (!target) {
          let node = document.querySelector('[name="cf-turnstile-response"]');
          for (let index = 0; node && index < 6; index += 1) {
            const rect = node.getBoundingClientRect();
            if (rect.width >= 250 && rect.height >= 50) {
              target = node;
              break;
            }
            node = node.parentElement;
          }
        }

        const info = {
          patch: window.__lunesScreenXYPatchVersion || '',
          candidates: candidates.length,
          innerWidth: window.innerWidth,
          innerHeight: window.innerHeight,
          outerWidth: window.outerWidth,
          outerHeight: window.outerHeight,
        };
        if (!target) return info;

        const rect = target.getBoundingClientRect();
        const borderX = Math.max(0, (window.outerWidth - window.innerWidth) / 2);
        const chromeY = Math.max(0, window.outerHeight - window.innerHeight);
        info.rect = {
          x: Math.round(rect.x),
          y: Math.round(rect.y),
          width: Math.round(rect.width),
          height: Math.round(rect.height),
        };
        info.x = Math.round(window.screenX + borderX + rect.left + 22);
        info.y = Math.round(
          window.screenY + chromeY + rect.top + rect.height / 2
        );
        return info;
    })()"""
    try:
        value = sb.execute_script(expression)
        if value is None:
            value = sb.execute_script(f"return {expression}")
        return value if isinstance(value, dict) else {}
    except Exception as exc:
        print(f"[Turnstile] Coordinate detection failed: {exc}")
        return {}


def solve_turnstile(sb) -> tuple[bool, float, str]:
    """Try the screen-coordinate patched click first, with a five-second window."""
    started = time.monotonic()
    if get_turnstile_token(sb):
        return True, 0.0, "automatic"

    print(
        "[Turnstile] Starting patched fast path "
        f"({TURNSTILE_FAST_TIMEOUT_SECONDS:g}s)"
    )
    click_info = get_turnstile_click_info(sb)
    print(f"[Turnstile] Screen-coordinate diagnostics: {click_info}")
    try:
        if "x" in click_info and "y" in click_info:
            sb.uc_gui_click_x_y(
                click_info["x"], click_info["y"], timeframe=0.35
            )
        else:
            sb.uc_gui_click_captcha()
    except Exception as exc:
        print(f"[Turnstile] Fast click failed: {exc}")
        try:
            sb.uc_gui_click_captcha()
        except Exception as fallback_exc:
            print(f"[Turnstile] Auto-detected click failed: {fallback_exc}")

    elapsed = time.monotonic() - started
    if wait_for_turnstile(sb, TURNSTILE_FAST_TIMEOUT_SECONDS - elapsed):
        duration = time.monotonic() - started
        print(f"[Turnstile] Fast path succeeded in {duration:.2f}s")
        return True, duration, "screenxy_fast"

    for attempt in range(1, TURNSTILE_FALLBACK_ATTEMPTS + 1):
        print(
            "[Turnstile] Starting compatibility fallback "
            f"{attempt}/{TURNSTILE_FALLBACK_ATTEMPTS}"
        )
        try:
            sb.solve_captcha()
        except Exception as exc:
            print(f"[Turnstile] CDP fallback failed: {exc}")
        try:
            sb.uc_gui_click_captcha(blind=True)
        except Exception as exc:
            print(f"[Turnstile] Blind fallback failed: {exc}")
        if wait_for_turnstile(sb, TURNSTILE_FALLBACK_TIMEOUT_SECONDS):
            duration = time.monotonic() - started
            print(f"[Turnstile] Fallback succeeded in {duration:.2f}s")
            return True, duration, "fallback"

    duration = time.monotonic() - started
    print(f"[Turnstile] Token missing after {duration:.2f}s")
    return False, duration, "failed"


def fill_login_form(sb) -> None:
    email_selector = "input#email, input[name='email'], input[type='email']"
    password_selector = (
        "input#password, input[name='password'], input[type='password']"
    )
    sb.wait_for_element_visible(email_selector, timeout=20)
    sb.wait_for_element_visible(password_selector, timeout=20)
    sb.type(email_selector, EMAIL)
    sb.type(password_selector, PASSWORD)


def login(sb) -> tuple[bool, str | None, dict]:
    navigation_ok, navigation_error = navigate_with_retry(sb, TARGET_URL)
    if not navigation_ok:
        return False, navigation_error, {}

    current_url = sb.get_current_url()
    if "/login" not in current_url and (
        not SERVER_ID or f"/servers/{SERVER_ID}" in current_url
    ):
        print("[Login] Existing session is valid")
        return True, None, {"turnstile_mode": "not_required"}

    try:
        fill_login_form(sb)
    except Exception as exc:
        return False, f"login_form_missing:{type(exc).__name__}", {}

    solved, duration, mode = solve_turnstile(sb)
    details = {
        "turnstile_solved": solved,
        "turnstile_mode": mode,
        "turnstile_seconds": round(duration, 2),
    }

    try:
        sb.click("button[type='submit']", timeout=10)
    except Exception as exc:
        return False, f"submit_failed:{type(exc).__name__}", details

    sb.sleep(10)
    if has_upstream_error(sb):
        return False, "upstream_server_error", details

    current_url = sb.get_current_url()
    if "/login" in current_url:
        error = "login_rejected"
        if not solved and not get_turnstile_token(sb):
            error = "turnstile_token_missing"
        return False, error, details

    if SERVER_ID and f"/servers/{SERVER_ID}" not in current_url:
        navigation_ok, navigation_error = navigate_with_retry(sb, TARGET_URL)
        if not navigation_ok:
            return False, navigation_error, details
        current_url = sb.get_current_url()

    if SERVER_ID and f"/servers/{SERVER_ID}" not in current_url:
        return False, "server_page_not_reached", details
    if has_upstream_error(sb):
        return False, "upstream_server_error", details

    return True, None, details


def run_browser(proxy_server: str) -> tuple[bool, str | None]:
    from seleniumbase import SB

    if not TURNSTILE_EXTENSION_DIR.is_dir():
        error = "turnstile_extension_missing"
        save_result(None, False, error)
        return False, error

    options = {
        "uc": True,
        "test": True,
        "locale": "en",
        "xvfb": True,
        "xvfb_metrics": "1366,900",
        "extension_dir": str(TURNSTILE_EXTENSION_DIR),
    }
    if proxy_server:
        options["proxy"] = proxy_server
        print("[Browser] Proxy enabled")
    else:
        print("[Browser] Direct connection")

    try:
        with SB(**options) as sb:
            success, error, details = login(sb)
            save_result(sb, success, error, **details)
            return success, error
    except Exception as exc:
        error = f"browser_exception:{type(exc).__name__}"
        print(f"[Browser] {error}: {exc}")
        save_result(None, False, error)
        return False, error


def main() -> int:
    if not EMAIL or not PASSWORD:
        save_result(None, False, "credentials_missing")
        return 1
    if TURNSTILE_FAST_TIMEOUT_SECONDS <= 0:
        save_result(None, False, "invalid_fast_timeout")
        return 1

    connection_attempts = [PROXY_SERVER] if PROXY_SERVER else [""]
    if PROXY_SERVER:
        connection_attempts.append("")

    for index, proxy_server in enumerate(connection_attempts, start=1):
        print(
            f"[Browser] Connection attempt {index}/{len(connection_attempts)} "
            f"({'proxy' if proxy_server else 'direct'})"
        )
        success, error = run_browser(proxy_server)
        if success:
            return 0
        if index < len(connection_attempts):
            print(f"[Browser] Retrying with direct connection after: {error}")

    return 1


if __name__ == "__main__":
    sys.exit(main())

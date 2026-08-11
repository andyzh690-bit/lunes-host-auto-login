#!/usr/bin/env python3
"""Lunes Host login automation using DrissionPage and a Turnstile patch."""

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
SCREENSHOT_DIR = ARTIFACTS_DIR / "screenshots"
SCREENSHOT_PATH = SCREENSHOT_DIR / "login-result.png"
FAST_CLICK_SCREENSHOT_PATH = SCREENSHOT_DIR / "turnstile-fast-click.png"
RESULT_PATH = ARTIFACTS_DIR / "login-result.json"
TURNSTILE_EXTENSION_DIR = ROOT_DIR / "extensions" / "turnstile-screenxy"
TURNSTILE_PATCH_PATH = TURNSTILE_EXTENSION_DIR / "screenxy.js"

NAVIGATION_ATTEMPTS = 3
NAVIGATION_RETRY_SECONDS = 10
TURNSTILE_FAST_TIMEOUT_SECONDS = float(
    os.getenv("TURNSTILE_FAST_TIMEOUT_SECONDS", "5")
)
TURNSTILE_FALLBACK_ATTEMPTS = 2
TURNSTILE_FALLBACK_TIMEOUT_SECONDS = 10
TOKEN_POLL_SECONDS = 0.25


def take_screenshot(tab, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tab.get_screenshot(path=str(path.parent), name=path.name, full_page=True)


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


def navigate_with_retry(tab, url: str) -> tuple[bool, str | None]:
    last_error = "navigation_failed"
    for attempt in range(1, NAVIGATION_ATTEMPTS + 1):
        try:
            tab.get(url, retry=0, timeout=30)
            time.sleep(4)
            if not has_upstream_error(tab):
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


def get_turnstile_token(tab) -> str:
    script = """
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


def wait_for_turnstile(tab, timeout: float) -> bool:
    deadline = time.monotonic() + max(0, timeout)
    while True:
        if get_turnstile_token(tab):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(TOKEN_POLL_SECONDS, remaining))


def patch_and_click_turnstile(tab) -> dict:
    tab.run_js("try { turnstile.reset(); } catch (error) {}")
    time.sleep(0.25)

    response = tab.ele("@name=cf-turnstile-response", timeout=3)
    if not response:
        raise RuntimeError("turnstile_response_missing")
    wrapper = response.parent()
    shadow = wrapper.shadow_root
    if not shadow:
        raise RuntimeError("turnstile_shadow_root_missing")
    challenge_iframe = shadow.ele("tag:iframe", timeout=3)
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

    body = challenge_iframe.ele("tag:body", timeout=3)
    body_shadow = body.shadow_root if body else None
    if not body_shadow:
        raise RuntimeError("turnstile_body_shadow_root_missing")
    button = body_shadow.ele("tag:input", timeout=3)
    if not button:
        raise RuntimeError("turnstile_button_missing")
    button.click()
    return diagnostics if isinstance(diagnostics, dict) else {}


def solve_turnstile(tab) -> tuple[bool, float, str]:
    started = time.monotonic()
    if get_turnstile_token(tab):
        return True, 0.0, "automatic"

    print(
        "[Turnstile] Starting patched fast path "
        f"({TURNSTILE_FAST_TIMEOUT_SECONDS:g}s)"
    )
    try:
        diagnostics = patch_and_click_turnstile(tab)
        print(f"[Turnstile] Iframe patch diagnostics: {diagnostics}")
        time.sleep(1)
        take_screenshot(tab, FAST_CLICK_SCREENSHOT_PATH)
    except Exception as exc:
        print(f"[Turnstile] Fast click failed: {type(exc).__name__}: {exc}")

    elapsed = time.monotonic() - started
    if wait_for_turnstile(tab, TURNSTILE_FAST_TIMEOUT_SECONDS - elapsed):
        duration = time.monotonic() - started
        print(f"[Turnstile] Fast path succeeded in {duration:.2f}s")
        return True, duration, "screenxy_fast"

    for attempt in range(1, TURNSTILE_FALLBACK_ATTEMPTS + 1):
        print(
            "[Turnstile] Starting patched fallback "
            f"{attempt}/{TURNSTILE_FALLBACK_ATTEMPTS}"
        )
        try:
            diagnostics = patch_and_click_turnstile(tab)
            print(f"[Turnstile] Fallback diagnostics: {diagnostics}")
        except Exception as exc:
            print(
                f"[Turnstile] Fallback click failed: "
                f"{type(exc).__name__}: {exc}"
            )
        if wait_for_turnstile(tab, TURNSTILE_FALLBACK_TIMEOUT_SECONDS):
            duration = time.monotonic() - started
            print(f"[Turnstile] Fallback succeeded in {duration:.2f}s")
            return True, duration, "fallback"

    duration = time.monotonic() - started
    print(f"[Turnstile] Token missing after {duration:.2f}s")
    return False, duration, "failed"


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
    email.input(EMAIL, clear=True)
    password.input(PASSWORD, clear=True)


def login(tab) -> tuple[bool, str | None, dict]:
    navigation_ok, navigation_error = navigate_with_retry(tab, TARGET_URL)
    if not navigation_ok:
        return False, navigation_error, {}

    current_url = tab.url
    if "/login" not in current_url and (
        not SERVER_ID or f"/servers/{SERVER_ID}" in current_url
    ):
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
    if has_upstream_error(tab):
        return False, "upstream_server_error", details
    if "/login" in tab.url:
        return False, "login_rejected", details

    if SERVER_ID and f"/servers/{SERVER_ID}" not in tab.url:
        navigation_ok, navigation_error = navigate_with_retry(tab, TARGET_URL)
        if not navigation_ok:
            return False, navigation_error, details

    if SERVER_ID and f"/servers/{SERVER_ID}" not in tab.url:
        return False, "server_page_not_reached", details
    return True, None, details


def run_browser(proxy_server: str) -> tuple[bool, str | None]:
    from DrissionPage import Chromium, ChromiumOptions

    if not TURNSTILE_PATCH_PATH.is_file():
        error = "turnstile_extension_missing"
        save_result(None, False, error)
        return False, error

    options = ChromiumOptions(read_file=False).auto_port()
    options.add_extension(str(TURNSTILE_EXTENSION_DIR))
    options.set_argument("--no-sandbox")
    options.set_argument("--disable-dev-shm-usage")
    options.set_argument("--window-size=1366,900")
    if proxy_server:
        options.set_argument(f"--proxy-server={proxy_server}")
        print("[Browser] Proxy enabled")
    else:
        print("[Browser] Direct connection")

    browser = None
    try:
        browser = Chromium(options)
        tab = browser.latest_tab
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


def main() -> int:
    if not EMAIL or not PASSWORD:
        save_result(None, False, "credentials_missing")
        return 1
    if TURNSTILE_FAST_TIMEOUT_SECONDS <= 0:
        save_result(None, False, "invalid_fast_timeout")
        return 1

    display = None
    try:
        if sys.platform.startswith("linux") and not os.getenv("DISPLAY"):
            from pyvirtualdisplay import Display

            display = Display(visible=False, size=(1366, 900))
            display.start()
        return run_attempts()
    finally:
        if display is not None:
            display.stop()


if __name__ == "__main__":
    sys.exit(main())

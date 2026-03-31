"""
Lunes Host 自动登录脚本
使用 Camoufox 反检测浏览器 + 人类鼠标移动点击 Cloudflare Turnstile

使用方法:
python scripts/login.py

依赖:
pip install playwright
playwright install firefox
"""
import os
import sys
import json
import time
import random
from playwright.sync_api import sync_playwright

SERVER_ID = os.getenv("SERVER_ID", "")
EMAIL = os.getenv("LOGIN_EMAIL")
PASSWORD = os.getenv("LOGIN_PASSWORD")

if not EMAIL or not PASSWORD:
    print("错误: 必须设置 LOGIN_EMAIL 和 LOGIN_PASSWORD 环境变量")
    print("使用方法:")
    print("  LOGIN_EMAIL=user@example.com LOGIN_PASSWORD=pass python scripts/login.py")
    print("  SERVER_ID=73546 LOGIN_EMAIL=user@example.com LOGIN_PASSWORD=pass python scripts/login.py")
    sys.exit(1)

if SERVER_ID:
    TARGET_URL = f"https://betadash.lunes.host/servers/{SERVER_ID}"
else:
    TARGET_URL = "https://betadash.lunes.host/login"

if sys.platform == "win32":
    default_camoufox = "camoufox.exe"
else:
    default_camoufox = "camoufox"

_env_camoufox = os.getenv("CAMOUFOX_PATH")
if _env_camoufox:
    CAMOUFOX_PATH = _env_camoufox
else:
    CAMOUFOX_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "camoufox", default_camoufox)

def human_mouse_move(page, x, y, steps=15):
    """模拟人类鼠标移动（带随机抖动）"""
    for _ in range(steps):
        target_x = x + random.randint(-5, 5)
        target_y = y + random.randint(-5, 5)
        page.mouse.move(target_x, target_y)
        time.sleep(random.randint(20, 50) / 1000)
    return x, y

def click_turnstile(page, max_wait=12):
    """点击 Cloudflare Turnstile 验证框"""
    print("[Turnstile] 查找验证框...")

    turnstile_box = None
    selectors = [
        'iframe[src*="turnstile"]',
        'iframe[class*="turnstile"]',
        '[data-sitekey]',
        '.cf-turnstile',
        '[class*="turnstile"]'
    ]

    for selector in selectors:
        try:
            elem = page.query_selector(selector)
            if elem:
                turnstile_box = elem.bounding_box()
                if turnstile_box:
                    print(f"[Turnstile] 找到: {selector}")
                    break
        except:
            continue

    if not turnstile_box:
        print("[Turnstile] 未找到验证框")
        return False

    center_x = turnstile_box['x'] + turnstile_box['width'] / 2
    center_y = turnstile_box['y'] + turnstile_box['height'] / 2

    print(f"[Turnstile] 移动鼠标到 ({center_x:.0f}, {center_y:.0f})")
    human_mouse_move(page, center_x, center_y)

    print("[Turnstile] 等待人类犹豫时间...")
    time.sleep(random.randint(300, 800) / 1000)

    print("[Turnstile] 点击验证框...")
    page.mouse.click(center_x, center_y)

    print(f"[Turnstile] 等待验证完成 ({max_wait}秒)...")
    time.sleep(max_wait)

    return True

def login():
    """执行登录"""
    camoufox_exe = CAMOUFOX_PATH
    if not os.path.isabs(camoufox_exe):
        camoufox_exe = os.path.abspath(camoufox_exe)

    if not os.path.exists(camoufox_exe):
        print(f"错误: Camoufox 浏览器未找到: {camoufox_exe}")
        print("请先下载 Camoufox 浏览器")
        sys.exit(1)

    print("=" * 50)
    print("Lunes Host 自动登录")
    print("=" * 50)
    print(f"目标: {TARGET_URL}")
    print(f"账号: {EMAIL}")
    print(f"浏览器: {camoufox_exe}")
    print("=" * 50)

    headless = os.getenv("HEADLESS", "true").lower() == "true"
    if not os.environ.get("DISPLAY") and sys.platform != "win32":
        headless = True
        print("[浏览器] 无 DISPLAY 环境变量，自动使用无头模式")

    with sync_playwright() as p:
        print(f"[浏览器] 启动 Camoufox (headless={headless})...")

        browser = p.firefox.launch(
            executable_path=camoufox_exe,
            headless=headless
        )

        context = browser.new_context(
            viewport={'width': 1440, 'height': 900}
        )

        page = context.new_page()

        print(f"[浏览器] 访问: {TARGET_URL}")
        page.goto(TARGET_URL, timeout=30000)
        time.sleep(5)

        print("[登录] 点击 Turnstile 验证框...")
        click_turnstile(page)

        print("[登录] 填写表单...")
        try:
            page.fill('input[name="email"], input[type="email"]', EMAIL, timeout=5000)
            page.fill('input[name="password"], input[type="password"]', PASSWORD, timeout=5000)
        except Exception as e:
            print(f"[登录] 表单填写失败: {e}")

        print("[登录] 点击登录按钮...")
        try:
            page.click('button[type="submit"]', timeout=5000)
        except Exception as e:
            print(f"[登录] 点击按钮失败: {e}")

        print("[登录] 等待页面跳转...")
        time.sleep(8)

        result_url = page.url
        print(f"[登录] 最终 URL: {result_url}")

        page_content = page.content()
        page_title = page.title()
        print(f"[登录] 页面标题: {page_title}")

        if "Internal Server Error" in page_content:
            success = False
            print("[登录] 检测到服务器错误页面")
        elif "500" in page_title or "Error" in page_title:
            success = False
            print("[登录] 检测到错误页面标题")
        elif "login" in result_url and "servers" not in result_url:
            success = False
            print("[登录] 仍在登录页面")
        elif "error" in page_content[:2000].lower():
            success = False
            print("[登录] 检测到错误内容")
        elif "servers" in result_url:
            if SERVER_ID and str(SERVER_ID) in result_url:
                success = True
                print(f"[登录] 成功到达目标服务器页面: {SERVER_ID}")
            else:
                success = True
                print("[登录] 到达服务器页面")
        elif "dashboard" in result_url:
            success = True
        elif "account" in result_url:
            success = True
        else:
            success = False

        if success:
            print("=" * 50)
            print(">> 登录成功!")
            print("=" * 50)
        else:
            print("=" * 50)
            print(">> 登录失败，请检查截图")
            print("=" * 50)

        screenshot_path = os.path.join(os.path.dirname(__file__), "..", "artifacts", "screenshots", "login-result.png")
        os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
        try:
            page.screenshot(path=screenshot_path, full_page=True)
            print(f"[截图] 已保存: {screenshot_path}")
        except Exception as e:
            print(f"[截图] 保存失败: {e}")

        result_json = {
            "success": success,
            "url": result_url,
            "email": EMAIL,
            "server_id": SERVER_ID
        }
        with open(os.path.join(os.path.dirname(__file__), "..", "artifacts", "login-result.json"), "w") as f:
            json.dump(result_json, f)
        print(f"[结果] {result_json}")

        browser.close()

        return 0 if success else 1

if __name__ == "__main__":
    sys.exit(login())

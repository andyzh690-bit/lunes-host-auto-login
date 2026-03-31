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

TARGET_URL = os.getenv("LOGIN_URL", "https://betadash.lunes.host/login")
EMAIL = os.getenv("LOGIN_EMAIL", "boss@finte.site")
PASSWORD = os.getenv("LOGIN_PASSWORD", "Zm123123@@@")

if sys.platform == "win32":
    default_camoufox = "camoufox.exe"
else:
    default_camoufox = "camoufox"
CAMOUFOX_PATH = os.getenv("CAMOUFOX_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "camoufox", default_camoufox))

def human_mouse_move(page, x, y, steps=15):
    """模拟人类鼠标移动（带随机抖动）"""
    for _ in range(steps):
        target_x = x + random.randint(-5, 5)
        target_y = y + random.randint(-5, 5)
        page.mouse.move(target_x, target_y)
        time.sleep(random.randint(20, 50) / 1000)
    return x, y

def click_turnstile(page, max_wait=15):
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
    
    print("[Turnstile] 等待验证完成...")
    time.sleep(max_wait)
    
    return True

def login():
    """执行登录"""
    camoufox_exe = CAMOUFOX_PATH
    if not os.path.isabs(camoufox_exe):
        camoufox_exe = os.path.abspath(camoufox_exe)
    
    print(f"[调试] CAMOUFOX_PATH: {CAMOUFOX_PATH}")
    print(f"[调试] camoufox_exe: {camoufox_exe}")
    print(f"[调试] os.path.exists: {os.path.exists(camoufox_exe)}")
    
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
    
    with sync_playwright() as p:
        print("[浏览器] 启动 Camoufox...")
        
        browser = p.firefox.launch(
            executable_path=camoufox_exe,
            headless=False
        )
        
        context = browser.new_context(
            viewport={'width': 1440, 'height': 900}
        )
        
        page = context.new_page()
        
        print(f"[浏览器] 访问: {TARGET_URL}")
        page.goto(TARGET_URL, timeout=30000)
        time.sleep(8)
        
        print("[登录] 点击 Turnstile 验证框...")
        click_turnstile(page)
        
        print("[登录] 填写表单...")
        page.fill('input[name="email"], input[type="email"]', EMAIL)
        page.fill('input[name="password"], input[type="password"]', PASSWORD)
        
        print("[登录] 点击登录按钮...")
        page.click('button[type="submit"]')
        time.sleep(5)
        
        result_url = page.url
        print(f"[登录] 最终 URL: {result_url}")
        
        success = (
            "dashboard" in result_url or
            "account" in result_url or
            "manage" in result_url or
            result_url.endswith("/") and "login" not in result_url
        )
        
        if success:
            print("=" * 50)
            print(">> 登录成功!")
            print("=" * 50)
        else:
            print("=" * 50)
            print(">> 登录可能失败，请检查截图")
            print("=" * 50)
        
        screenshot_path = os.path.join(os.path.dirname(__file__), "..", "artifacts", "screenshots", "login-result.png")
        os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
        page.screenshot(path=screenshot_path, full_page=True)
        
        browser.close()
        
        return 0 if success else 1

if __name__ == "__main__":
    sys.exit(login())

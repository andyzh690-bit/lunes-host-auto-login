"""
Cloudflare Turnstile 绕过登录模板
使用 Camoufox 反检测浏览器 + 人类鼠标移动

使用方法:
1. 复制此文件到目标项目
2. 修改 SELECTORS 配置匹配目标网站
3. 设置环境变量运行

环境变量:
- LOGIN_URL: 登录页面URL
- LOGIN_EMAIL: 登录邮箱
- LOGIN_PASSWORD: 登录密码
- SUCCESS_URL_PATTERN: 成功后URL包含的关键字（多个用逗号分隔）
- HEADLESS: 无头模式（默认true）
"""
import os
import sys
import json
import time
import random
from playwright.sync_api import sync_playwright

# ============ 配置区域 - 根据目标网站修改 ============
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
        "failed",
        "invalid"
    ]
}

# ============ 核心逻辑 - 通常不需要修改 ============
URL = os.getenv("LOGIN_URL", "")
EMAIL = os.getenv("LOGIN_EMAIL", "")
PASSWORD = os.getenv("LOGIN_PASSWORD", "")
SUCCESS_PATTERNS = os.getenv("SUCCESS_URL_PATTERN", "").split(",") if os.getenv("SUCCESS_URL_PATTERN") else []

if not EMAIL or not PASSWORD or not URL:
    print("错误: 必须设置 LOGIN_URL, LOGIN_EMAIL, LOGIN_PASSWORD 环境变量")
    sys.exit(1)

def get_camoufox_path():
    """获取 Camoufox 浏览器路径"""
    if sys.platform == "win32":
        default = "camoufox.exe"
    else:
        default = "camoufox"
    
    env_path = os.getenv("CAMOUFOX_PATH")
    if env_path:
        return env_path
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "camoufox", default)

def human_mouse_move(page, x, y, steps=15):
    """模拟人类鼠标移动（带随机抖动）"""
    for _ in range(steps):
        target_x = x + random.randint(-5, 5)
        target_y = y + random.randint(-5, 5)
        page.mouse.move(target_x, target_y)
        time.sleep(random.randint(20, 50) / 1000)
    return x, y

def find_and_click_turnstile(page, max_wait=12):
    """查找并点击 Cloudflare Turnstile 验证框"""
    print("[Turnstile] 查找验证框...")
    
    for selector in CONFIG["turnstile_selectors"]:
        try:
            elem = page.query_selector(selector)
            if elem:
                box = elem.bounding_box()
                if box:
                    print(f"[Turnstile] 找到: {selector}")
                    center_x = box['x'] + box['width'] / 2
                    center_y = box['y'] + box['height'] / 2
                    
                    print(f"[Turnstile] 移动鼠标到 ({center_x:.0f}, {center_y:.0f})")
                    human_mouse_move(page, center_x, center_y)
                    
                    print("[Turnstile] 等待人类犹豫时间...")
                    time.sleep(random.randint(300, 800) / 1000)
                    
                    print("[Turnstile] 点击验证框...")
                    page.mouse.click(center_x, center_y)
                    
                    print(f"[Turnstile] 等待验证完成 ({max_wait}秒)...")
                    time.sleep(max_wait)
                    return True
        except:
            continue
    
    print("[Turnstile] 未找到验证框（可能页面无CF保护）")
    return False

def check_login_success(page):
    """检查登录是否成功"""
    url = page.url
    content = page.content()
    title = page.title()
    
    print(f"[结果] URL: {url}")
    print(f"[结果] 标题: {title}")
    
    # 检查错误指示器
    for indicator in CONFIG["error_indicators"]:
        if indicator.lower() in content[:3000].lower():
            if indicator == "Internal Server Error":
                print(f"[结果] 检测到错误: {indicator}")
                return False, url
    
    # 检查成功模式
    patterns = SUCCESS_PATTERNS if SUCCESS_PATTERNS else ["dashboard", "account", "home", "admin"]
    for pattern in patterns:
        if pattern.strip() and pattern.strip().lower() in url.lower():
            print(f"[结果] 匹配成功模式: {pattern}")
            return True, url
    
    # 检查是否仍在登录页
    if "login" in url.lower() and not any(p in url for p in ["next=", "redirect="]):
        print("[结果] 仍在登录页面")
        return False, url
    
    print("[结果] 未匹配成功模式，但无明显错误")
    return True, url

def login():
    """执行登录"""
    camoufox_path = get_camoufox_path()
    if not os.path.isabs(camoufox_path):
        camoufox_path = os.path.abspath(camoufox_path)
    
    if not os.path.exists(camoufox_path):
        print(f"错误: Camoufox 浏览器未找到: {camoufox_path}")
        print("请先下载: https://github.com/daijro/camoufox/releases")
        sys.exit(1)
    
    headless = os.getenv("HEADLESS", "true").lower() == "true"
    if not os.environ.get("DISPLAY") and sys.platform != "win32":
        headless = True
    
    print("=" * 50)
    print("CF Turnstile 绕过登录")
    print("=" * 50)
    print(f"目标: {URL}")
    print(f"账号: {EMAIL}")
    print(f"浏览器: {camoufox_path}")
    print("=" * 50)
    
    with sync_playwright() as p:
        print(f"[浏览器] 启动 Camoufox (headless={headless})...")
        browser = p.firefox.launch(
            executable_path=camoufox_path,
            headless=headless
        )
        
        context = browser.new_context(viewport={'width': 1440, 'height': 900})
        page = context.new_page()
        
        print(f"[浏览器] 访问: {URL}")
        page.goto(URL, timeout=30000)
        time.sleep(5)
        
        # 点击 Turnstile
        find_and_click_turnstile(page)
        
        # 填写表单
        print("[登录] 填写表单...")
        try:
            page.fill(CONFIG["email_selectors"], EMAIL, timeout=5000)
            page.fill(CONFIG["password_selectors"], PASSWORD, timeout=5000)
        except Exception as e:
            print(f"[登录] 表单填写: {e}")
        
        # 点击提交
        print("[登录] 提交登录...")
        try:
            submit = page.query_selector(CONFIG["submit_selectors"])
            if submit:
                submit.click(timeout=5000)
        except Exception as e:
            print(f"[登录] 提交按钮: {e}")
        
        print("[登录] 等待页面跳转...")
        time.sleep(10)
        
        # 检查结果
        success, final_url = check_login_success(page)
        
        # 保存截图
        screenshot_dir = os.path.join(os.path.dirname(__file__), "..", "artifacts", "screenshots")
        os.makedirs(screenshot_dir, exist_ok=True)
        screenshot_path = os.path.join(screenshot_dir, "login-result.png")
        page.screenshot(path=screenshot_path, full_page=True)
        print(f"[截图] 已保存: {screenshot_path}")
        
        # 保存结果
        result = {"success": success, "url": final_url, "email": EMAIL}
        result_path = os.path.join(os.path.dirname(__file__), "..", "artifacts", "login-result.json")
        with open(result_path, "w") as f:
            json.dump(result, f)
        
        print("=" * 50)
        print(f">> {'登录成功!' if success else '登录失败'}")
        print("=" * 50)
        
        browser.close()
        return 0 if success else 1

if __name__ == "__main__":
    sys.exit(login())

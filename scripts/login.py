#!/usr/bin/env python3
"""
Lunes Host 自动登录脚本
使用 Camoufox 反检测浏览器 + 人类鼠标移动点击 Cloudflare Turnstile
"""
import os
import sys
import json
import time
import random
import site
import asyncio
import subprocess
from pathlib import Path
from camoufox.async_api import AsyncCamoufox

sys.path.append(os.path.dirname(__file__))
from mouse_probe import install_mouse_probe, read_mouse_probe, probe_ok

def apply_mouse_patch() -> None:
    """
    启动前确保 screenX/screenY 补丁已应用。
    失败不阻断（打印警告），但会降低过盾概率。
    """
    script = Path(__file__).resolve().parent / "patch_playwright_mouse.py"
    if not script.exists():
        print("[浏览器] 未找到 patch_playwright_mouse.py，跳过鼠标补丁")
        return

    print("[浏览器] 应用 Playwright screenX/screenY 补丁...")
    try:
        r = subprocess.run(
            [sys.executable, str(script)],
            check=False,
            capture_output=True,
            text=True,
        )
        if r.stdout:
            print(r.stdout.strip())
        if r.returncode != 0:
            print(r.stderr.strip() if r.stderr else "[浏览器] 鼠标补丁失败")
        else:
            print("[浏览器] 鼠标补丁完成")
    except Exception as e:
        print(f"[浏览器] 鼠标补丁异常: {e}")

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

async def human_mouse_move(page, x, y, steps=15):
    """模拟人类鼠标移动（带随机抖动）"""
    for _ in range(steps):
        target_x = x + random.randint(-5, 5)
        target_y = y + random.randint(-5, 5)
        await page.mouse.move(target_x, target_y)
        await asyncio.sleep(random.randint(20, 50) / 1000)
    return x, y

async def get_turnstile_token(page, timeout_s=12) -> str:
    """读取 token，空字符串表示失败。"""
    js = r"""
    () => {
      const names = ['cf-turnstile-response', 'g-recaptcha-response'];
      for (const n of names) {
        const el = document.querySelector(`[name="${n}"]`);
        if (el && el.value) return el.value;
      }
      const ta = document.querySelector('textarea[name="cf-turnstile-response"]');
      if (ta && ta.value) return ta.value;
      return '';
    }
    """
    loop = max(1, int(timeout_s / 0.5))
    for _ in range(loop):
        try:
            token = await page.evaluate(js)
            if token:
                return token
        except:
            pass
        await asyncio.sleep(0.5)
    return ""

async def click_turnstile(page, max_wait=12):
    """点击 Cloudflare Turnstile 验证框"""
    print("[Turnstile] 安装鼠标探针...")
    await install_mouse_probe(page)

    print("[Turnstile] 查找验证框...")
    turnstile_box = None
    selectors = [
        "[data-sitekey]",
        "iframe[src*='turnstile']",
        "iframe[src*='challenges.cloudflare.com']",
        ".cf-turnstile",
        "#cf-turnstile",
    ]

    for sel in selectors:
        try:
            elem = page.locator(sel).first
            if await elem.count() > 0 and await elem.is_visible():
                box = await elem.bounding_box()
                if box and box.get("width", 0) > 5 and box.get("height", 0) > 5:
                    turnstile_box = box
                    print(f"[Turnstile] 找到: {sel}")
                    break
        except:
            continue

    if not turnstile_box:
        print("[Turnstile] 未找到验证框")
        return False

    click_x = turnstile_box['x'] + min(28, turnstile_box["width"] * 0.15) + random.uniform(-2, 2)
    click_y = turnstile_box['y'] + turnstile_box['height'] / 2 + random.uniform(-2, 2)

    print(f"[Turnstile] 移动鼠标到 ({click_x:.0f}, {click_y:.0f})")
    
    # 随机滚动一下页面，模拟人类阅读
    await page.evaluate(f"window.scrollBy(0, {random.randint(100, 300)})")
    await asyncio.sleep(random.uniform(0.5, 1.5))
    await page.evaluate(f"window.scrollBy(0, -{random.randint(50, 150)})")
    await asyncio.sleep(random.uniform(0.5, 1.5))

    await human_mouse_move(page, click_x, click_y, steps=25)

    print("[Turnstile] 等待人类犹豫时间...")
    await asyncio.sleep(random.randint(500, 1200) / 1000)

    print("[Turnstile] 模拟真实点击...")
    await page.mouse.down()
    await asyncio.sleep(random.randint(50, 150) / 1000)
    await page.mouse.up()
    await asyncio.sleep(random.randint(40, 100) / 1000)

    sample = await read_mouse_probe(page)
    print(f"[Turnstile] mouse probe: {sample}")
    if not probe_ok(sample):
        print("[Turnstile] 警告：screenX/screenY 可能仍异常（补丁未生效或 Camoufox 路径不同）")
    else:
        print("[Turnstile] mouse probe OK（screen 坐标非 0）")

    max_wait = 30
    print(f"[Turnstile] 等待验证完成 ({max_wait}秒)...")
    token = await get_turnstile_token(page, timeout_s=max_wait)
    if not token:
        print("[Turnstile] 警告：未能获取到验证 Token，可能被盾拦截。")
        return False

    print("[Turnstile] 验证通过！已成功获取 Token。")
    return True

async def login_async():
    """执行登录主逻辑 (异步)"""
    print("=" * 50)
    print("Lunes Host 自动登录")
    print("=" * 50)
    print(f"目标: {TARGET_URL}")
    print(f"账号: {EMAIL}")
    print("=" * 50)

    headless = os.getenv("HEADLESS", "true").lower() == "true"
    if not os.environ.get("DISPLAY") and sys.platform != "win32":
        headless = True
        print("[浏览器] 无 DISPLAY 环境变量，自动使用无头模式")

    apply_mouse_patch()

    print(f"[浏览器] 启动 Camoufox (headless={headless})...")

    # 使用 AsyncCamoufox 并完全使用 await
    async with AsyncCamoufox(
        headless=headless,
        enable_cache=True,
        geoip=False,
        humanize=True,
        window=(1280, 720)
    ) as browser:
        
        state_file = os.path.join(os.path.dirname(__file__), "..", "artifacts", "state.json")
        ctx_args = {
            "viewport": {"width": 1280, "height": 720},
        }
        if os.path.exists(state_file):
            print(f"[浏览器] 加载登录态: {state_file}")
            ctx_args["storage_state"] = state_file

        page = None
        ctx = None
        try:
            ctx = await browser.new_context(**ctx_args)
            page = await ctx.new_page()
        except Exception as e:
            print(f"[浏览器] 创建 page 失败，尝试 fallback: {e}")
            ctx_args["no_viewport"] = True
            ctx_args.pop("viewport", None)
            ctx = await browser.new_context(**ctx_args)
            page = await ctx.new_page()

        print(f"[浏览器] 访问: {TARGET_URL}")
        await page.goto(TARGET_URL, timeout=30000)
        await asyncio.sleep(5)

        print("[登录] 点击 Turnstile 验证框...")
        if not await click_turnstile(page):
            print("Turnstile 未通过（token 为空），终止登录")
            screenshot_path = os.path.join(os.path.dirname(__file__), "..", "artifacts", "screenshots", "login-result.png")
            os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
            await page.screenshot(path=screenshot_path, full_page=True)
            
            result_json = {
                "success": False,
                "url": page.url,
                "email": EMAIL,
                "server_id": SERVER_ID
            }
            with open(os.path.join(os.path.dirname(__file__), "..", "artifacts", "login-result.json"), "w") as f:
                json.dump(result_json, f)
            print(f"[结果] {result_json}")
            return 1

        print("[登录] 填写表单...")
        try:
            await page.fill('input[name="email"], input[type="email"]', EMAIL, timeout=5000)
            await page.fill('input[name="password"], input[type="password"]', PASSWORD, timeout=5000)
        except Exception as e:
            print(f"[登录] 表单填写失败: {e}")

        print("[登录] 点击登录按钮...")
        try:
            submit_btn = page.locator('button[type="submit"]').first
            if await submit_btn.count() > 0:
                await submit_btn.click(timeout=5000)
        except Exception as e:
            print(f"[登录] 点击按钮超时（可能页面已在跳转）: {e}")

        print("[登录] 等待页面跳转...")
        await asyncio.sleep(10)

        continue_btn = page.locator('button:has-text("Continue"), button:has-text("Dashboard")').first
        try:
            if await continue_btn.count() > 0 and await continue_btn.is_visible():
                print("[登录] 检测到继续按钮，点击...")
                await continue_btn.click(timeout=3000)
                await asyncio.sleep(5)
        except:
            pass

        await asyncio.sleep(5)

        result_url = page.url
        print(f"[登录] 最终 URL: {result_url}")

        page_content = await page.content()
        page_title = await page.title()
        print(f"[登录] 页面标题: {page_title}")

        success = False
        if "Internal Server Error" in page_content:
            success = False
            print("[登录] 检测到服务器错误页面")
        elif "500" in page_title:
            success = False
            print("[登录] 检测到500错误页面标题")
        elif "login" in result_url and "servers" not in result_url and "next=" not in result_url:
            success = False
            print("[登录] 仍在登录页面")
        elif "error" in page_content[:2000].lower() and "Internal Server Error" in page_content:
            success = False
            print("[登录] 检测到错误内容")
        elif "servers" in result_url and "Internal Server Error" not in page_content:
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
        elif "next=/servers" in result_url:
            print("[登录] 检测到重定向到服务器页面，等待重定向...")
            await asyncio.sleep(3)
            result_url = page.url
            if "servers" in result_url and "Internal Server Error" not in await page.content():
                success = True
            else:
                success = False

        if success:
            print("=" * 50)
            print(">> 登录成功!")
            print("=" * 50)
            if ctx:
                await ctx.storage_state(path=state_file)
                print(f"[浏览器] 已保存登录态至: {state_file}")
        else:
            print("=" * 50)
            print(">> 登录失败，请检查截图")
            print("=" * 50)

        screenshot_path = os.path.join(os.path.dirname(__file__), "..", "artifacts", "screenshots", "login-result.png")
        os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
        try:
            await page.screenshot(path=screenshot_path, full_page=True)
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

        return 0 if success else 1

def login():
    """入口包装器"""
    return asyncio.run(login_async())

if __name__ == "__main__":
    sys.exit(login())

#!/usr/bin/env python3
"""页面内鼠标坐标探针：确认 click 事件的 screenX/screenY 是否非 0。"""

from __future__ import annotations

PROBE_JS = r"""
() => {
  if (window.__mouseProbeInstalled) return true;
  window.__mouseProbeInstalled = true;
  window.__lastMouseProbe = null;

  const handler = (e) => {
    window.__lastMouseProbe = {
      type: e.type,
      clientX: e.clientX,
      clientY: e.clientY,
      screenX: e.screenX,
      screenY: e.screenY,
      button: e.button,
      isTrusted: e.isTrusted,
      ts: Date.now(),
    };
    console.log('[mouse-probe]', JSON.stringify(window.__lastMouseProbe));
  };

  // 捕获阶段更稳
  window.addEventListener('mousedown', handler, true);
  window.addEventListener('mouseup', handler, true);
  window.addEventListener('click', handler, true);
  return true;
}
"""

READ_JS = r"""
() => window.__lastMouseProbe || null
"""


PAGE_SCREENXY_FALLBACK = r"""
() => {
  if (window.__screenXYFallback) return;
  window.__screenXYFallback = true;

  // 仅增强脚本可见事件属性；不能保证 isTrusted，但可改善部分检测
  const proto = MouseEvent.prototype;
  const cx = Object.getOwnPropertyDescriptor(proto, 'clientX');
  const cy = Object.getOwnPropertyDescriptor(proto, 'clientY');
  if (!cx || !cy) return;

  function fix(getterX, getterY, which) {
    return function() {
      const x = getterX.call(this);
      const y = getterY.call(this);
      const sx = (window.screenX || 0) + x;
      const sy = (window.screenY || 0) + y;
      return which === 'x' ? (sx || x || 1) : (sy || y || 1);
    };
  }

  try {
    Object.defineProperty(proto, 'screenX', {
      get: fix(cx.get, cy.get, 'x')
    });
    Object.defineProperty(proto, 'screenY', {
      get: fix(cx.get, cy.get, 'y')
    });
  } catch (e) {}
}
"""

async def install_screenxy_fallback(page):
    await page.add_init_script(PAGE_SCREENXY_FALLBACK)
    try:
        await page.evaluate(PAGE_SCREENXY_FALLBACK)
    except Exception:
        pass


async def install_mouse_probe(page) -> None:
    await install_screenxy_fallback(page)
    await page.add_init_script(PROBE_JS)
    # 若页面已打开，再即时安装一次
    try:
        await page.evaluate(PROBE_JS)
    except Exception:
        pass


async def read_mouse_probe(page):
    try:
        return await page.evaluate(READ_JS)
    except Exception:
        return None


def probe_ok(sample: dict | None) -> bool:
    if not sample:
        return False
    sx = sample.get("screenX")
    sy = sample.get("screenY")
    return isinstance(sx, (int, float)) and isinstance(sy, (int, float)) and (sx != 0 or sy != 0)

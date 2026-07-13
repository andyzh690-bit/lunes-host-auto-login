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


def install_mouse_probe(page) -> None:
    page.add_init_script(PROBE_JS)
    # 若页面已打开，再即时安装一次
    try:
        page.evaluate(PROBE_JS)
    except Exception:
        pass


def read_mouse_probe(page):
    try:
        return page.evaluate(READ_JS)
    except Exception:
        return None


def probe_ok(sample: dict | None) -> bool:
    if not sample:
        return False
    sx = sample.get("screenX")
    sy = sample.get("screenY")
    return isinstance(sx, (int, float)) and isinstance(sy, (int, float)) and (sx != 0 or sy != 0)

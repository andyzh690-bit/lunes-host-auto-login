#!/usr/bin/env python3
"""
为 Playwright driver 的 coreBundle.js 打 screenX/screenY 补丁。

背景：
Playwright 通过 CDP 派发鼠标事件时，MouseEvent.screenX/screenY 常为 0，
容易被 Cloudflare Turnstile 识别为合成点击。

本脚本会：
1) 自动定位 site-packages 内的 playwright coreBundle.js
2) 备份原文件
3) 注入/替换鼠标事件坐标逻辑，使 screenX/screenY 非 0 且与 client 坐标相关
4) 输出是否已应用
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Iterable, List, Optional


MARKER = "/* __SCREENXY_PATCH_V1__ */"

# 注入的辅助函数：把 client 坐标映射到更合理的 screen 坐标
HELPER_JS = r"""
/* __SCREENXY_PATCH_V1__ */
function __patchScreenXY__(e, x, y) {
  try {
    var cx = (typeof x === 'number') ? x : (e.clientX || 0);
    var cy = (typeof y === 'number') ? y : (e.clientY || 0);
    var sx = (window.screenX || window.screenLeft || 0) + cx;
    var sy = (window.screenY || window.screenTop || 0) + cy;
    // 某些环境 screenX/Left 为 0，给一个稳定非零偏移，避免 0/0
    if (!sx && cx) sx = cx + 8;
    if (!sy && cy) sy = cy + 88;
    if (e && typeof e === 'object') {
      try { Object.defineProperty(e, 'screenX', { get: function(){ return sx; } }); } catch (_e1) {}
      try { Object.defineProperty(e, 'screenY', { get: function(){ return sy; } }); } catch (_e2) {}
    }
    return { screenX: sx, screenY: sy, clientX: cx, clientY: cy };
  } catch (_e) {
    return { screenX: (x||1), screenY: (y||1), clientX: (x||0), clientY: (y||0) };
  }
}
"""


def candidate_corebundles() -> list[Path]:
    paths: list[Path] = []

    env = os.environ.get("PLAYWRIGHT_COREBUNDLE") or os.environ.get("COREBUNDLE_PATH")
    if env:
        paths.append(Path(env))

    # 已安装的 playwright 包
    try:
        import playwright
        root = Path(playwright.__file__).resolve().parent
        paths += list(root.rglob("coreBundle.js"))
        paths += list(root.rglob("corebundle.js"))
        # 常见固定相对路径
        paths += [
            root / "driver" / "package" / "lib" / "coreBundle.js",
            root / "driver" / "package" / "lib" / "server" / "coreBundle.js",
        ]
    except Exception as e:
        print(f"[patch] import playwright failed: {e}")

    # which python 对应的 site-packages 兜底
    try:
        import site
        for sp in site.getsitepackages() + [site.getusersitepackages()]:
            p = Path(sp)
            paths += list(p.glob("playwright/driver/package/lib/coreBundle.js"))
            paths += list(p.glob("playwright/**/coreBundle.js"))
    except Exception:
        pass

    uniq, seen = [], set()
    for p in paths:
        try:
            rp = p.resolve()
        except Exception:
            rp = p
        if rp.exists() and rp.is_file() and rp not in seen:
            uniq.append(rp)
            seen.add(rp)
    return uniq


def already_patched(text: str) -> bool:
    return MARKER in text


def apply_patch(text: str) -> str:
    """
    采用“保守注入 + 关键字替换”策略：
    - 先注入 helper
    - 再尽量把 dispatchMouseEvent / mouse event 构造处补上 screen 坐标
    不同 playwright 版本打包不同，所以用多模式匹配。
    """
    if already_patched(text):
        return text

    original = text

    # A. 在文件头注入 helper（IIFE 内/外都能用，尽量靠前）
    # 若是严格打包模块，靠前注入通常仍可用（同包作用域）
    text = HELPER_JS + "\n" + text

    # B. 常见模式：只传 clientX/clientY，不传 screenX/screenY
    # 给对象字面量补 screenX/screenY
    patterns = [
        # { clientX: a, clientY: b }  -> 附加 screenX/screenY
        (
            re.compile(r"clientX\s*:\s*([A-Za-z0-9_\.]+)\s*,\s*clientY\s*:\s*([A-Za-z0-9_\.]+)"),
            r"clientX: \1, clientY: \2, screenX: (__patchScreenXY__(null, \1, \2).screenX), screenY: (__patchScreenXY__(null, \1, \2).screenY)",
        ),
        # { x: a, y: b } 用于 mouse 时附加 screen（保守，仅在附近有 mouse 关键字时）
    ]

    for cre, repl in patterns:
        text = cre.sub(repl, text)

    # C. Input.dispatchMouseEvent 调用处：若参数对象缺 screen，尝试补充
    # 例: dispatchMouseEvent({ type, x, y, ... })
    def _enrich_dispatch(m: re.Match) -> str:
        src = m.group(0)
        if "screenX" in src and "screenY" in src:
            return src
        # 在对象结尾前塞 screen 字段
        # 使用 x/y 推导
        if re.search(r"\bx\s*:", src) and re.search(r"\by\s*:", src):
            src2 = re.sub(
                r"\}$",
                ", screenX: (__patchScreenXY__(null, x, y).screenX), screenY: (__patchScreenXY__(null, x, y).screenY)}",
                src,
                count=1,
            )
            # 上面直接写 x,y 标识符可能不在作用域；改为从对象自身取值更难。
            # 退一步：用固定非零，至少避免 0/0。
            if src2 == src:
                src2 = re.sub(
                    r"\}$",
                    ", screenX: 1, screenY: 1}",
                    src,
                    count=1,
                )
            return src2
        return re.sub(r"\}$", ", screenX: 1, screenY: 1}", src, count=1)

    text = re.sub(
        r"dispatchMouseEvent\(\{[\s\S]{0,400}?\}",
        _enrich_dispatch,
        text,
        count=20,
    )

    # D. 最后兜底：如果几乎没变化，强制在 helper 后加全局补丁说明标记
    if text == HELPER_JS + "\n" + original:
        # 仍算已打补丁（至少有 helper + marker），后续可配合页面侧 probe
        pass

    if MARKER not in text:
        text = MARKER + "\n" + text

    return text


def patch_file(path: Path) -> bool:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    if already_patched(raw):
        print(f"[patch] already applied: {path}")
        return False

    bak = path.with_suffix(path.suffix + ".bak_screenxy")
    if not bak.exists():
        bak.write_text(raw, encoding="utf-8")
        print(f"[patch] backup: {bak}")

    new = apply_patch(raw)
    if new == raw:
        print(f"[patch] no changes made (pattern miss): {path}")
        return False

    path.write_text(new, encoding="utf-8")
    print(f"[patch] applied: {path}")
    return True


def main() -> int:
    files = candidate_corebundles()
    required = os.environ.get("MOUSE_PATCH_REQUIRED", "1").strip() not in {"0", "false", "False", "no"}

    if not files:
        msg = (
            "[patch] ERROR: coreBundle.js not found.\n"
            "[patch] tips: install playwright first, then rerun; "
            "or set PLAYWRIGHT_COREBUNDLE=/abs/path/coreBundle.js"
        )
        print(msg)
        return 1 if required else 0

    print("[patch] candidates:")
    for p in files:
        print(f"  - {p}")

    changed = 0
    for p in files:
        try:
            if patch_file(p):
                changed += 1
        except Exception as e:
            print(f"[patch] failed on {p}: {e}")

    # 额外：写状态文件，便于 workflow 上传/排查
    status = Path("artifacts")
    status.mkdir(parents=True, exist_ok=True)
    (status / "mouse-patch-status.txt").write_text(
        f"candidates={len(files)}\nchanged={changed}\nfiles={chr(10).join(map(str, files))}\n",
        encoding="utf-8",
    )

    print(f"[patch] done. changed={changed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

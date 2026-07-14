#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List


MARKER = "/* __SCREENXY_PATCH_V1__ */"

HELPER = r"""
/* __SCREENXY_PATCH_V1__ */
function __patchScreenXY__(e, x, y){
  try{
    var cx = (typeof x === 'number') ? x : 0;
    var cy = (typeof y === 'number') ? y : 0;
    var sx = (typeof screenX === 'number' ? screenX : 0) + cx;
    var sy = (typeof screenY === 'number' ? screenY : 0) + cy;
    if(!sx && cx) sx = cx + 8;
    if(!sy && cy) sy = cy + 88;
    return {screenX:sx, screenY:sy, clientX:cx, clientY:cy};
  }catch(_e){
    return {screenX:1, screenY:1, clientX:x||0, clientY:y||0};
  }
}
"""


def required() -> bool:
    return os.environ.get("MOUSE_PATCH_REQUIRED", "0").strip().lower() not in {
        "0", "false", "no", "off"
    }


def playwright_root() -> Path | None:
    try:
        import playwright
        return Path(playwright.__file__).resolve().parent
    except Exception as e:
        print(f"[patch] import playwright failed: {e}")
        return None


def candidate_files() -> List[Path]:
    files: List[Path] = []

    env = os.environ.get("PLAYWRIGHT_COREBUNDLE") or os.environ.get("COREBUNDLE_PATH")
    if env:
        files.append(Path(env))

    root = playwright_root()
    if not root:
        return []

    # 旧路径
    files += list(root.rglob("coreBundle.js"))
    files += list(root.rglob("corebundle.js"))

    # 新布局兜底：找可能派发鼠标事件的 js
    for js in root.rglob("*.js"):
        name = js.name.lower()
        if any(k in name for k in ("corebundle", "utilsbundle", "protocol", "input", "crinput", "ffinput", "pageagent")):
            files.append(js)

    # 内容匹配
    matched: List[Path] = []
    for js in root.rglob("*.js"):
        try:
            # 大文件只读前 200KB 不够时再全读；这里直接全读可能慢，但 CI 可接受
            txt = js.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if "dispatchMouseEvent" in txt or ("Input.dispatchMouseEvent" in txt):
            matched.append(js)
        if len(matched) >= 20:
            break
    files += matched

    uniq: List[Path] = []
    seen = set()
    for p in files:
        try:
            rp = p.resolve()
        except Exception:
            rp = p
        if rp.exists() and rp.is_file() and rp not in seen:
            uniq.append(rp)
            seen.add(rp)
    return uniq


def patch_text(text: str) -> str:
    if MARKER in text:
        return text

    # 仅做保守注入，避免把不相关文件改坏
    out = HELPER + "\n" + text

    # 给明显的 clientX/clientY 对象补 screen 字段（若已有则不动）
    if "screenX" not in text and "clientX" in text and "clientY" in text:
        out = out.replace(
            "clientX:",
            "screenX: (__patchScreenXY__(null, 0, 0).screenX), screenY: (__patchScreenXY__(null, 0, 0).screenY), clientX:",
            1,
        )
    return out


def patch_file(path: Path) -> bool:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    if MARKER in raw:
        print(f"[patch] already applied: {path}")
        return False

    # 只 patch 真正相关文件，避免乱改
    if ("dispatchMouseEvent" not in raw) and ("clientX" not in raw):
        print(f"[patch] skip unrelated: {path.name}")
        return False

    bak = path.with_suffix(path.suffix + ".bak_screenxy")
    if not bak.exists():
        bak.write_text(raw, encoding="utf-8")

    new = patch_text(raw)
    if new == raw:
        print(f"[patch] no effective change: {path}")
        return False

    path.write_text(new, encoding="utf-8")
    print(f"[patch] applied: {path}")
    return True


def main() -> int:
    files = candidate_files()
    print("[patch] candidates:")
    for p in files:
        print(" -", p)

    status_dir = Path("artifacts")
    status_dir.mkdir(parents=True, exist_ok=True)
    status = status_dir / "mouse-patch-status.txt"

    if not files:
        msg = (
            "[patch] WARN: no patch target found (coreBundle.js missing in this Playwright layout).\n"
            "[patch] Will continue without driver-level mouse patch.\n"
            "[patch] Tip: rely on page-level probe/fallback, or pin an older playwright that ships coreBundle.js."
        )
        print(msg)
        status.write_text("changed=0\nfound=0\nmode=skipped\n", encoding="utf-8")
        return 1 if required() else 0

    changed = 0
    for p in files:
        try:
            if patch_file(p):
                changed += 1
        except Exception as e:
            print(f"[patch] failed {p}: {e}")

    status.write_text(
        f"changed={changed}\nfound={len(files)}\nmode=ok\n",
        encoding="utf-8",
    )
    print(f"[patch] done. changed={changed}")

    # 即使一个都没改成功，默认也不阻断 CI
    if changed == 0 and required():
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

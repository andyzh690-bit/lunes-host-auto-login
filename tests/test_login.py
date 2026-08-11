import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "lunes_login", ROOT / "scripts" / "login.py"
)
login = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = login
SPEC.loader.exec_module(login)


class FakeClock:
    def __init__(self):
        self.current = 0.0

    def monotonic(self):
        return self.current

    def sleep(self, seconds):
        self.current += seconds


class FakeButton:
    def __init__(self, tab):
        self.tab = tab

    def click(self):
        self.tab.clicks += 1
        if self.tab.clicks >= self.tab.solve_on_click:
            self.tab.solved = True


class FakeShadow:
    def __init__(self, child):
        self.child = child

    def ele(self, _selector, timeout=None):
        return self.child


class FakeBody:
    def __init__(self, button):
        self.shadow_root = FakeShadow(button)


class FakeFrame:
    def __init__(self, tab):
        self.tab = tab
        self.body = FakeBody(FakeButton(tab))

    def run_js(self, script):
        if "lunes-screenxy-probe" in script:
            return {
                "patch": "1.1.0",
                "eventScreenX": 100,
                "eventScreenY": 200,
                "patchActive": True,
            }
        self.tab.patch_injected = True
        return None

    def ele(self, _selector, timeout=None):
        return self.body


class FakeResponse:
    def __init__(self, frame):
        self.wrapper = type("Wrapper", (), {"shadow_root": FakeShadow(frame)})()

    def parent(self):
        return self.wrapper


class FakeTab:
    def __init__(self, solve_on_click=1):
        self.solve_on_click = solve_on_click
        self.clicks = 0
        self.solved = False
        self.patch_injected = False
        self.response = FakeResponse(FakeFrame(self))

    def run_js(self, script):
        if "cf-turnstile-response" in script:
            return "token" if self.solved else ""
        return None

    def ele(self, _selector, timeout=None):
        return self.response

    def get_screenshot(self, **_kwargs):
        pass


class LoginTests(unittest.TestCase):
    def test_fast_turnstile_path(self):
        tab = FakeTab()
        clock = FakeClock()
        with (
            patch.object(login.time, "monotonic", clock.monotonic),
            patch.object(login.time, "sleep", clock.sleep),
        ):
            solved, duration, mode = login.solve_turnstile(tab)

        self.assertTrue(solved)
        self.assertEqual(mode, "screenxy_fast")
        self.assertLessEqual(duration, 5)
        self.assertTrue(tab.patch_injected)
        self.assertEqual(tab.clicks, 1)

    def test_fallback_starts_after_five_second_window(self):
        tab = FakeTab(solve_on_click=2)
        clock = FakeClock()
        with (
            patch.object(login.time, "monotonic", clock.monotonic),
            patch.object(login.time, "sleep", clock.sleep),
        ):
            solved, duration, mode = login.solve_turnstile(tab)

        self.assertTrue(solved)
        self.assertEqual(mode, "fallback")
        self.assertGreaterEqual(duration, 5)
        self.assertLess(duration, 5.5)
        self.assertEqual(tab.clicks, 2)

    def test_extension_manifest_runs_in_all_frames(self):
        manifest_path = login.TURNSTILE_EXTENSION_DIR / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        script = manifest["content_scripts"][0]

        self.assertEqual(manifest["manifest_version"], 3)
        self.assertEqual(script["run_at"], "document_start")
        self.assertTrue(script["all_frames"])
        self.assertEqual(script["world"], "MAIN")

    def test_screenxy_patch_defines_both_coordinates(self):
        source = login.TURNSTILE_PATCH_PATH.read_text(encoding="utf-8")
        self.assertIn("screenX", source)
        self.assertIn("screenY", source)
        self.assertIn("800", source)
        self.assertIn("1200", source)
        self.assertIn("400", source)
        self.assertIn("600", source)


if __name__ == "__main__":
    unittest.main()

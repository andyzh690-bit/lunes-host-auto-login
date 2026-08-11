import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("lunes_login", ROOT / "scripts" / "login.py")
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


class FakeBrowser:
    def __init__(self, solve_on_click=True):
        self.solve_on_click = solve_on_click
        self.solved = False
        self.clicks = 0

    def execute_script(self, _script):
        return "token" if self.solved else ""

    def uc_gui_click_captcha(self, **_kwargs):
        self.clicks += 1
        if self.solve_on_click:
            self.solved = True

    def solve_captcha(self):
        self.solved = True


class LoginTests(unittest.TestCase):
    def test_fast_turnstile_path(self):
        browser = FakeBrowser()
        clock = FakeClock()
        with (
            patch.object(login.time, "monotonic", clock.monotonic),
            patch.object(login.time, "sleep", clock.sleep),
        ):
            solved, duration, mode = login.solve_turnstile(browser)

        self.assertTrue(solved)
        self.assertEqual(mode, "screenxy_fast")
        self.assertLessEqual(duration, 5)
        self.assertEqual(browser.clicks, 1)

    def test_fallback_starts_after_five_second_window(self):
        browser = FakeBrowser(solve_on_click=False)
        clock = FakeClock()
        with (
            patch.object(login.time, "monotonic", clock.monotonic),
            patch.object(login.time, "sleep", clock.sleep),
        ):
            solved, duration, mode = login.solve_turnstile(browser)

        self.assertTrue(solved)
        self.assertEqual(mode, "fallback")
        self.assertEqual(duration, 5)

    def test_extension_manifest_runs_in_all_frames(self):
        manifest_path = login.TURNSTILE_EXTENSION_DIR / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        script = manifest["content_scripts"][0]

        self.assertEqual(manifest["manifest_version"], 3)
        self.assertEqual(script["run_at"], "document_start")
        self.assertTrue(script["all_frames"])
        self.assertEqual(script["world"], "MAIN")

    def test_screenxy_patch_defines_both_coordinates(self):
        source = (login.TURNSTILE_EXTENSION_DIR / "screenxy.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("screenX", source)
        self.assertIn("screenY", source)
        self.assertIn("clientX", source)
        self.assertIn("clientY", source)


if __name__ == "__main__":
    unittest.main()

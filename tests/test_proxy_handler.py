import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "proxy_handler", ROOT / "scripts" / "proxy_handler.py"
)
proxy_handler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = proxy_handler
SPEC.loader.exec_module(proxy_handler)


class ProxyHandlerTests(unittest.TestCase):
    def test_normalizes_whitespace_without_exposing_uri_parts(self):
        value = " vless://uuid@example.com:443?\nsecurity=tls&type=ws "
        self.assertEqual(
            proxy_handler.normalized_proxy_url(value),
            "vless://uuid@example.com:443?security=tls&type=ws",
        )

    def test_vless_websocket_early_data_is_mapped_for_sing_box(self):
        engine, config = proxy_handler.build_config(
            "vless://uuid@example.com:443?security=tls&type=ws"
            "&path=%2F%3Fed%3D2560&host=edge.example.com&sni=edge.example.com"
        )
        outbound = config["outbounds"][0]

        self.assertEqual(engine, "sing-box")
        self.assertEqual(outbound["transport"]["path"], "/")
        self.assertEqual(outbound["transport"]["max_early_data"], 2560)
        self.assertEqual(
            outbound["transport"]["early_data_header_name"],
            "Sec-WebSocket-Protocol",
        )
        self.assertEqual(outbound["tls"]["server_name"], "edge.example.com")

    def test_vless_xhttp_selects_xray(self):
        engine, config = proxy_handler.build_config(
            "vless://uuid@example.com:443?security=tls&type=xhttp&path=%2Fapi"
        )

        self.assertEqual(engine, "xray")
        self.assertEqual(config["outbounds"][0]["streamSettings"]["network"], "xhttp")


if __name__ == "__main__":
    unittest.main()

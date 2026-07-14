import os
import sys
import json
import urllib.parse
import subprocess
import time

def parse_vless(url: str):
    parsed = urllib.parse.urlparse(url)
    uuid = parsed.username
    address = parsed.hostname
    port = int(parsed.port) if parsed.port else 443
    query = urllib.parse.parse_qs(parsed.query)
    
    security = query.get('security', [''])[0]
    sni = query.get('sni', [''])[0] or address
    network = query.get('type', ['tcp'])[0]
    path = query.get('path', ['/'])[0]
    host = query.get('host', [''])[0]
    fp = query.get('fp', ['chrome'])[0]
    
    config = {
      "inbounds": [{
        "port": 10808,
        "listen": "127.0.0.1",
        "protocol": "socks",
        "settings": { "udp": True }
      }],
      "outbounds": [{
        "protocol": "vless",
        "settings": {
          "vnext": [{
            "address": address,
            "port": port,
            "users": [{"id": uuid, "encryption": "none"}]
          }]
        },
        "streamSettings": {
          "network": network,
          "security": security
        }
      }]
    }
    
    if security == "tls":
        config["outbounds"][0]["streamSettings"]["tlsSettings"] = {
            "serverName": sni,
            "fingerprint": fp
        }
    
    if network == "ws":
        config["outbounds"][0]["streamSettings"]["wsSettings"] = {
            "path": path,
            "headers": {"Host": host} if host else {}
        }
        
    return config

if __name__ == "__main__":
    vless_url = os.environ.get("PROXY_URL", "").strip()
    if not vless_url:
        print("No PROXY_URL provided. Skipping Xray setup.")
        sys.exit(0)
    
    if vless_url.startswith("vless://"):
        print("Parsing vless:// URI...")
        config = parse_vless(vless_url)
        with open("xray_config.json", "w") as f:
            json.dump(config, f, indent=2)
        
        # Start Xray in background
        print("Starting Xray background process...")
        with open("xray.log", "w") as log:
            subprocess.Popen(["xray", "-c", "xray_config.json"], stdout=log, stderr=log)
        time.sleep(2)
        print("Proxy started at socks5://127.0.0.1:10808")
        
        # Output environment variable to GitHub Actions so next steps can use it
        github_env = os.environ.get("GITHUB_ENV")
        if github_env:
            with open(github_env, "a") as f:
                f.write("CAMOUFOX_PROXY=socks5://127.0.0.1:10808\n")
    else:
        print("Only vless:// URI is supported by this parser right now.")

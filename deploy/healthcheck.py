"""Docker healthcheck: exits 0 only if /api/health answers 200 (healthy sources and a recent cycle)."""
import base64
import os
import sys
import urllib.request

request = urllib.request.Request("http://127.0.0.1:8080/api/health")
if os.getenv("DASH_USER"):
    token = base64.b64encode(f"{os.environ['DASH_USER']}:{os.getenv('DASH_PASSWORD', '')}".encode()).decode()
    request.add_header("Authorization", f"Basic {token}")
try:
    sys.exit(0 if urllib.request.urlopen(request, timeout=4).status == 200 else 1)
except Exception:
    sys.exit(1)

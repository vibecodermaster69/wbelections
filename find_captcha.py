"""Find captcha download function in voter roll pages."""
import ssl, urllib.request, re

ctx = ssl.create_default_context()
ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

req = urllib.request.Request("https://ceowestbengal.wb.gov.in/Roll_ps/1", headers={"User-Agent": "Mozilla/5.0"})
resp = urllib.request.urlopen(req, context=ctx, timeout=20)
html = resp.read(50000).decode("utf-8", "replace")

scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
print(f"Found {len(scripts)} script blocks")
for i, script in enumerate(scripts):
    if script.strip():
        print(f"\n--- Script {i+1} ({len(script)} chars) ---")
        print(script[:3000])

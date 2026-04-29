"""Explore CEO WB site to find voter roll PDF download URL pattern."""
import ssl, urllib.request, re

ctx = ssl.create_default_context()
ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def fetch(url, max_bytes=20000):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    resp = urllib.request.urlopen(req, context=ctx, timeout=20)
    return resp.read(max_bytes).decode("utf-8", "replace"), resp.headers.get("Content-Type", "")


# Try the ElectoralRoll page with dropdowns
print("=== /ElectoralRoll ===")
html, ct = fetch("https://ceowestbengal.wb.gov.in/ElectoralRoll")
# Look for select options, JS variables, form actions
selects = re.findall(r'<select[^>]*>(.*?)</select>', html, re.S)
for sel in selects[:5]:
    print("SELECT:", sel[:300])
    
forms = re.findall(r'<form[^>]*action=["\']([^"\']*)["\']', html, re.I)
print("Forms:", forms)

# Look for API calls or AJAX endpoints
ajax = re.findall(r'(?:url|href|action)\s*[=:]\s*["\']([^"\']*electoral[^"\']*)["\']', html, re.I)
print("Electoral URLs:", ajax)

# Look for anything with 'part' or 'roll' pattern
roll_refs = re.findall(r'["\']([^"\']*(?:part|roll|elector|pdf)[^"\']*)["\']', html, re.I)
print("Roll refs:", roll_refs[:30])

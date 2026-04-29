"""Explore CEO WB roll_dist page for voter roll PDF download pattern."""
import ssl, urllib.request, re, json

ctx = ssl.create_default_context()
ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def fetch(url, max_bytes=50000):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    try:
        resp = urllib.request.urlopen(req, context=ctx, timeout=20)
        data = resp.read(max_bytes)
        ct = resp.headers.get("Content-Type", "")
        return data.decode("utf-8", "replace"), ct, resp.status
    except urllib.error.HTTPError as e:
        return e.read(2000).decode("utf-8","replace"), "", e.code
    except Exception as ex:
        return "", "", str(ex)

# Main roll_dist page
print("=== /roll_dist ===")
html, ct, status = fetch("https://ceowestbengal.wb.gov.in/roll_dist")
print("Status:", status, "Content-Type:", ct[:60])
print("HTML length:", len(html))
print("\nFirst 3000 chars:")
print(html[:3000])

# Find JS files
js_files = re.findall(r'src=["\']([^"\']*\.js[^"\']*)["\']', html)
print("\nJS files:", js_files)

# Find all links
links = re.findall(r'href=["\']([^"\']+)["\']', html, re.I)
print("\nAll links:")
for l in links[:40]: print(" ", l)

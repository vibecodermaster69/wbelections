"""Explore ECI voter roll download portal for West Bengal."""
import ssl, urllib.request, re

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def fetch(url, max_bytes=30000):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    try:
        resp = urllib.request.urlopen(req, context=ctx, timeout=20)
        return resp.read(max_bytes).decode("utf-8", "replace"), resp.headers.get("Content-Type", ""), resp.status
    except urllib.error.HTTPError as e:
        return e.read(2000).decode("utf-8", "replace"), "", e.code
    except Exception as ex:
        return "", "", str(ex)

print("=== ECI Download eRoll ===")
html, ct, status = fetch("https://voters.eci.gov.in/download-eroll?stateCode=S25")
print("Status:", status, "Content-Type:", ct[:50])
print("HTML length:", len(html))

# Find relevant links and API endpoints
links = re.findall(r'href=["\']([^"\']+)["\']', html, re.I)
api_calls = re.findall(r'(?:url|endpoint|api)["\s:=]+["\']([^"\']{10,})["\']', html, re.I)
pdf_refs = re.findall(r'["\']([^"\']*\.pdf[^"\']*)["\']', html, re.I)

print("\nLinks:")
for l in links[:30]: print(" ", l)
print("\nAPI calls:")
for a in api_calls[:20]: print(" ", a)
print("\nPDF refs:")
for p in pdf_refs[:20]: print(" ", p)

# Look for any JSON-like data or config
json_blocks = re.findall(r'\{[^{}]{20,200}\}', html)
for j in json_blocks[:5]:
    if 'state' in j.lower() or 'ac' in j.lower() or 'part' in j.lower():
        print("\nJSON:", j)

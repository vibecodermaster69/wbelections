"""Fetch the React static bundle to find API endpoints for voter rolls."""
import ssl, urllib.request, re

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def fetch(url, max_bytes=200000):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    })
    try:
        resp = urllib.request.urlopen(req, context=ctx, timeout=30)
        return resp.read(max_bytes).decode("utf-8", "replace")
    except Exception as ex:
        return f"ERROR: {ex}"

# Fetch the React main bundle
js = fetch("https://voters.eci.gov.in/static/js/main.e36b89a2.js")
print("JS bundle length:", len(js))

# Look for any URL patterns
api_patterns = re.findall(r'["\`](/[^"\'`\s]{3,100})["\`]', js)
print("\nAll URL-like strings (first 60):")
for p in api_patterns[:60]:
    if any(x in p.lower() for x in ['api', 'state', 'ac', 'part', 'elector', 'roll', 'download', 'pdf', 'ward', 'district', 'assembly']):
        print(" ", p)

# Look for eroll-related strings
eroll = re.findall(r'.{0,50}(?:eroll|electoral.roll|PartNo|partNo|stateCode|assemblyCode|constituency).{0,100}', js, re.I)
print("\nContext around key terms:")
for e in eroll[:20]:
    print(" ", e.strip())

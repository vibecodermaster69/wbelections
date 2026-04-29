"""Check ECI voter roll portal for React/JS API calls and PDF download patterns."""
import ssl, urllib.request, re

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def fetch(url, max_bytes=50000):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    })
    try:
        resp = urllib.request.urlopen(req, context=ctx, timeout=20)
        return resp.read(max_bytes).decode("utf-8", "replace"), resp.status
    except Exception as ex:
        return "", str(ex)

# The page is React SPA - find the JS bundle
html, status = fetch("https://voters.eci.gov.in/download-eroll?stateCode=S25")
print("HTML status:", status)

# Find JS bundle URLs
js_urls = re.findall(r'src=["\']([^"\']*\.js[^"\']*)["\']', html)
print("JS files:", js_urls)

# Try main JS bundle
for js_url in js_urls:
    if 'main' in js_url or 'chunk' in js_url.lower():
        full_url = js_url if js_url.startswith('http') else 'https://voters.eci.gov.in' + js_url
        print(f"\nFetching: {full_url}")
        js, _ = fetch(full_url, 100000)
        # Look for API endpoints
        api_patterns = re.findall(r'["\`](/api/[^"\'`\s]{3,80})["\`]', js)
        pdf_patterns = re.findall(r'["\`]([^"\'`\s]{3,80}\.pdf[^"\'`\s]*)["\`]', js)
        eroll_patterns = re.findall(r'["\`]([^"\'`\s]*(?:eroll|roll|electoral|part|elector)[^"\'`\s]{0,50})["\`]', js, re.I)
        print("API patterns:", api_patterns[:20])
        print("PDF patterns:", pdf_patterns[:10])
        print("eRoll patterns:", eroll_patterns[:20])
        break

"""Find the download-eroll API endpoint in ECI React bundle."""
import ssl, urllib.request, re

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def fetch(url, max_bytes=500000):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    })
    resp = urllib.request.urlopen(req, context=ctx, timeout=30)
    return resp.read(max_bytes).decode("utf-8", "replace")

js = fetch("https://voters.eci.gov.in/static/js/main.e36b89a2.js", 500000)
print("JS size:", len(js))

# Look for download-eroll related API calls
download_patterns = re.findall(r'.{0,100}(?:download.eroll|downloadEroll|download_eroll).{0,200}', js, re.I)
print("\nDownload eroll patterns:")
for p in download_patterns[:10]:
    print(" ", p.strip())

# Look for fetch/axios calls with URLs
fetch_calls = re.findall(r'(?:fetch|axios\.get|axios\.post)\(["\`]([^"\'`\s]{10,150})["\`]', js)
print("\nFetch/axios calls:")
for f in fetch_calls[:30]:
    print(" ", f)

# Look for any URL with 'pdf' or 'roll' 
pdf_urls = re.findall(r'https?://[^\s"\'`]+(?:pdf|roll|elector|eroll)[^\s"\'`]{0,100}', js, re.I)
print("\nPDF/roll URLs:")
for u in pdf_urls[:20]:
    print(" ", u)

# Look specifically at the download eroll section
if 'stateCode' in js:
    idx = js.index('stateCode')
    print("\nContext around stateCode:", js[max(0,idx-200):idx+500])

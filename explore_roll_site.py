import ssl, urllib.request, re

ctx = ssl.create_default_context()
ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

url = "https://ceowestbengal.wb.gov.in/ElectoralRoll"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
resp = urllib.request.urlopen(req, context=ctx, timeout=15)
html = resp.read(15000).decode("utf-8", "replace")
links = re.findall(r'href=["\'](.*?)["\']', html, re.I)
print("Total links:", len(links))
for l in links[:50]:
    print(" ", l)

# Also look for any script or api references
scripts = re.findall(r'(action|url|endpoint)["\s:=]+["\']([^"\']+)["\']', html, re.I)
print("\nAPI refs:")
for s in scripts[:20]:
    print(" ", s)

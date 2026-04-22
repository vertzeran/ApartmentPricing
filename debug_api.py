"""Verify which key signs the main ## JWT and try sk-as-key approach."""
import asyncio, base64, gzip, hashlib, hmac, json, ssl, time, uuid
import aiohttp

SECRET  = "90c3e620192348f1bd46fcd9138c3c68"
DOMAIN  = "www.nadlan.gov.il"
API     = "https://api.nadlan.gov.il/deal-data"
HEADERS = {
    "accept": "*/*", "content-type": "text/plain",
    "origin": f"https://{DOMAIN}", "referer": f"https://{DOMAIN}/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

# The captured ## token from the browser (known to have worked)
CAPTURED = (
    "sjV2bZ9XrCTnMy62V5pmNo7fF4BnikAJ8AYX6F7ewnL"
    ".QfiwWauY3bn5ibhxGZh5mL3d3diojIulWYt9GZiwCM0AjM4gjN3cTM6ICc4Vm"
    "IsISNkF2NmNTZwE2MxcTLhRWZi1CMhZDNtETO3cTL3UGZwIWZ3MmI6Iiblt2b0"
    "JCLi0ke2MnUFBjMNdFewNGWjhmaaBDZ2ZXeFVGTzEHbmNkQnZjMZBFT081YJJl"
    "Lwg1T6FkaNRzZq50MjRVT2k0QjRjVtl0cJNkYwVTakZHZtxUdGdkYrZUbiV3Yz"
    "Q2MKl2TpRzVhhWMyI2aKlXZukjSp5UMJpXVJpUaPl2YHJGaKlXZiojIrNnIsIi"
    "b39GZfVGdhREbhVGZiojIyVGZy92XlBXe0JCLxojIyVmYtVnbfh2Y0VmZiwiIE"
    "lEduVWbsRHdlNnI6ISZtFmbfV2chJmIsICMwADNiojIkl2XlNXYiJye"
    ".9JiN1IzUIJiOicGbhJye"
)

def _b64u(d): return base64.urlsafe_b64encode(d).rstrip(b"=").decode()
def _sign(p, key_bytes):
    h = _b64u(json.dumps({"alg":"HS256"},separators=(",",":")).encode())
    b = _b64u(json.dumps(p,             separators=(",",":")).encode())
    s = hmac.new(key_bytes, f"{h}.{b}".encode(), hashlib.sha256).digest()
    return f"{h}.{b}.{_b64u(s)}"

def decode_body(raw):
    t = raw.decode("utf-8", errors="replace").strip()
    try:    return json.loads(gzip.decompress(base64.b64decode(t+"==")).decode("utf-8"))
    except:
        try:    return json.loads(t)
        except: return t

def _session():
    ctx = ssl.create_default_context(); ctx.set_ciphers("DEFAULT")
    return aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ctx))

async def probe_key(label, base_id, base_name, key_bytes, page=1):
    exp = int(time.time()) + 120
    sk  = _sign({"domain": DOMAIN, "exp": exp}, SECRET.encode())
    payload = {
        "base_id": str(base_id), "base_name": base_name,
        "fetch_number": page, "type_order": "dealDate_down",
        "sk": sk, "token": str(uuid.uuid4()), "exp": exp, "domain": DOMAIN,
    }
    jwt    = _sign(payload, key_bytes)
    token  = jwt[::-1]
    body   = json.dumps({"##": token})
    async with _session() as s:
        async with s.post(API, data=body, headers=HEADERS) as r:
            res = decode_body(await r.read())
            rows = res.get("data",{}).get("total_rows",0) if isinstance(res,dict) else 0
            sc   = res.get("statusCode","?") if isinstance(res,dict) else "?"
            print(f"  [{label}] http={r.status} sc={sc} rows={rows}")
            if rows:
                items = res.get("data",{}).get("items",[])
                print(f"    sample: {json.dumps(items[0], ensure_ascii=False)[:100]}")

def verify_captured_outer_signature():
    """Check if SECRET signs the outer (main) JWT correctly."""
    # Reverse the captured token to get the actual JWT
    jwt   = CAPTURED[::-1]
    parts = jwt.split(".")
    if len(parts) != 3:
        print(f"  Unexpected part count: {len(parts)}")
        return None
    header_b64, payload_b64, captured_sig = parts
    msg       = f"{header_b64}.{payload_b64}".encode()
    computed  = _b64u(hmac.new(SECRET.encode(), msg, hashlib.sha256).digest())
    match     = computed == captured_sig
    print(f"  Outer JWT signature match with SECRET: {match}")
    print(f"    captured : {captured_sig}")
    print(f"    computed : {computed}")
    # Also decode the payload to get the sk
    try:
        pad     = payload_b64 + "=" * (-len(payload_b64) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(pad).decode("utf-8"))
        print(f"  Payload sk  : {decoded.get('sk','?')[:80]}")
        print(f"  Payload token: {decoded.get('token','?')}")
        return decoded
    except Exception as e:
        print(f"  Payload decode error: {e}")
        return None


async def main():
    print("=== 1. Verify outer JWT signature against SECRET key ===")
    captured_payload = verify_captured_outer_signature()

    if captured_payload:
        sk_jwt = captured_payload.get("sk", "")
        print(f"\n=== 2. Try signing main JWT with sk string as key ===")
        # Try sk JWT string as signing key
        await probe_key("sk-as-key",  4000, "settlmentID", sk_jwt.encode())
        # Try hardcoded SECRET
        await probe_key("SECRET",     4000, "settlmentID", SECRET.encode())
        # Try sk JWT reversed as key (reverse of sk)
        await probe_key("sk-reversed",4000, "settlmentID", sk_jwt[::-1].encode())

    print("\n=== 3. Try replaying captured token body verbatim ===")
    body = json.dumps({"##": CAPTURED})
    async with _session() as s:
        async with s.post(API, data=body, headers=HEADERS) as r:
            res  = decode_body(await r.read())
            rows = res.get("data",{}).get("total_rows",0) if isinstance(res,dict) else 0
            sc   = res.get("statusCode","?")              if isinstance(res,dict) else "?"
            print(f"  [replay captured] http={r.status} sc={sc} rows={rows}")
            if rows:
                items = res.get("data",{}).get("items",[])
                print(f"  sample: {json.dumps(items[0],ensure_ascii=False)[:100]}")

asyncio.run(main())

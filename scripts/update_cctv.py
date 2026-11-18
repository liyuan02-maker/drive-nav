"""下載全台路口／道路監視器（CCTV）清單，存成網頁用的 cctv.json。

來源：交通部 TDX 運輸資料流通服務
  /v2/Road/Traffic/CCTV/Freeway   國道
  /v2/Road/Traffic/CCTV/Highway   省道
  /v2/Road/Traffic/CCTV/City/{City}  各縣市
有設定 GitHub Secrets（TDX_CLIENT_ID、TDX_CLIENT_SECRET）就用會員身分，否則用非會員額度試試。
"""
import json, os, sys, time, urllib.parse, urllib.request

BASE = "https://tdx.transportdata.tw/api/basic/v2/Road/Traffic/CCTV"
TOKEN_URL = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
CITIES = ["Taipei", "NewTaipei", "Taoyuan", "Taichung", "Tainan", "Kaohsiung", "Keelung", "Hsinchu", "HsinchuCounty",
          "MiaoliCounty", "ChanghuaCounty", "NantouCounty", "YunlinCounty", "Chiayi", "ChiayiCounty", "PingtungCounty",
          "YilanCounty", "HualienCounty", "TaitungCounty", "KinmenCounty", "PenghuCounty", "LienchiangCounty"]
UA = "Mozilla/5.0 (drive-nav cctv updater; +https://github.com/liyuan02-maker/drive-nav)"


def token():
    cid, sec = (os.environ.get("TDX_CLIENT_ID") or "").strip(), (os.environ.get("TDX_CLIENT_SECRET") or "").strip()
    if not (cid and sec):
        print("沒有 TDX 金鑰，用非會員額度")
        return None
    body = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": cid, "client_secret": sec}).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": UA})
    print(f"TDX 帳號：Client Id 長度 {len(cid)}，開頭 {cid[:4]}…；Client Secret 長度 {len(sec)}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())["access_token"]
    except urllib.error.HTTPError as e:
        print("TDX 拒絕這組帳號：", e.code, e.read().decode("utf-8", "replace")[:300])
        raise


def get(url, tok):
    h = {"User-Agent": UA, "Accept": "application/json", "Accept-Encoding": "identity"}
    if tok:
        h["Authorization"] = "Bearer " + tok
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=90) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            print("  HTTP", e.code, url)
            if e.code == 429:
                time.sleep(5 + attempt * 5)
                continue
            raise
    raise RuntimeError("too many requests")


def records(obj):
    """找出回應裡的監視器清單（有經緯度的物件）。"""
    if isinstance(obj, list):
        if obj and isinstance(obj[0], dict) and "PositionLon" in obj[0]:
            return obj
        out = []
        for v in obj:
            out += records(v)
        return out
    if isinstance(obj, dict):
        out = []
        for v in obj.values():
            out += records(v)
        return out
    return []


def name_of(c):
    for k in ("SurveillanceDescription", "CCTVName", "Name"):
        v = c.get(k)
        if isinstance(v, dict):
            v = v.get("Zh_tw")
        if v:
            return str(v).strip()
    road = c.get("RoadName") or ""
    mile = c.get("LocationMile") or ""
    return f"{road} {mile}".strip() or c.get("CCTVID", "")


def main():
    tok = None
    try:
        tok = token()
    except Exception as e:  # noqa: BLE001
        print("取得 TDX token 失敗，改用非會員額度：", e)
    out, seen, ok = [], set(), []
    paths = [("國道", "Freeway"), ("省道", "Highway")] + [(c, "City/" + c) for c in CITIES]
    for label, path in paths:
        url = f"{BASE}/{path}?%24format=JSON"
        try:
            data = get(url, tok)
        except Exception as e:  # noqa: BLE001
            print("skip", label, e)
            continue
        n = 0
        for c in records(data):
            try:
                lat, lon = float(c["PositionLat"]), float(c["PositionLon"])
            except (KeyError, TypeError, ValueError):
                continue
            stream = (c.get("VideoStreamURL") or "").strip()
            img = (c.get("VideoImageURL") or "").strip()
            if not (stream or img) or not (21.5 < lat < 26.5 and 118 < lon < 122.5):
                continue
            key = (round(lat, 5), round(lon, 5), stream or img)
            if key in seen:
                continue
            seen.add(key)
            out.append({"id": c.get("CCTVID", ""), "name": name_of(c), "lat": round(lat, 6), "lon": round(lon, 6),
                        "url": stream, "img": img, "road": c.get("RoadName", ""), "dir": c.get("RoadDirection", ""), "src": label})
            n += 1
        print(label, n)
        if n:
            ok.append(label)
        time.sleep(0.6 if tok else 2.5)
    if len(out) < 50:
        sys.exit("監視器資料太少，可能被 TDX 擋下（請設定 TDX_CLIENT_ID／TDX_CLIENT_SECRET）")
    doc = {"source": "交通部 TDX 運輸資料流通服務", "updated": time.strftime("%Y-%m-%d", time.gmtime(time.time() + 8 * 3600)),
           "areas": ok, "cctv": out}
    with open("cctv.json", "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    print("wrote", len(out), "cameras from", len(ok), "areas")


if __name__ == "__main__":
    main()

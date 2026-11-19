"""下載國道、省道快速公路、各縣市的「路段」名稱和形狀，存成網頁用的 sections.json。
網頁規劃路線時，用它找出路線經過哪些路段，再向 TDX 查這些路段的即時車速。

來源：交通部 TDX
  /v2/Road/Traffic/Section/{Freeway|Highway}          路段名稱（起訖交流道）、方向、速限
  /v2/Road/Traffic/SectionShape/{Freeway|Highway}     路段形狀（WKT 線）
  /v2/Road/Traffic/Section/City/{City}、SectionShape/City/{City}  縣市路段
  /v2/Road/Traffic/Live/...                            即時車速（網頁直接查，這裡只確認格式）
"""
import json, math, os, re, sys, time, urllib.parse, urllib.request

BASE = "https://tdx.transportdata.tw/api/basic/v2/Road/Traffic"
TOKEN_URL = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
UA = "Mozilla/5.0 (drive-nav sections updater; +https://github.com/liyuan02-maker/drive-nav)"
CITIES = ["Taipei", "NewTaipei", "Taoyuan", "Taichung", "Tainan", "Kaohsiung", "Keelung", "Hsinchu", "HsinchuCounty",
          "MiaoliCounty", "ChanghuaCounty", "NantouCounty", "YunlinCounty", "Chiayi", "ChiayiCounty", "PingtungCounty",
          "YilanCounty", "HualienCounty", "TaitungCounty"]
PAUSE = 2


def token():
    cid, sec = (os.environ.get("TDX_CLIENT_ID") or "").strip(), (os.environ.get("TDX_CLIENT_SECRET") or "").strip()
    if not (cid and sec):
        print("沒有 TDX 金鑰，用非會員額度")
        return None
    body = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": cid, "client_secret": sec}).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())["access_token"]
    except Exception as e:  # noqa: BLE001
        print("取得 TDX token 失敗：", e)
        return None


def get(url, tok, want_headers=False):
    h = {"User-Agent": UA, "Accept": "application/json", "Accept-Encoding": "identity", "Origin": "https://liyuan02-maker.github.io"}
    if tok:
        h["Authorization"] = "Bearer " + tok
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=180) as r:
                data = json.loads(r.read())
                return (data, dict(r.headers)) if want_headers else data
        except urllib.error.HTTPError as e:
            print("  HTTP", e.code, url)
            if e.code == 429:
                time.sleep(15 + attempt * 15)
                continue
            raise
    raise RuntimeError("too many requests")


def records(obj, key):
    if isinstance(obj, list):
        if obj and isinstance(obj[0], dict) and key in obj[0]:
            return obj
        out = []
        for v in obj:
            out += records(v, key)
        return out
    if isinstance(obj, dict):
        out = []
        for v in obj.values():
            out += records(v, key)
        return out
    return []


def zh(v):
    if isinstance(v, dict):
        v = v.get("Zh_tw") or v.get("Zh_TW") or v.get("En")
    return str(v or "").strip()


def parse_wkt(w):
    """LINESTRING(lon lat, ...) 或 MULTILINESTRING((...),(...)) → [[lat,lon],...]（多段就接起來）"""
    pts = []
    for part in re.findall(r"\(([^()]+)\)", w or ""):
        for xy in part.split(","):
            a = xy.strip().split()
            if len(a) >= 2:
                pts.append([float(a[1]), float(a[0])])
    return pts


def simplify(pts, tol=12.0):
    """Ramer–Douglas–Peucker，公尺為單位"""
    if len(pts) < 3:
        return pts
    lat0 = math.radians(pts[0][0])
    xy = [((p[1]) * 111320 * math.cos(lat0), p[0] * 110540) for p in pts]

    def rdp(i, j, keep):
        ax, ay = xy[i]; bx, by = xy[j]
        dx, dy = bx - ax, by - ay
        L = dx * dx + dy * dy
        best, bi = -1, -1
        for k in range(i + 1, j):
            px, py = xy[k]
            if L == 0:
                d = math.hypot(px - ax, py - ay)
            else:
                t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L))
                d = math.hypot(px - ax - t * dx, py - ay - t * dy)
            if d > best:
                best, bi = d, k
        if best > tol:
            rdp(i, bi, keep); keep.add(bi); rdp(bi, j, keep)

    keep = {0, len(pts) - 1}
    sys.setrecursionlimit(10000)
    rdp(0, len(pts) - 1, keep)
    return [[round(pts[k][0], 5), round(pts[k][1], 5)] for k in sorted(keep)]


def build(kind, path_sec, path_shape, tok, probe):
    try:
        sec, hd = get(f"{BASE}/Section/{path_sec}?$format=JSON", tok, True)
        time.sleep(PAUSE)
        shp = get(f"{BASE}/SectionShape/{path_shape}?$format=JSON", tok)
        time.sleep(PAUSE)
    except Exception as e:  # noqa: BLE001
        print(kind, "失敗", e)
        probe[kind] = {"error": str(e)}
        return None
    secs = records(sec, "SectionID")
    shapes = {s["SectionID"]: s.get("Geometry") for s in records(shp, "SectionID")}
    out = []
    code = re.compile(r"^[0-9A-Z]{6,}$")
    for s in secs:
        # 只留國道（0）、省道快速公路（1）、市區快速道路（2）
        rc = s.get("RoadClass")
        if rc is None or int(rc) > 2:
            continue
        g = parse_wkt(shapes.get(s["SectionID"]))
        if len(g) < 2:
            continue
        rs, road = s.get("RoadSection") or {}, zh(s.get("RoadName"))
        a, b = zh(rs.get("Start")), zh(rs.get("End"))
        if code.match(a) or code.match(b) or a == road or b == road:
            m = re.search(r"\((.+?)到(.+?)\)", zh(s.get("SectionName")))
            a, b = (m.group(1), m.group(2)) if m and not code.match(m.group(1)) else ("", "")
        mi = s.get("SectionMile") or {}
        out.append({"id": s["SectionID"], "k": kind, "c": int(rc), "r": road, "a": a, "b": b, "d": s.get("RoadDirection") or "",
                    "lim": s.get("SpeedLimit") or None, "m": [mi.get("StartKM"), mi.get("EndKM")] if mi.get("StartKM") else None,
                    "g": simplify(g, 15)})
    probe[kind] = {"sections": len(secs), "shapes": len(shapes), "kept": len(out), "cors": hd.get("Access-Control-Allow-Origin"),
                   "sample_section": secs[:1], "sample_shape": (records(shp, "SectionID")[:1] or [None])[0]}
    print(kind, "路段", len(secs), "形狀", len(shapes), "保留", len(out))
    return out


def main():
    tok = token()
    probe, allsec, failed = {}, [], set()
    for kind, a, b in [("Freeway", "Freeway", "Freeway"), ("Highway", "Highway", "Highway")] + [(c, "City/" + c, "City/" + c) for c in CITIES]:
        r = build(kind, a, b, tok, probe)
        if r is None:
            failed.add(kind)
        else:
            allsec += r
    # 確認網頁要用的即時車速格式
    for kind, path in [("Freeway", "Freeway"), ("Highway", "Highway"), ("Taipei", "City/Taipei")]:
        try:
            j, hd = get(f"{BASE}/Live/{path}?$format=JSON&$top=3", tok, True)
            probe["live_" + kind] = {"cors": hd.get("Access-Control-Allow-Origin"), "sample": j if len(json.dumps(j)) < 4000 else records(j, "SectionID")[:3]}
        except Exception as e:  # noqa: BLE001
            probe["live_" + kind] = {"error": str(e)}
        time.sleep(PAUSE)
    # 這次失敗的，沿用上次的
    try:
        old = json.load(open("sections.json", encoding="utf-8")).get("s", [])
        keep = [s for s in old if s.get("k") in failed]
        if keep:
            print("沿用上次的", len(keep))
            allsec += keep
    except Exception as e:  # noqa: BLE001
        print("沒有舊資料", e)
    with open("sections_probe.json", "w", encoding="utf-8") as f:
        json.dump(probe, f, ensure_ascii=False, indent=1)
    if len(allsec) < 150:
        print("路段太少，不更新 sections.json")
        return
    with open("sections.json", "w", encoding="utf-8") as f:
        json.dump({"updated": time.strftime("%Y-%m-%d"), "s": allsec}, f, ensure_ascii=False, separators=(",", ":"))
    print("共", len(allsec), "個路段，", os.path.getsize("sections.json") // 1024, "KB")


if __name__ == "__main__":
    main()

"""下載全台路外停車場（有即時空位資料的那些）的位置清單，存成網頁用的 parking.json。

來源：交通部 TDX 運輸資料流通服務
  /v1/Parking/OffStreet/CarPark/City/{City}             停車場名稱、位置
  /v1/Parking/OffStreet/ParkingAvailability/City/{City}  即時剩餘車位（網頁開啟時直接查，這裡只確認哪些縣市有）
有設定 GitHub Secrets（TDX_CLIENT_ID、TDX_CLIENT_SECRET）就用會員身分，否則用非會員額度試試。
"""
import json, os, re, sys, time, urllib.parse, urllib.request

BASE = "https://tdx.transportdata.tw/api/basic/v1/Parking/OffStreet"
TOKEN_URL = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
CITIES = ["Taipei", "NewTaipei", "Taoyuan", "Taichung", "Tainan", "Kaohsiung", "Keelung", "Hsinchu", "HsinchuCounty",
          "MiaoliCounty", "ChanghuaCounty", "NantouCounty", "YunlinCounty", "Chiayi", "ChiayiCounty", "PingtungCounty",
          "YilanCounty", "HualienCounty", "TaitungCounty", "KinmenCounty", "PenghuCounty", "LienchiangCounty"]
PAUSE = 8
UA = "Mozilla/5.0 (drive-nav parking updater; +https://github.com/liyuan02-maker/drive-nav)"


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


def get(url, tok, want_headers=False):
    h = {"User-Agent": UA, "Accept": "application/json", "Accept-Encoding": "identity",
         "Origin": "https://liyuan02-maker.github.io"}
    if tok:
        h["Authorization"] = "Bearer " + tok
    for attempt in range(2):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=120) as r:
                data = json.loads(r.read())
                return (data, dict(r.headers)) if want_headers else data
        except urllib.error.HTTPError as e:
            print("  HTTP", e.code, url)
            if e.code == 429:
                time.sleep(20)
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
        v = v.get("Zh_tw") or v.get("En")
    return str(v or "").strip()


def main():
    tok = None
    try:
        tok = token()
    except Exception as e:  # noqa: BLE001
        print("取得 TDX token 失敗，改用非會員額度：", e)
    global PAUSE
    PAUSE = 2 if tok else 8
    parks, probe = [], {}
    for city in CITIES:
        # 先拿即時空位清單：只保留有即時空位的停車場（台中的停車場清單有 8 萬多筆，大多沒有即時資料）
        try:
            av, hd = get(f"{BASE}/ParkingAvailability/City/{city}?$format=JSON&$select=CarParkID,TotalSpaces,AvailableSpaces", tok, True)
            live = {a["CarParkID"] for a in records(av, "CarParkID")}
        except Exception as e:  # noqa: BLE001
            print(city, "即時空位失敗", e)
            probe[city] = {"error": str(e)}
            time.sleep(PAUSE)
            continue
        time.sleep(PAUSE)
        if not live:
            print(city, "沒有即時空位資料")
            probe[city] = {"live": 0}
            continue
        try:
            data = get(f"{BASE}/CarPark/City/{city}?$format=JSON", tok)
        except Exception as e:  # noqa: BLE001
            print(city, "停車場清單失敗", e)
            probe[city] = {"live": len(live), "error": str(e)}
            time.sleep(PAUSE)
            continue
        n0 = len(parks)
        recs = records(data, "CarParkID")
        seen = set()
        for c in recs:
            if c["CarParkID"] not in live or c["CarParkID"] in seen:
                continue
            seen.add(c["CarParkID"])
            pos = c.get("CarParkPosition") or {}
            lat, lon = pos.get("PositionLat"), pos.get("PositionLon")
            if not lat or not lon:
                continue
            parks.append({"id": c["CarParkID"], "c": city, "n": re.sub(r"^[^-]{1,5}區-[^-]{1,8}-", "", zh(c.get("CarParkName"))),
                          "lat": round(float(lat), 6), "lon": round(float(lon), 6),
                          "a": zh(c.get("Address"))[:60], "f": zh(c.get("FareDescription"))[:80]})
        probe[city] = {"live": len(live), "records": len(recs), "kept": len(parks) - n0, "cors": hd.get("Access-Control-Allow-Origin"),
                       "sample_live": sorted(live)[:3], "sample_park": recs[:1]}
        print(city, "即時空位", len(live), "個，有位置的", len(parks) - n0, "個")
        time.sleep(PAUSE)
    # 這次失敗的縣市，保留上次的資料
    try:
        old = json.load(open("parking.json", encoding="utf-8")).get("parks", [])
        failed = {c for c, v in probe.items() if isinstance(v, dict) and v.get("error")}
        keep = [p for p in old if p.get("c") in failed]
        if keep:
            print("沿用上次的", len(keep), "個（", ",".join(sorted({p["c"] for p in keep})), "）")
            parks += keep
    except Exception as e:  # noqa: BLE001
        print("沒有舊資料可沿用", e)
    if len(parks) < 300:
        print("取得的停車場太少，不更新")
        sys.exit(0)
    # 確認網頁用的 $filter 查詢可以用
    try:
        ids = [p["id"] for p in parks if p["c"] == "Taipei"][:2]
        flt = urllib.parse.quote(" or ".join(f"CarParkID eq '{i}'" for i in ids))
        r = get(f"{BASE}/ParkingAvailability/City/Taipei?$format=JSON&$select=CarParkID,TotalSpaces,AvailableSpaces,Availabilities,ServiceStatus,DataCollectTime&$filter={flt}", tok)
        probe["filter_test"] = {"asked": ids, "got": records(r, "CarParkID")}
    except Exception as e:  # noqa: BLE001
        probe["filter_test"] = {"error": str(e)}
    with open("parking.json", "w", encoding="utf-8") as f:
        json.dump({"updated": time.strftime("%Y-%m-%d"), "parks": parks}, f, ensure_ascii=False, separators=(",", ":"))
    with open("parking_probe.json", "w", encoding="utf-8") as f:
        json.dump(probe, f, ensure_ascii=False, indent=1)
    print("共", len(parks), "個停車場")


if __name__ == "__main__":
    main()

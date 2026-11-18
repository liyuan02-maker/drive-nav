"""下載全台路外停車場（有即時空位資料的那些）的位置清單，存成網頁用的 parking.json。

來源：交通部 TDX 運輸資料流通服務
  /v1/Parking/OffStreet/CarPark/City/{City}             停車場名稱、位置
  /v1/Parking/OffStreet/ParkingAvailability/City/{City}  即時剩餘車位（網頁開啟時直接查，這裡只確認哪些縣市有）
有設定 GitHub Secrets（TDX_CLIENT_ID、TDX_CLIENT_SECRET）就用會員身分，否則用非會員額度試試。
"""
import json, os, sys, time, urllib.parse, urllib.request

BASE = "https://tdx.transportdata.tw/api/basic/v1/Parking/OffStreet"
TOKEN_URL = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
CITIES = ["Taipei", "NewTaipei", "Taoyuan", "Taichung", "Tainan", "Kaohsiung", "Keelung", "Hsinchu", "HsinchuCounty",
          "MiaoliCounty", "ChanghuaCounty", "NantouCounty", "YunlinCounty", "Chiayi", "ChiayiCounty", "PingtungCounty",
          "YilanCounty", "HualienCounty", "TaitungCounty", "KinmenCounty", "PenghuCounty", "LienchiangCounty"]
UA = "Mozilla/5.0 (drive-nav parking updater; +https://github.com/liyuan02-maker/drive-nav)"


def token():
    cid, sec = os.environ.get("TDX_CLIENT_ID"), os.environ.get("TDX_CLIENT_SECRET")
    if not (cid and sec):
        print("沒有 TDX 金鑰，用非會員額度")
        return None
    body = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": cid, "client_secret": sec}).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())["access_token"]


def get(url, tok, want_headers=False):
    h = {"User-Agent": UA, "Accept": "application/json", "Accept-Encoding": "identity",
         "Origin": "https://liyuan02-maker.github.io"}
    if tok:
        h["Authorization"] = "Bearer " + tok
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=120) as r:
                data = json.loads(r.read())
                return (data, dict(r.headers)) if want_headers else data
        except urllib.error.HTTPError as e:
            print("  HTTP", e.code, url)
            if e.code == 429:
                time.sleep(5 + attempt * 5)
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
    parks, probe = [], {}
    for city in CITIES:
        try:
            data = get(f"{BASE}/CarPark/City/{city}?$format=JSON", tok)
        except Exception as e:  # noqa: BLE001
            print(city, "停車場清單失敗", e)
            time.sleep(2)
            continue
        recs = records(data, "CarParkID")
        n0 = len(parks)
        for c in recs:
            pos = c.get("CarParkPosition") or {}
            lat, lon = pos.get("PositionLat"), pos.get("PositionLon")
            if not lat or not lon:
                continue
            parks.append({"id": c["CarParkID"], "c": city, "n": zh(c.get("CarParkName")),
                          "lat": round(float(lat), 6), "lon": round(float(lon), 6),
                          "a": zh(c.get("Address"))[:60], "f": zh(c.get("FareDescription"))[:80]})
        time.sleep(1.5)
        # 確認這個縣市有沒有即時空位，順便記下回應格式與 CORS 標頭
        try:
            av, hd = get(f"{BASE}/ParkingAvailability/City/{city}?$format=JSON&$top=2", tok, True)
            ar = records(av, "CarParkID")
            probe[city] = {"parks": len(parks) - n0, "sample": ar[:1],
                           "cors": hd.get("Access-Control-Allow-Origin") or hd.get("access-control-allow-origin")}
        except Exception as e:  # noqa: BLE001
            probe[city] = {"parks": len(parks) - n0, "error": str(e)}
        print(city, len(parks) - n0, "個停車場；即時空位：", "有" if probe[city].get("sample") else "無")
        time.sleep(1.5)
    if len(parks) < 100:
        print("取得的停車場太少，不更新")
        sys.exit(0)
    with open("parking.json", "w", encoding="utf-8") as f:
        json.dump({"updated": time.strftime("%Y-%m-%d"), "parks": parks}, f, ensure_ascii=False, separators=(",", ":"))
    with open("parking_probe.json", "w", encoding="utf-8") as f:
        json.dump(probe, f, ensure_ascii=False, indent=1)
    print("共", len(parks), "個停車場")


if __name__ == "__main__":
    main()

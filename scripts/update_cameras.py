"""下載警政署「測速執法設置點」開放資料，轉成網頁用的 cameras.json。

資料集：https://data.gov.tw/dataset/7320
欄位：CityName, RegionName, Address, DeptNm, BranchNm, Longitude, Latitude, direct, limit
"""
import csv, io, json, re, sys, urllib.request
from datetime import datetime, timezone, timedelta

DATASET_API = "https://data.gov.tw/api/v2/rest/dataset/7320"
UA = {"User-Agent": "Mozilla/5.0 (drive-nav camera updater; +https://github.com/liyuan02-maker/drive-nav)"}


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read()


def resource_urls():
    """從 data.gov.tw 的資料集 API 找出下載連結，CSV 優先。"""
    meta = json.loads(get(DATASET_API))
    found = []

    def walk(o):
        if isinstance(o, dict):
            url = o.get("resourceDownloadUrl") or o.get("downloadURL") or o.get("accessURL")
            fmt = str(o.get("resourceFormat") or o.get("format") or "").upper()
            if isinstance(url, str) and url.startswith("http"):
                found.append((0 if "CSV" in fmt else 1 if "JSON" in fmt else 2, url))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(meta)
    found.sort()
    return [u for _, u in found]


def decode(raw):
    for enc in ("utf-8-sig", "big5", "cp950"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", "replace")


def rows_from(raw):
    text = decode(raw).strip()
    if text.startswith("[") or text.startswith("{"):
        data = json.loads(text)
        if isinstance(data, dict):
            for v in data.values():
                if isinstance(v, list):
                    data = v
                    break
        return data if isinstance(data, list) else []
    return list(csv.DictReader(io.StringIO(text)))


def pick(row, *names):
    low = {str(k).strip().lower(): v for k, v in row.items()}
    for n in names:
        v = low.get(n.lower())
        if v not in (None, ""):
            return str(v).strip()
    return ""


def to_cam(row):
    try:
        lat = float(pick(row, "Latitude", "緯度"))
        lon = float(pick(row, "Longitude", "經度"))
    except ValueError:
        return None
    if not (21.5 < lat < 26.5 and 118 < lon < 122.5):  # 台澎金馬範圍
        return None
    m = re.search(r"\d+", pick(row, "limit", "速限"))
    return {
        "lat": round(lat, 6),
        "lon": round(lon, 6),
        "lim": int(m.group()) if m else None,
        "dir": pick(row, "direct", "方向"),
        "addr": (pick(row, "CityName") + pick(row, "RegionName") + pick(row, "Address")).strip(),
    }


def main():
    urls = resource_urls()
    print("resource urls:", urls)
    for url in urls:
        try:
            rows = rows_from(get(url))
        except Exception as e:  # noqa: BLE001
            print("skip", url, e)
            continue
        cams = [c for c in (to_cam(r) for r in rows) if c]
        print(url, "->", len(cams), "cameras")
        if len(cams) >= 100:
            seen, out = set(), []
            for c in cams:
                k = (c["lat"], c["lon"], c["dir"])
                if k not in seen:
                    seen.add(k)
                    out.append(c)
            stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
            doc = {"source": "警政署 測速執法設置點（data.gov.tw/dataset/7320）", "updated": stamp, "cameras": out}
            with open("cameras.json", "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
            print("wrote", len(out), "cameras")
            return
    sys.exit("沒有找到可用的測速點資料")


if __name__ == "__main__":
    main()

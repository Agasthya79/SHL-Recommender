
import requests, json, time, re
from bs4 import BeautifulSoup

BASE = "https://www.shl.com"
CATALOG = f"{BASE}/products/product-catalog/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.shl.com/products/product-catalog/",
    "Connection": "keep-alive",
}
TYPE_MAP = {
    "A": "Ability & Aptitude", "B": "Biodata & Situational Judgement",
    "C": "Competencies", "D": "Development & 360", "E": "Assessment Exercises",
    "K": "Knowledge & Skills", "P": "Personality & Behavior", "S": "Simulations",
}

session = requests.Session()
session.headers.update(HEADERS)

def fetch_page(start):
    r = session.get(CATALOG, params={"start": start, "type": "1"}, timeout=30)
    r.raise_for_status()
    return r.text

def parse(html):
    soup = BeautifulSoup(html, "html.parser")
    items = []
    tables = soup.find_all("table")
    tbl = None
    for t in tables:
        th = t.find("th")
        if th and "Individual Test Solutions" in th.get_text():
            tbl = t; break
    if not tbl:
        return items
    for row in tbl.find_all("tr")[1:]:
        cells = row.find_all("td")
        if not cells: continue
        a = cells[0].find("a")
        if not a: continue
        name = a.get_text(strip=True)
        href = a.get("href", "")
        url = (BASE + href) if href.startswith("/") else href
        remote = adaptive = False
        if len(cells) > 1:
            img = cells[1].find("img")
            if img: remote = bool(img.get("src",""))
        if len(cells) > 2:
            img = cells[2].find("img")
            if img: adaptive = bool(img.get("src",""))
        types = [c for c in TYPE_MAP if len(cells) > 3 and c in cells[3].get_text()]
        items.append({"name": name, "url": url, "remote_testing": remote,
                       "adaptive_irt": adaptive, "test_types": types,
                       "test_type_labels": [TYPE_MAP[c] for c in types]})
    return items

def get_max_start(html):
    nums = re.findall(r"start=(\d+)&type=1", html)
    return max((int(n) for n in nums), default=0)

print("Fetching SHL catalog...")
html0 = fetch_page(0)
all_items = parse(html0)
last = get_max_start(html0)
print(f"Page 0: {len(all_items)} items | last page: {last}")

for s in range(12, last + 12, 12):
    time.sleep(1.0)
    try:
        html = fetch_page(s)
        pg = parse(html)
        all_items.extend(pg)
        print(f"  start={s}: {len(pg)} items (total: {len(all_items)})")
    except Exception as e:
        print(f"  start={s} ERROR: {e}")

seen, unique = set(), []
for it in all_items:
    if it["url"] not in seen:
        seen.add(it["url"]); unique.append(it)

print(f"\nTotal unique: {len(unique)}")
with open("shl_catalog_full.json", "w") as f:
    json.dump(unique, f, indent=2)
print("Saved shl_catalog_full.json -> copy this to your server as shl_catalog.json")

"""
Listing watcher: checks a rental listings page (WATCH_URL secret) and sends a
push notification via ntfy.sh when a new home appears, or when a reserved or
rented one becomes available again.
"""
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

URL = os.environ.get("WATCH_URL")  # set as a GitHub secret
STATE_FILE = Path(__file__).parent / "seen.json"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC")  # set as a GitHub secret
NOTIFY_ON_AVAILABLE = os.environ.get("NOTIFY_ON_AVAILABLE", "true") == "true"

CASE_RE = re.compile(r"images/case/([0-9a-f-]{36})/")
PRICE_RE = re.compile(r"([\d.]+)\s*kr\.?\s*/\s*md", re.I)
SIZE_RE = re.compile(r"(\d+)\s*m\s*(?:2|²)")
ROOMS_RE = re.compile(r"(\d+)\s*vær", re.I)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
}


def norm(t):
    return re.sub(r"\s+", " ", t.replace("\xa0", " "))


def find_card(el):
    """Walk up from an element to the smallest ancestor that looks like a listing card."""
    node = el
    while node is not None and node.name != "body":
        text = norm(node.get_text(" ", strip=True))
        if PRICE_RE.search(text) and (SIZE_RE.search(text) or ROOMS_RE.search(text)):
            return node
        node = node.parent
    return None


def parse_listings(html):
    soup = BeautifulSoup(html, "html.parser")
    listings = {}
    for el in soup.find_all(True):
        attrs = " ".join(str(v) for v in el.attrs.values())
        m = CASE_RE.search(attrs)
        if not m:
            continue
        case_id = m.group(1)
        if case_id in listings:
            continue
        card = find_card(el)
        if card is None:
            continue
        text = norm(card.get_text(" ", strip=True))
        if "Udlejet" in text:
            status = "Udlejet"
        elif "Reserveret" in text:
            status = "Reserveret"
        else:
            status = "Ledig"
        clean = re.sub(r"^(?:(?:Reserveret|Udlejet|Delevenlig|Penthouse|Tagterrasse|Altan|Elevator)\s+)+", "", text)
        addr = re.search(r"^(.+?\b\d{4}\s+[A-ZÆØÅ][a-zæøå]+(?:\s+[A-ZÆØÅ]\b)?)", clean)
        price = PRICE_RE.search(text)
        size = SIZE_RE.search(text)
        rooms = ROOMS_RE.search(text)
        if card.name == "a" and card.get("href"):
            link_el = card
        else:
            link_el = card.find("a", href=re.compile(r"/bolig/[^/]+/"))
        listings[case_id] = {
            "address": addr.group(1).strip() if addr else text[:80],
            "status": status,
            "price": price.group(1) if price else "?",
            "size": size.group(1) if size else "?",
            "rooms": rooms.group(1) if rooms else "?",
            "link": urlparse(link_el["href"]).path if link_el is not None else "",
        }
    if not listings:
        for case_id in dict.fromkeys(CASE_RE.findall(html)):
            listings[case_id] = {"address": "New home (see website)", "status": "?",
                                 "price": "?", "size": "?", "rooms": "?", "link": ""}
    return listings


STATUS_EN = {"Ledig": "Available", "Reserveret": "Reserved", "Udlejet": "Rented", "?": "Unknown"}


def describe(l):
    return (f"{l['address']}\n{l['rooms']} rooms · {l['size']} m² · "
            f"{l['price']} DKK/month · {STATUS_EN.get(l['status'], l['status'])}")


def notify(title, message, link):
    if not NTFY_TOPIC:
        print(f"[no NTFY_TOPIC set] {title}: {message}")
        return
    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=message.encode("utf-8"),
        headers={"Title": title.encode("utf-8"), "Click": urljoin(URL, link), "Tags": "house"},
        timeout=20,
    )


def main():
    if not URL:
        sys.exit("WATCH_URL secret is not set.")
    resp = requests.get(URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    html = resp.text
    print(f"HTTP {resp.status_code}, {len(html)} chars")
    print(f"Listing IDs found in raw HTML: {len(set(CASE_RE.findall(html)))}")
    current = parse_listings(html)

    if not current:
        # Page layout probably changed. Fail loudly so GitHub emails you,
        # and don't overwrite the saved state.
        sys.exit("No listings parsed. The page structure may have changed.")

    first_run = not STATE_FILE.exists()
    seen = {}
    if not first_run:
        try:
            seen = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except ValueError:
            print("seen.json was damaged; starting fresh (no alerts this run).")
            first_run = True

    if os.environ.get("TEST_NOTIFY") == "true":
        l = next(iter(current.values()))
        notify("🧪 Test from listing watcher", f"It works! Example listing:\n{describe(l)}", l["link"])
        print("Test notification sent.")

    if not first_run:
        for cid, l in current.items():
            summary = describe(l)
            if cid not in seen:
                notify("🏠 New home listed", summary, l["link"])
            elif NOTIFY_ON_AVAILABLE and l["status"] == "Ledig" and seen[cid].get("status") != "Ledig":
                notify("✅ Home available again", summary, l["link"])
    else:
        print(f"First run: saved {len(current)} existing listings, no notifications sent.")

    # Keep old entries too, so a listing that disappears and returns isn't re-announced
    seen.update({cid: {"status": l["status"]} for cid, l in current.items()})
    STATE_FILE.write_text(json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Checked {len(current)} listings.")


if __name__ == "__main__":
    main()

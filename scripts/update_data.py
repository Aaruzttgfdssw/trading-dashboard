#!/usr/bin/env python3
"""
Holt echte Daten und schreibt sie nach data/latest.json.

Quellen (alle kostenlos, ohne Anmeldung):
  - Kurse:   CoinGecko        https://api.coingecko.com
  - Kerzen:  Binance (Markt-  https://data-api.binance.vision
             daten), Ersatz: CoinGecko
  - News:    RSS von CoinDesk und Cointelegraph

Es werden KEINE Daten erfunden. Schlägt eine Quelle fehl, bleibt der letzte
echte Stand erhalten und wird auf der Seite als "veraltet" markiert.
Es werden keine Käufe oder Verkäufe ausgeführt.
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "data", "latest.json")
UA = "Mozilla/5.0 (compatible; trading-dashboard-learning-project)"

COINS = [
    {"id": "bitcoin", "symbol": "BTC", "name": "Bitcoin", "binance": "BTCUSDT"},
    {"id": "ethereum", "symbol": "ETH", "name": "Ether", "binance": "ETHUSDT"},
    {"id": "solana", "symbol": "SOL", "name": "Solana", "binance": "SOLUSDT"},
    {"id": "ripple", "symbol": "XRP", "name": "XRP", "binance": "XRPUSDT"},
    {"id": "dogecoin", "symbol": "DOGE", "name": "Dogecoin", "binance": "DOGEUSDT"},
]

FEEDS = [
    # (Name, Adresse, Bereich)
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/", "Krypto"),
    ("Cointelegraph", "https://cointelegraph.com/rss", "Krypto"),
    ("Decrypt", "https://decrypt.co/feed", "Krypto"),
    ("BBC Welt", "https://feeds.bbci.co.uk/news/world/rss.xml", "Welt"),
    ("BBC Wirtschaft", "https://feeds.bbci.co.uk/news/business/rss.xml", "Wirtschaft"),
    ("OilPrice", "https://oilprice.com/rss/main", "Rohstoffe"),
    ("tagesschau Wirtschaft", "https://www.tagesschau.de/wirtschaft/index~rss2.xml", "Wirtschaft"),
    ("BTC-ECHO", "https://www.btc-echo.de/feed/", "Krypto"),
]
GERMAN_FEEDS = {"tagesschau Wirtschaft", "BTC-ECHO"}

# ETFs (US-Börse). Kurse kommen von Yahoo Finance, Ersatz: Stooq.
ETFS = [
    {"sym": "SPY", "name": "S&P 500", "gruppe": "Breiter Markt", "tv": "AMEX:SPY"},
    {"sym": "QQQ", "name": "Nasdaq 100", "gruppe": "Breiter Markt", "tv": "NASDAQ:QQQ"},
    {"sym": "URTH", "name": "MSCI World", "gruppe": "Breiter Markt", "tv": "AMEX:URTH"},
    {"sym": "GLD", "name": "Gold", "gruppe": "Rohstoffe", "tv": "AMEX:GLD"},
    {"sym": "SLV", "name": "Silber", "gruppe": "Rohstoffe", "tv": "AMEX:SLV"},
    {"sym": "USO", "name": "Rohöl", "gruppe": "Rohstoffe", "tv": "AMEX:USO"},
    {"sym": "UNG", "name": "Erdgas", "gruppe": "Rohstoffe", "tv": "AMEX:UNG"},
    {"sym": "XLE", "name": "Energie-Aktien", "gruppe": "Branchen", "tv": "AMEX:XLE"},
    {"sym": "ITA", "name": "Rüstung und Luftfahrt", "gruppe": "Branchen", "tv": "ITA"},
    {"sym": "IBIT", "name": "Bitcoin (BlackRock)", "gruppe": "Krypto-ETFs", "tv": "NASDAQ:IBIT"},
    {"sym": "ETHA", "name": "Ether (BlackRock)", "gruppe": "Krypto-ETFs", "tv": "NASDAQ:ETHA"},
]

# Stichworte, mit denen Meldungen einem Bereich zugeordnet werden.
TAGS = {
    "Prominente": ["trump", "musk", "biden", "white house", "weißes haus", "elon", "powell", "xi jinping", "putin", "lagarde"],
    "ETF": [" etf", "etfs", "blackrock", "grayscale"],
    "Regulierung": ["sec ", "regulat", "ban ", "lawmaker", "tax", "cftc", "parliament", "law ", "sanction",
                    "regulier", "verbot", "steuer", "bafin", "gesetz", "sanktion", "mica"],
    "Krieg/Konflikt": ["war ", "war,", "war.", "iran", "israel", "ukraine", "russia", "hormuz", "missile",
                       "attack", "houthi", "taiwan", "military", "troops", "ceasefire",
                       "krieg", "angriff", "rakete", "militär", "waffenruhe", "konflikt", "nahost"],
    "Rohstoffe": ["oil", "crude", "brent", "opec", "natural gas", "lng", "gold", "silver", "copper",
                  "lithium", "uranium", "rare earth", "wheat", "ölpreis", "rohöl", "erdgas", "silber", "kupfer", "seltene erden"],
    "Zinsen/Wirtschaft": ["fed ", "interest rate", "inflation", "ecb", "recession", "tariff", "jobs report", "gdp",
                          "zins", "ezb", "notenbank", "rezession", "zoll", "zölle", "konjunktur", "dax"],
    "Hack/Betrug": ["hack", "exploit", "rug pull", "scam", "stolen", "drain", "betrug", "gestohlen"],
    "Memecoins": ["memecoin", "meme coin", "pump.fun", "dogecoin", "pepe", "shiba", "bonk", "dogwifhat"],
}


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def http_get(url, timeout=25):
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (attempt + 1))
    raise last


# ---------------------------------------------------------------- Kurse
def prices_binance():
    """Ersatzquelle, falls CoinGecko gerade blockiert: ohne 7-Tage-Wert und Marktwert."""
    syms = json.dumps([c["binance"] for c in COINS], separators=(",", ":"))
    url = "https://data-api.binance.vision/api/v3/ticker/24hr?symbols=" + urllib.parse.quote(syms)
    rows = {r["symbol"]: r for r in json.loads(http_get(url))}
    out = []
    for c in COINS:
        r = rows.get(c["binance"])
        if not r:
            continue
        out.append({
            "id": c["id"], "symbol": c["symbol"], "name": c["name"],
            "preis": float(r["lastPrice"]), "aend24": float(r["priceChangePercent"]),
            "aend7": None, "marktkap": None, "volumen": float(r["quoteVolume"]),
        })
    if not out:
        raise RuntimeError("Binance lieferte keine Kurse")
    return {"stand": now_iso(), "quelle": "Binance (Ersatzquelle)", "daten": out}


def fetch_prices():
    try:
        return prices_coingecko()
    except Exception as e:  # noqa: BLE001
        print(f"  CoinGecko nicht erreichbar ({e}), versuche Binance")
        return prices_binance()


def prices_coingecko():
    ids = ",".join(c["id"] for c in COINS)
    url = ("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=" + ids +
           "&price_change_percentage=24h,7d")
    rows = {r["id"]: r for r in json.loads(http_get(url))}
    out = []
    for c in COINS:
        r = rows.get(c["id"])
        if not r or r.get("current_price") is None:
            continue
        out.append({
            "id": c["id"], "symbol": c["symbol"], "name": c["name"],
            "preis": r["current_price"],
            "aend24": r.get("price_change_percentage_24h_in_currency"),
            "aend7": r.get("price_change_percentage_7d_in_currency"),
            "marktkap": r.get("market_cap"),
            "volumen": r.get("total_volume"),
        })
    if not out:
        raise RuntimeError("CoinGecko lieferte keine Kurse")
    return {"stand": now_iso(), "quelle": "CoinGecko", "daten": out}


# --------------------------------------------------------------- Kerzen
def candles_binance(symbol):
    url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval=1d&limit=30"
    rows = json.loads(http_get(url))
    out = []
    for r in rows:
        d = datetime.fromtimestamp(r[0] / 1000, timezone.utc).strftime("%Y-%m-%d")
        out.append({"d": d, "o": float(r[1]), "h": float(r[2]), "l": float(r[3]), "c": float(r[4])})
    return out


def candles_coingecko(coin_id):
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc?vs_currency=usd&days=30"
    rows = json.loads(http_get(url))
    days = {}
    for ts, o, h, l, c in rows:
        d = datetime.fromtimestamp(ts / 1000, timezone.utc).strftime("%Y-%m-%d")
        if d not in days:
            days[d] = {"d": d, "o": o, "h": h, "l": l, "c": c}
        else:
            x = days[d]
            x["h"] = max(x["h"], h)
            x["l"] = min(x["l"], l)
            x["c"] = c
    return [days[k] for k in sorted(days)]


def fetch_candles():
    data, quelle = {}, set()
    for c in COINS:
        rows = None
        try:
            rows = candles_binance(c["binance"])
            quelle.add("Binance")
        except Exception as e:  # noqa: BLE001
            print(f"  Binance für {c['symbol']} nicht erreichbar ({e}), versuche CoinGecko")
            try:
                time.sleep(2)
                rows = candles_coingecko(c["id"])
                quelle.add("CoinGecko")
            except Exception as e2:  # noqa: BLE001
                print(f"  Auch CoinGecko für {c['symbol']} ohne Ergebnis ({e2})")
        if rows:
            data[c["symbol"]] = rows
    if not data:
        raise RuntimeError("Keine Kerzen erhalten")
    return {"stand": now_iso(), "quelle": " und ".join(sorted(quelle)), "daten": data}


# ----------------------------------------------------------------- News
def clean(text, limit=240):
    text = re.sub(r"<[^>]+>", " ", unescape(text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# Wie stark kann eine Meldung Kurse bewegen? 0 = kaum, 3 = stark.
STRONG = ["approv", "reject", "ban ", "bans ", "banned", "hack", "exploit", "rate cut", "rate hike", "cuts rates",
          "raises rates", "lawsuit", "sues ", "charged", "sanction", "attack", "invasion", "ceasefire", "record high",
          "all-time high", "crash", "plunge", "tumbl", "soar", "surge", "delist", "listing", "bankrupt", "liquidat",
          "executive order", "tariff", "etf", "inflows", "outflows", "fed ", "sec ", "opec", "strait of hormuz",
          "missile", "default", "emergency", "halt", "freez", "seiz", "arrest", "merger", "acquisition", "earnings",
          "genehmig", "verbot", "angriff", "zinssenkung", "zinserhöhung", "rekordhoch", "absturz", "einbruch", "zölle",
          "sanktion", "pleite", "insolvenz", "übernahme", "ölpreis", "notenbank"]
NOISE = ["price prediction", "prediction:", "could reach", "how to ", "guide", "best ", "top 10", "top 5", "podcast",
         "opinion", "sponsored", "review", "quiz", "explained", "what is ", "newsletter", "week in review",
         "here's why", "analyst says", "should you", "watch:", "video:", "live updates",
         "prognose:", "kursziel", "so kaufen", "anleitung", "ratgeber", "podcast", "kommentar", "meinung", "liveblog", "quiz"]


def importance(title, summary, tags):
    t = " " + title.lower() + " "
    if any(n in t for n in NOISE):
        return 0
    score = min(2, len(tags))
    if any(w in t for w in STRONG):
        score += 1
    if "Prominente" in tags and any(w in t for w in ["crypto", "bitcoin", "coin", "token", "tariff", "order", "oil", "rate"]):
        score += 1
    return min(3, score)


def tag_item(title, summary):
    hay = " " + (title + " " + summary).lower() + " "
    return [tag for tag, words in TAGS.items() if any(w in hay for w in words)]


def fetch_news():
    items, seen = [], set()
    ok_feeds = []
    for name, url, bereich in FEEDS:
        try:
            root = ET.fromstring(http_get(url))
        except Exception as e:  # noqa: BLE001
            print(f"  Feed {name} nicht lesbar ({e})")
            continue
        ok_feeds.append(name)
        for n, it in enumerate(root.iter("item")):
            if n >= 25:
                break
            title = clean(it.findtext("title"), 200)
            link = (it.findtext("link") or "").strip()
            if not title or not link or link in seen:
                continue
            try:
                dt = parsedate_to_datetime(it.findtext("pubDate"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            except Exception:  # noqa: BLE001
                continue
            seen.add(link)
            summary = clean(it.findtext("description"))
            items.append({
                "titel": title, "link": link, "quelle": name, "bereich": bereich,
                "sprache": "de" if name in GERMAN_FEEDS else "en",
                "zeit": dt.astimezone(timezone.utc).isoformat(timespec="seconds"),
                "text": summary, "tags": (tg := tag_item(title, summary)), "wichtig": importance(title, summary, tg),
            })
    if not items:
        raise RuntimeError("Keine Nachrichten erhalten")
    items.sort(key=lambda x: x["zeit"], reverse=True)
    return {"stand": now_iso(), "quelle": ", ".join(ok_feeds), "daten": items[:90]}


# ----------------------------------------------------------------- ETFs
def etf_yahoo(sym):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1y&interval=1d"
    r = json.loads(http_get(url))["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    rows = []
    for i, ts in enumerate(r["timestamp"]):
        vals = [q["open"][i], q["high"][i], q["low"][i], q["close"][i]]
        if any(v is None for v in vals):
            continue
        d = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")
        rows.append({"d": d, "o": round(vals[0], 4), "h": round(vals[1], 4), "l": round(vals[2], 4),
                     "c": round(vals[3], 4), "v": q["volume"][i] or 0})
    return rows


def etf_stooq(sym):
    url = f"https://stooq.com/q/d/l/?s={sym.lower()}.us&i=d"
    lines = http_get(url).decode("utf-8", "replace").strip().splitlines()
    rows = []
    for line in lines[1:]:
        p = line.split(",")
        if len(p) < 5:
            continue
        try:
            rows.append({"d": p[0], "o": float(p[1]), "h": float(p[2]), "l": float(p[3]), "c": float(p[4]),
                         "v": float(p[5]) if len(p) > 5 and p[5] else 0})
        except ValueError:
            continue
    return rows[-270:]


def fetch_etfs():
    out, quelle = [], set()
    for e in ETFS:
        rows = None
        for name, fn in (("Yahoo Finance", etf_yahoo), ("Stooq", etf_stooq)):
            try:
                rows = fn(e["sym"])
                if len(rows) >= 2:
                    quelle.add(name)
                    break
            except Exception as ex:  # noqa: BLE001
                print(f"  {name} für {e['sym']} ohne Ergebnis ({ex})")
            rows = None
        time.sleep(0.5)
        if not rows:
            continue
        last = rows[-1]["c"]
        def chg(n):
            return (last / rows[-1 - n]["c"] - 1) * 100 if len(rows) > n else None
        a1d, a1w, a1m = chg(1), chg(5), chg(21)
        a1y = chg(250) if len(rows) > 250 else ((last / rows[0]["c"] - 1) * 100 if len(rows) > 200 else None)
        out.append({**e, "preis": last, "aend1d": a1d, "aend1w": a1w, "aend1m": a1m, "aend1y": a1y,
                    "datum": rows[-1]["d"], "kerzen": rows[-90:]})
    if not out:
        raise RuntimeError("Keine ETF-Kurse erhalten")
    return {"stand": now_iso(), "quelle": " und ".join(sorted(quelle)), "daten": out}


# -------------------------------------------------------------- Chancen
def build_signals(kurse, news, etfs=None):
    """Regelbasierte Auffälligkeiten. Das ist keine Kaufempfehlung."""
    signals = []
    for e in (etfs or {}).get("daten", []):
        a = e.get("aend1d")
        if a is not None and abs(a) >= 2.5:
            richtung = "gestiegen" if a > 0 else "gefallen"
            signals.append({
                "coin": e["name"], "symbol": e["sym"], "art": "Starke Tagesbewegung (ETF)",
                "erklaerung": f"Der ETF {e['sym']} ({e['name']}) ist am letzten Handelstag um {abs(a):.1f} % {richtung}. Für einen breit gestreuten Fonds ist das viel.",
                "risiko": "Mittel. Große Tagesbewegungen bei ETFs hängen oft an einer Nachricht und können sich am nächsten Tag umkehren.",
            })
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    recent = [n for n in (news or {}).get("daten", [])
              if datetime.fromisoformat(n["zeit"]) >= cutoff]
    for c in (kurse or {}).get("daten", []):
        a24, a7 = c.get("aend24"), c.get("aend7")
        belege = []
        if a24 is not None and a24 >= 8:
            signals.append({
                "coin": c["name"], "symbol": c["symbol"], "art": "Starker Anstieg",
                "erklaerung": f"{c['name']} ist in 24 Stunden um {a24:.1f} % gestiegen. Wer jetzt kauft, steigt nach dem Anstieg ein.",
                "risiko": "Hoch. Nach schnellen Sprüngen fallen Kurse oft wieder zurück.",
            })
        elif a24 is not None and a24 <= -8:
            signals.append({
                "coin": c["name"], "symbol": c["symbol"], "art": "Starker Rückgang",
                "erklaerung": f"{c['name']} ist in 24 Stunden um {abs(a24):.1f} % gefallen. Manche hoffen dann auf eine Erholung.",
                "risiko": "Hoch. Ein Kurs, der gefallen ist, kann weiter fallen. Eine Erholung ist nicht garantiert.",
            })
        elif a7 is not None and abs(a7) >= 15:
            richtung = "gestiegen" if a7 > 0 else "gefallen"
            signals.append({
                "coin": c["name"], "symbol": c["symbol"], "art": "Starke Woche",
                "erklaerung": f"{c['name']} ist in 7 Tagen um {abs(a7):.1f} % {richtung}.",
                "risiko": "Mittel bis hoch. Starke Wochenbewegungen können sich umkehren.",
            })
        names = [c["name"].lower(), c["symbol"].lower()]
        hits = [n for n in recent if any(re.search(r"\b" + re.escape(w) + r"\b", n["titel"].lower()) for w in names)]
        if len(hits) >= 2:
            belege = [h["titel"] for h in hits[:2]]
            signals.append({
                "coin": c["name"], "symbol": c["symbol"], "art": "Viele Meldungen",
                "erklaerung": f"In den letzten 24 Stunden gibt es {len(hits)} Meldungen, in denen {c['name']} im Titel steht.",
                "risiko": "Mittel. Viel Aufmerksamkeit führt oft zu stärkeren Schwankungen, in beide Richtungen.",
                "belege": belege,
            })
    return {"stand": now_iso(), "regeln": "Krypto: Anstieg oder Rückgang ab 8 % in 24 Stunden, 15 % in 7 Tagen, mindestens 2 Meldungen in 24 Stunden. ETFs: Tagesbewegung ab 2,5 %",
            "daten": signals}


# ----------------------------------------------------------------- Main
def load_old():
    try:
        with open(OUT, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def main():
    old = load_old()
    result = {"erzeugt": now_iso()}
    fresh = 0
    for key, fn in (("kurse", fetch_prices), ("kerzen", fetch_candles), ("news", fetch_news), ("etfs", fetch_etfs)):
        print(f"Hole {key} ...")
        try:
            result[key] = fn()
            fresh += 1
        except Exception as e:  # noqa: BLE001
            print(f"  FEHLER bei {key}: {e}")
            if old.get(key):
                result[key] = dict(old[key])
                result[key]["veraltet"] = True
            result.setdefault("fehler", []).append(f"{key}: {e}")
    result["chancen"] = build_signals(result.get("kurse"), result.get("news"), result.get("etfs"))
    if fresh == 0:
        print("Keine Quelle erreichbar, nichts geschrieben.")
        return 1
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    print(f"Fertig: {fresh} von 4 Quellen frisch, geschrieben nach data/latest.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())

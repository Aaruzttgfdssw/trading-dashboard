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
    # In Deutschland kaufbare ETFs (UCITS), Kurse von Xetra in Euro
    {"sym": "EUNL", "yahoo": "EUNL.DE", "stooq": "eunl.de", "name": "iShares Core MSCI World", "isin": "IE00B4L5Y983",
     "ter": "ca. 0,20 %", "region": "Welt (Industrieländer)", "tv": "XETR:EUNL", "art": "ETF"},
    {"sym": "VWCE", "yahoo": "VWCE.DE", "stooq": "vwce.de", "name": "Vanguard FTSE All-World", "isin": "IE00BK5BQT80",
     "ter": "ca. 0,19 %", "region": "Ganze Welt inkl. Schwellenländer", "tv": "XETR:VWCE", "art": "ETF"},
    {"sym": "SXR8", "yahoo": "SXR8.DE", "stooq": "sxr8.de", "name": "iShares Core S&P 500", "isin": "IE00B5BMR087",
     "ter": "ca. 0,07 %", "region": "USA", "tv": "XETR:SXR8", "art": "ETF"},
    {"sym": "IS3N", "yahoo": "IS3N.DE", "stooq": "is3n.de", "name": "iShares Core MSCI EM IMI", "isin": "IE00BKM4GZ66",
     "ter": "ca. 0,18 %", "region": "Schwellenländer", "tv": "XETR:IS3N", "art": "ETF"},
    {"sym": "SXRV", "yahoo": "SXRV.DE", "stooq": "sxrv.de", "name": "iShares Nasdaq 100", "isin": "IE00B53SZB19",
     "ter": "ca. 0,30 %", "region": "US-Technologie", "tv": "XETR:SXRV", "art": "ETF"},
    {"sym": "4GLD", "yahoo": "4GLD.DE", "stooq": "4gld.de", "name": "Xetra-Gold", "isin": "DE000A0S9GB0",
     "ter": "ca. 0,3 %", "region": "Gold", "tv": "XETR:4GLD", "art": "ETC"},
    {"sym": "XDWD", "yahoo": "XDWD.DE", "stooq": "xdwd.de", "name": "Xtrackers MSCI World", "isin": "IE00BJ0KDQ92",
     "ter": "ca. 0,19 %", "region": "Welt (Industrieländer)", "tv": "XETR:XDWD", "art": "ETF"},
    {"sym": "IUSQ", "yahoo": "IUSQ.DE", "stooq": "iusq.de", "name": "iShares MSCI ACWI", "isin": "IE00B6R52259",
     "ter": "ca. 0,20 %", "region": "Ganze Welt inkl. Schwellenländer", "tv": "XETR:IUSQ", "art": "ETF"},
    {"sym": "VGWL", "yahoo": "VGWL.DE", "stooq": "vgwl.de", "name": "Vanguard FTSE All-World (ausschüttend)", "isin": "IE00B3RBWM25",
     "ter": "ca. 0,22 %", "region": "Ganze Welt inkl. Schwellenländer", "tv": "XETR:VGWL", "art": "ETF"},
    {"sym": "EXS1", "yahoo": "EXS1.DE", "stooq": "exs1.de", "name": "iShares Core DAX", "isin": "DE0005933931",
     "ter": "ca. 0,16 %", "region": "Deutschland", "tv": "XETR:EXS1", "art": "ETF"},
    {"sym": "EXSA", "yahoo": "EXSA.DE", "stooq": "exsa.de", "name": "iShares STOXX Europe 600", "isin": "DE0002635307",
     "ter": "ca. 0,20 %", "region": "Europa", "tv": "XETR:EXSA", "art": "ETF"},
    {"sym": "XDWT", "yahoo": "XDWT.DE", "stooq": "xdwt.de", "name": "Xtrackers MSCI World IT", "isin": "IE00BM67HT60",
     "ter": "ca. 0,25 %", "region": "Technologie weltweit", "tv": "XETR:XDWT", "art": "ETF"},
    {"sym": "DFEN", "yahoo": "DFEN.DE", "stooq": "dfen.de", "name": "VanEck Defense", "isin": "IE000YYE6WK5",
     "ter": "ca. 0,55 %", "region": "Rüstung", "tv": "XETR:DFEN", "art": "ETF"},
    {"sym": "IQQH", "yahoo": "IQQH.DE", "stooq": "iqqh.de", "name": "iShares Global Clean Energy", "isin": "IE00B1XNHC34",
     "ter": "ca. 0,65 %", "region": "Saubere Energie", "tv": "XETR:IQQH", "art": "ETF"},
    {"sym": "XAIX", "yahoo": "XAIX.DE", "stooq": "xaix.de", "name": "Xtrackers Artificial Intelligence & Big Data", "isin": "IE00BGV5VN51",
     "ter": "ca. 0,35 %", "region": "KI (Künstliche Intelligenz)", "tv": "XETR:XAIX", "art": "ETF"},
    {"sym": "VVSM", "yahoo": "VVSM.DE", "stooq": "vvsm.de", "name": "VanEck Semiconductor (Chips, u. a. Nvidia)", "isin": "IE00BMC38736",
     "ter": "ca. 0,35 %", "region": "KI-Chips (Halbleiter)", "tv": "XETR:VVSM", "art": "ETF"},
    {"sym": "2B76", "yahoo": "2B76.DE", "stooq": "2b76.de", "name": "iShares Automation & Robotics", "isin": "IE00BYZK4552",
     "ter": "ca. 0,40 %", "region": "KI und Robotik", "tv": "XETR:2B76", "art": "ETF"},
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
    url = ("https://api.coingecko.com/api/v3/coins/markets?vs_currency=eur&ids=" + ids +
           "&price_change_percentage=24h,7d,1y")
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
            "aend1y": r.get("price_change_percentage_1y_in_currency"),
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
STRONG = ["approv", "reject", "ban ", "bans ", "banned", "rate cut", "rate hike", "cuts rates",
          "raises rates", "lawsuit", "sues ", "charged", "sanction", "attack", "invasion", "ceasefire", "record high",
          "all-time high", "crash", "plunge", "tumbl", "soar", "surge", "delist", "listing", "bankrupt", "liquidat",
          "executive order", "tariff", "etf", "inflows", "outflows", "fed ", "sec ", "opec", "strait of hormuz",
          "missile", "default", "emergency", "halt", "freez", "seiz", "arrest", "merger", "acquisition", "earnings",
          "genehmig", "verbot", "angriff", "zinssenkung", "zinserhöhung", "rekordhoch", "absturz", "einbruch", "zölle",
          "sanktion", "pleite", "insolvenz", "übernahme", "ölpreis", "notenbank", "leitzins"]
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
    tags = [tag for tag, words in TAGS.items() if any(w in hay for w in words)]
    # "Hack/Betrug" nur, wenn es wirklich um Krypto oder Finanzen geht (nicht z. B. "ausgenutzt" in der Politik)
    if "Hack/Betrug" in tags and not any(w in hay for w in ["crypto", "krypto", "bitcoin", "token", "exchange", "börse", "defi", "wallet", "protocol", "bank"]):
        tags.remove("Hack/Betrug")
    return tags


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


# ----------------------------------------------------- Deutsche Kurzfassung
def first_sentence(text, limit=200):
    text = (text or "").strip()
    m = re.search(r"^(.{40,}?[.!?])(\s|$)", text)
    t = m.group(1) if m else text
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"


def translate_de(text):
    if not text:
        return text
    url = "https://api.mymemory.translated.net/get?" + urllib.parse.urlencode({"q": text[:450], "langpair": "en|de"})
    j = json.loads(http_get(url, timeout=15))
    out = (j.get("responseData") or {}).get("translatedText")
    if j.get("responseStatus") != 200 or not out or "MYMEMORY WARNING" in out.upper():
        raise RuntimeError("Übersetzung nicht verfügbar")
    return unescape(out)


def add_german(news, old):
    """Gibt den wichtigsten Meldungen einen deutschen Titel und einen deutschen Satz. Bereits übersetzte werden wiederverwendet."""
    cache = {n["link"]: n for n in (old or {}).get("daten", []) if n.get("titel_de")}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    todo = [n for n in news["daten"] if n.get("wichtig", 0) >= 2 and datetime.fromisoformat(n["zeit"]) >= cutoff][:6]
    for n in news["daten"]:
        n["kurz"] = first_sentence(n.get("text"))
        if n.get("sprache") == "de":
            n["titel_de"], n["kurz_de"] = n["titel"], n["kurz"]
        elif n["link"] in cache:
            n["titel_de"], n["kurz_de"] = cache[n["link"]].get("titel_de"), cache[n["link"]].get("kurz_de")
    done = 0
    for n in todo:
        if n.get("titel_de"):
            continue
        try:
            n["titel_de"] = translate_de(n["titel"])
            n["kurz_de"] = translate_de(n["kurz"]) if n["kurz"] else ""
            done += 1
            time.sleep(0.5)
        except Exception as e:  # noqa: BLE001
            print(f"  Übersetzung übersprungen ({e})")
            break
    print(f"  {done} Meldungen neu übersetzt")


# ----------------------------------------------------------------- ETFs
def etf_yahoo(e):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{e['yahoo']}?range=5y&interval=1d"
    r = json.loads(http_get(url))["chart"]["result"][0]
    closes = r["indicators"]["quote"][0]["close"]
    rows = []
    for ts, c in zip(r["timestamp"], closes):
        if c is None:
            continue
        rows.append({"d": datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d"), "c": round(c, 4)})
    return rows


def etf_stooq(e):
    url = f"https://stooq.com/q/d/l/?s={e['stooq']}&i=d"
    lines = http_get(url).decode("utf-8", "replace").strip().splitlines()
    rows = []
    for line in lines[1:]:
        p = line.split(",")
        if len(p) >= 5:
            try:
                rows.append({"d": p[0], "c": float(p[4])})
            except ValueError:
                pass
    cutoff = (datetime.now(timezone.utc) - timedelta(days=5 * 366)).strftime("%Y-%m-%d")
    return [x for x in rows if x["d"] >= cutoff]


def _chg_since(rows, days):
    """Veränderung in % seit einem Datum vor `days` Tagen (letzter Kurs an oder vor diesem Tag)."""
    target = (datetime.strptime(rows[-1]["d"], "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
    past = [x for x in rows if x["d"] <= target]
    if not past:
        # Datenreihe beginnt knapp nach dem Stichtag (z. B. "5 Jahre" bei Yahoo): bis 14 Tage Abweichung erlauben
        first = datetime.strptime(rows[0]["d"], "%Y-%m-%d"); t = datetime.strptime(target, "%Y-%m-%d")
        if (first - t).days > 14:
            return None
        past = [rows[0]]
    return (rows[-1]["c"] / past[-1]["c"] - 1) * 100


def fetch_etfs():
    out, quelle = [], set()
    for e in ETFS:
        rows = None
        for name, fn in (("Yahoo Finance", etf_yahoo), ("Stooq", etf_stooq)):
            try:
                rows = fn(e)
                if len(rows) >= 2:
                    quelle.add(name)
                    break
            except Exception as ex:  # noqa: BLE001
                print(f"  {name} für {e['sym']} ohne Ergebnis ({ex})")
            rows = None
        time.sleep(0.5)
        if not rows:
            continue
        a5 = _chg_since(rows, 5 * 365)
        pa5 = ((1 + a5 / 100) ** (1 / 5) - 1) * 100 if a5 is not None else None
        spark = rows[::5][-260:]
        out.append({k: v for k, v in e.items() if k not in ("yahoo", "stooq")} | {
            "preis": rows[-1]["c"], "datum": rows[-1]["d"], "aend1d": (rows[-1]["c"] / rows[-2]["c"] - 1) * 100,
            "aend1w": _chg_since(rows, 7), "aend1m": _chg_since(rows, 30),
            "aend1y": _chg_since(rows, 365), "aend3y": _chg_since(rows, 3 * 365), "aend5y": a5, "pa5y": pa5,
            "verlauf": [round(x["c"], 2) for x in spark]})
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
    for key, fn in (("kurse", fetch_prices), ("news", fetch_news), ("etfs", fetch_etfs)):
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
    if result.get("news") and not result["news"].get("veraltet"):
        try:
            add_german(result["news"], old.get("news"))
        except Exception as e:  # noqa: BLE001
            print(f"  Deutsche Kurzfassung nicht möglich ({e})")
    if fresh == 0:
        print("Keine Quelle erreichbar, nichts geschrieben.")
        return 1
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    print(f"Fertig: {fresh} von 3 Quellen frisch, geschrieben nach data/latest.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Local dev server: serves web/site and the same API as the Lambda, storing holdings in holdings.json.

Run: set FINNHUB_API_KEY (optional, prices show 0 without it), then `python local_server.py`.
"""
import json, os, urllib.parse, urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(ROOT, "site")
DATA = os.path.join(ROOT, "holdings.json")
WATCH = os.path.join(ROOT, "watchlist.json")
KEY = os.environ.get("FINNHUB_API_KEY", "")


def load(path=DATA):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def watch_row(symbol):
    quote = finnhub("quote", symbol)
    price = float(quote.get("c") or 0)
    prev = float(quote.get("pc") or 0)
    change = price - prev if price and prev else 0
    return {"symbol": symbol, "price": price, "change": change, "changePct": change / prev * 100 if prev else 0}


def finnhub(endpoint, symbol):
    if not KEY:
        return {}
    qs = urllib.parse.urlencode({"symbol": symbol, "token": KEY})
    try:
        with urllib.request.urlopen(f"https://finnhub.io/api/v1/{endpoint}?{qs}", timeout=8) as r:
            return json.load(r)
    except Exception:
        return {}


def enrich(stock):
    symbol = stock["symbol"].upper()
    quote = finnhub("quote", symbol)
    price = float(quote.get("c") or 0)
    shares, cost = float(stock["shares"]), float(stock["cost"])
    return {**stock, "symbol": symbol, "price": price, "value": price * shares, "profitLoss": (price - cost) * shares}


def company(symbol):
    import datetime
    today = datetime.date.today()
    params = {"symbol": symbol, "from": str(today - datetime.timedelta(days=7)), "to": str(today)}
    news = finnhub_params("company-news", params)
    profile = finnhub("stock/profile2", symbol)
    articles = [{"headline": a.get("headline", "No Title"), "url": a.get("url", "")}
                for a in (news if isinstance(news, list) else [])[:5] if a.get("headline") and a.get("url")]
    return {"symbol": symbol, "name": profile.get("name"), "logo": profile.get("logo"), "website": profile.get("weburl"), "news": articles}


def finnhub_params(endpoint, params):
    if not KEY:
        return {}
    qs = urllib.parse.urlencode({**params, "token": KEY})
    try:
        with urllib.request.urlopen(f"https://finnhub.io/api/v1/{endpoint}?{qs}", timeout=8) as r:
            return json.load(r)
    except Exception:
        return {}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=SITE, **kw)

    def send_json(self, status, body):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/holdings":
            return self.send_json(200, load())
        if self.path == "/portfolio":
            rows = [enrich(x) for x in load()]
            return self.send_json(200, {"holdings": rows, "totalValue": sum(x["value"] for x in rows),
                                        "totalProfitLoss": sum(x["profitLoss"] for x in rows)})
        if self.path == "/watchlist":
            return self.send_json(200, [watch_row(s) for s in load(WATCH)])
        if self.path.startswith("/company"):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            return self.send_json(200, company(q.get("symbol", [""])[0].upper()))
        super().do_GET()

    def do_PUT(self):
        if self.path == "/watchlist":
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or "[]")
                symbols = list(dict.fromkeys(str(s).strip().upper() for s in data if str(s).strip()))
            except (ValueError, TypeError) as exc:
                return self.send_json(400, {"error": str(exc)})
            with open(WATCH, "w", encoding="utf-8") as f:
                json.dump(symbols, f)
            return self.send_json(200, symbols)
        if self.path != "/holdings":
            return self.send_json(404, {"error": "Not found"})
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or "[]")
            clean = [{"symbol": str(x["symbol"]).upper(), "shares": float(x["shares"]), "cost": float(x["cost"])} for x in data]
        except (KeyError, ValueError, TypeError) as exc:
            return self.send_json(400, {"error": str(exc)})
        with open(DATA, "w", encoding="utf-8") as f:
            json.dump(clean, f)
        self.send_json(200, clean)


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"http://localhost:8000 (listening on {host})")
    ThreadingHTTPServer((host, 8000), Handler).serve_forever()

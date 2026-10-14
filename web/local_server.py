"""Local dev server: serves web/site and the same API as the Lambda, storing holdings in holdings.json.

Run: set FINNHUB_API_KEY (optional, prices show 0 without it), then `python local_server.py`.
"""
import json, os, urllib.parse, urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(ROOT, "site")
DATA = os.path.join(ROOT, "holdings.json")
KEY = os.environ.get("FINNHUB_API_KEY", "")


def load():
    if not os.path.exists(DATA):
        return []
    with open(DATA, encoding="utf-8") as f:
        return json.load(f)


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
        super().do_GET()

    def do_PUT(self):
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
    print("http://localhost:8000")
    ThreadingHTTPServer(("127.0.0.1", 8000), Handler).serve_forever()

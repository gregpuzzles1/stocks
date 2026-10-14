"""Lambda API for the public personal stock dashboard."""
import json, os, urllib.parse
import boto3, requests

TABLE = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
KEY = os.environ["FINNHUB_API_KEY"]
HEADERS = {"content-type": "application/json", "access-control-allow-origin": "*"}

def response(status, body):
    return {"statusCode": status, "headers": HEADERS, "body": json.dumps(body)}

def holdings():
    item = TABLE.get_item(Key={"id": "portfolio"}).get("Item", {"holdings": []})
    return item.get("holdings", [])

def enrich(stock):
    symbol = stock["symbol"].upper()
    quote = requests.get("https://finnhub.io/api/v1/quote", params={"symbol": symbol, "token": KEY}, timeout=8).json()
    profile = requests.get("https://finnhub.io/api/v1/stock/profile2", params={"symbol": symbol, "token": KEY}, timeout=8).json()
    price = float(quote.get("c") or 0)
    shares, cost = float(stock["shares"]), float(stock["cost"])
    return {**stock, "symbol": symbol, "price": price, "open": quote.get("o"), "high": quote.get("h"), "low": quote.get("l"), "previousClose": quote.get("pc"), "value": price * shares, "profitLoss": (price-cost)*shares, "exchange": profile.get("exchange"), "industry": profile.get("finnhubIndustry"), "logo": profile.get("logo"), "website": profile.get("weburl")}

def lambda_handler(event, context):
    method = event["requestContext"]["http"]["method"]
    path = event.get("rawPath", "")
    try:
        if method == "GET" and path.endswith("/holdings"):
            return response(200, holdings())
        if method == "GET" and path.endswith("/portfolio"):
            rows = [enrich(x) for x in holdings()]
            return response(200, {"holdings": rows, "totalValue": sum(x["value"] for x in rows), "totalProfitLoss": sum(x["profitLoss"] for x in rows)})
        if method in ("PUT", "POST") and path.endswith("/holdings"):
            data = json.loads(event.get("body") or "[]")
            if not isinstance(data, list): return response(400, {"error": "Expected a list of holdings"})
            clean = [{"symbol": str(x["symbol"]).upper(), "shares": float(x["shares"]), "cost": float(x["cost"])} for x in data]
            TABLE.put_item(Item={"id": "portfolio", "holdings": clean})
            return response(200, clean)
        return response(404, {"error": "Not found"})
    except (KeyError, ValueError, requests.RequestException) as exc:
        return response(400, {"error": str(exc)})

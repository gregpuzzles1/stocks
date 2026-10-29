"""Lambda API for the public personal stock dashboard."""
import base64
import datetime
import json
import os
import re
from decimal import Decimal, InvalidOperation

import boto3
import requests


TABLE = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
SECRET_ARN = os.environ["FINNHUB_SECRET_ARN"]
SECRETS = boto3.client("secretsmanager")
FINNHUB_API_KEY = None
SYMBOL_PATTERN = re.compile(r"[A-Z0-9][A-Z0-9.-]{0,14}\Z")


def _json_default(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def response(status, body):
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body, default=_json_default),
    }


def _get_finnhub_key():
    global FINNHUB_API_KEY
    if FINNHUB_API_KEY is None:
        result = SECRETS.get_secret_value(SecretId=SECRET_ARN)
        key = result.get("SecretString")
        if not key:
            raise RuntimeError("Finnhub API key secret has no string value")
        key = key.strip()
        if not key:
            raise RuntimeError("Finnhub API key secret has no string value")
        FINNHUB_API_KEY = key
    return FINNHUB_API_KEY


def _finnhub_get(path, params):
    result = requests.get(
        f"https://finnhub.io/api/v1/{path}",
        params=params,
        headers={"X-Finnhub-Token": _get_finnhub_key()},
        timeout=8,
    )
    result.raise_for_status()
    return result.json()


def _symbol(value):
    if not isinstance(value, str):
        raise ValueError("Symbol must be a string")
    symbol = value.strip().upper()
    if not SYMBOL_PATTERN.fullmatch(symbol):
        raise ValueError("Symbol is missing or invalid")
    return symbol


def _request_body(event):
    body = event.get("body")
    if not isinstance(body, str) or not body:
        raise ValueError("Request body is required")
    if event.get("isBase64Encoded"):
        try:
            body = base64.b64decode(body, validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            raise ValueError("Request body must be valid JSON") from None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        raise ValueError("Request body must be valid JSON") from None


def holdings():
    item = TABLE.get_item(Key={"id": "portfolio"}).get("Item", {"holdings": []})
    return item.get("holdings", [])


def enrich(stock):
    symbol = _symbol(stock["symbol"])
    quote = _finnhub_get("quote", {"symbol": symbol})
    profile = _finnhub_get("stock/profile2", {"symbol": symbol})
    price = float(quote.get("c") or 0)
    shares, cost = float(stock["shares"]), float(stock["cost"])
    return {
        **stock,
        "symbol": symbol,
        "price": price,
        "open": quote.get("o"),
        "high": quote.get("h"),
        "low": quote.get("l"),
        "previousClose": quote.get("pc"),
        "value": price * shares,
        "profitLoss": (price - cost) * shares,
        "exchange": profile.get("exchange"),
        "industry": profile.get("finnhubIndustry"),
        "logo": profile.get("logo"),
        "website": profile.get("weburl"),
    }


def company(symbol):
    today = datetime.date.today()
    news = _finnhub_get(
        "company-news",
        {
            "symbol": symbol,
            "from": str(today - datetime.timedelta(days=7)),
            "to": str(today),
        },
    )
    profile = _finnhub_get("stock/profile2", {"symbol": symbol})
    articles = [
        {"headline": article.get("headline"), "url": article.get("url")}
        for article in (news if isinstance(news, list) else [])
        if article.get("headline") and article.get("url")
    ][:5]
    return {
        "symbol": symbol,
        "name": profile.get("name"),
        "logo": profile.get("logo"),
        "website": profile.get("weburl"),
        "news": articles,
    }


def watchlist():
    item = TABLE.get_item(Key={"id": "watchlist"}).get("Item", {"symbols": []})
    return item.get("symbols", [])


def watch_row(symbol):
    quote = _finnhub_get("quote", {"symbol": symbol})
    price, previous = float(quote.get("c") or 0), float(quote.get("pc") or 0)
    change = price - previous if price and previous else 0
    return {
        "symbol": symbol,
        "price": price,
        "change": change,
        "changePct": change / previous * 100 if previous else 0,
    }


def _clean_holdings(data):
    if not isinstance(data, list):
        raise ValueError("Expected a list of holdings")
    clean = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("Each holding must be an object")
        try:
            symbol = _symbol(item["symbol"])
            shares = Decimal(str(item["shares"]))
            cost = Decimal(str(item["cost"]))
        except KeyError:
            raise ValueError("Each holding requires symbol, shares, and cost") from None
        except InvalidOperation:
            raise ValueError("Shares and cost must be numbers") from None
        if not shares.is_finite() or not cost.is_finite():
            raise ValueError("Shares and cost must be finite numbers")
        clean.append({"symbol": symbol, "shares": shares, "cost": cost})
    return clean


def _clean_watchlist(data):
    if not isinstance(data, list):
        raise ValueError("Expected a list of symbols")
    return list(dict.fromkeys(_symbol(symbol) for symbol in data))


def lambda_handler(event, context):
    try:
        method = event["requestContext"]["http"]["method"]
        path = event.get("rawPath", "").rstrip("/")
        if method == "GET" and path == "/holdings":
            return response(200, holdings())
        if method == "GET" and path == "/portfolio":
            rows = [enrich(stock) for stock in holdings()]
            return response(
                200,
                {
                    "holdings": rows,
                    "totalValue": sum(row["value"] for row in rows),
                    "totalProfitLoss": sum(row["profitLoss"] for row in rows),
                },
            )
        if method == "GET" and path == "/watchlist":
            return response(200, [watch_row(symbol) for symbol in watchlist()])
        if method == "PUT" and path == "/watchlist":
            symbols = _clean_watchlist(_request_body(event))
            TABLE.put_item(Item={"id": "watchlist", "symbols": symbols})
            return response(200, symbols)
        if method == "GET" and path == "/company":
            params = event.get("queryStringParameters") or {}
            return response(200, company(_symbol(params.get("symbol"))))
        if method == "PUT" and path == "/holdings":
            clean = _clean_holdings(_request_body(event))
            TABLE.put_item(Item={"id": "portfolio", "holdings": clean})
            return response(200, clean)
        return response(404, {"error": "Not found"})
    except (KeyError, TypeError):
        return response(400, {"error": "Invalid request"})
    except ValueError as exc:
        return response(400, {"error": str(exc)})
    except requests.RequestException:
        return response(502, {"error": "Finnhub request failed"})

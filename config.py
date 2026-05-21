import os

FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
SERPAPI_API_KEYS = os.environ.get("SERPAPI_API_KEYS", "")
TAVILY_API_KEYS = os.environ.get("TAVILY_API_KEYS", "")
SERVERCHAN3_SENDKEY = os.environ.get("SERVERCHAN3_SENDKEY", "")

YAHOO_TICKERS = {
    "SPY": "SPY",
    "QQQ": "QQQ",
    "DIA": "DIA",
    "RSP": "RSP",
    "SOX": "^SOX",
    "SOXX": "SOXX",
    "VIX": "^VIX",
    "VXN": "^VXN",
    "VIX3M": "^VIX3M",
    "SKEW": "^SKEW",
    "DXY": "DX-Y.NYB",
    "US10Y": "^TNX",
    "XLY": "XLY",
    "XLU": "XLU",
    "COPPER": "HG=F",
    "GOLD": "GC=F",
}

LEADING_STOCKS = ["NVDA", "MSFT", "META", "AMZN", "AAPL", "GOOGL", "TSLA"]

FRED_SERIES = {
    "TIPS": "DFII10",
    "T10Y2Y": "T10Y2Y",
    "US2Y": "DGS2",
    "HY_OAS": "BAMLH0A0HYM2",
    "M2": "M2SL",
    "SAHM": "SAHMREALTIME",
    "UNRATE": "UNRATE",
    "ICSA": "ICSA",
    "CPI": "CPIAUCSL",
    "PAYEMS": "PAYEMS",
}

LOOKBACK_CALENDAR_DAYS = 500
MA50 = 50
MA200 = 200
MA250 = 250
RSI_PERIOD = 14

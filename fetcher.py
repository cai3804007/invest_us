import yfinance as yf
import pandas as pd
import requests
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import YAHOO_TICKERS, LEADING_STOCKS, FRED_SERIES, FRED_API_KEY, LOOKBACK_CALENDAR_DAYS, POSITION_TARGETS


class MarketDataFetcher:

    def __init__(self):
        self.yahoo_data = {}
        self.fred_data = {}
        self.fear_greed = None
        self._errors = []

    def fetch_all(self, console=None):
        if console:
            console.print("[bold cyan]正在获取市场数据...[/]")
        self._fetch_yahoo(console)
        self._fetch_fred(console)
        self._fetch_fear_greed(console)
        if console and self._errors:
            for err in self._errors:
                console.print(f"  [dim]{err}[/]")
        return self

    # ------------------------------------------------------------------
    # Yahoo Finance
    # ------------------------------------------------------------------

    def _download_one(self, symbol):
        try:
            end = datetime.now()
            start = end - timedelta(days=LOOKBACK_CALENDAR_DAYS)
            tk = yf.Ticker(symbol)
            df = tk.history(start=start, end=end, auto_adjust=True)
            if df is not None and not df.empty:
                if df.index.tz is not None:
                    df.index = df.index.tz_localize(None)
                return df
        except Exception:
            pass
        return pd.DataFrame()

    def _fetch_yahoo(self, console=None):
        all_items = [(n, s) for n, s in YAHOO_TICKERS.items()]
        all_items += [(s, s) for s in LEADING_STOCKS]
        # Add position-target tickers (e.g. QQQM) that aren't already covered
        for name, cfg in POSITION_TARGETS.items():
            ticker = cfg["ticker"]
            if ticker not in dict(all_items).values():
                all_items.append((ticker, ticker))

        if console:
            console.print(f"  [dim]Yahoo Finance: {len(all_items)} 个标的...[/]")

        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = {pool.submit(self._download_one, sym): name for name, sym in all_items}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    df = future.result()
                    if not df.empty:
                        self.yahoo_data[name] = df
                    else:
                        self._errors.append(f"Yahoo: {name} 无数据")
                except Exception as e:
                    self._errors.append(f"Yahoo: {name} 失败 ({e})")

    # ------------------------------------------------------------------
    # FRED
    # ------------------------------------------------------------------

    def _fetch_fred(self, console=None):
        if not FRED_API_KEY:
            if console:
                console.print("  [yellow]未设置 FRED_API_KEY，跳过 FRED 数据（TIPS/HY_OAS/M2/萨姆规则等）[/]")
                console.print("  [dim]免费申请: https://fred.stlouisfed.org/docs/api/api_key.html[/]")
                console.print("  [dim]设置方法: export FRED_API_KEY=你的key[/]")
            return

        if console:
            console.print(f"  [dim]FRED: {len(FRED_SERIES)} 个序列...[/]")

        end_str = datetime.now().strftime("%Y-%m-%d")
        start_str = (datetime.now() - timedelta(days=LOOKBACK_CALENDAR_DAYS)).strftime("%Y-%m-%d")

        for name, series_id in FRED_SERIES.items():
            try:
                url = "https://api.stlouisfed.org/fred/series/observations"
                params = {
                    "series_id": series_id,
                    "api_key": FRED_API_KEY,
                    "file_type": "json",
                    "observation_start": start_str,
                    "observation_end": end_str,
                    "sort_order": "asc",
                }
                resp = requests.get(url, params=params, timeout=15)
                data = resp.json()
                if "observations" in data:
                    rows = []
                    for o in data["observations"]:
                        if o["value"] != ".":
                            rows.append({"date": o["date"], "value": float(o["value"])})
                    if rows:
                        df = pd.DataFrame(rows)
                        df["date"] = pd.to_datetime(df["date"])
                        df = df.set_index("date").sort_index()
                        self.fred_data[name] = df
            except Exception as e:
                self._errors.append(f"FRED: {name} 失败 ({e})")

    # ------------------------------------------------------------------
    # CNN Fear & Greed
    # ------------------------------------------------------------------

    def _fetch_fear_greed(self, console=None):
        if console:
            console.print("  [dim]CNN Fear & Greed...[/]")
        try:
            url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
            headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
            resp = requests.get(url, headers=headers, timeout=10)
            data = resp.json()
            if "fear_and_greed" in data:
                self.fear_greed = data["fear_and_greed"].get("score")
                self.fear_greed_label = data["fear_and_greed"].get("rating", "")
        except Exception:
            self.fear_greed = None
            self.fear_greed_label = ""
            self._errors.append("CNN Fear & Greed 获取失败")

    # ------------------------------------------------------------------
    # Helper accessors
    # ------------------------------------------------------------------

    def get_series(self, name, field="Close"):
        if name in self.yahoo_data:
            df = self.yahoo_data[name]
            if field in df.columns:
                return df[field].dropna()
        return None

    def get_latest(self, name, field="Close"):
        s = self.get_series(name, field)
        if s is not None and len(s) > 0:
            return float(s.iloc[-1])
        return None

    def get_fred_series(self, name):
        if name in self.fred_data:
            return self.fred_data[name]["value"]
        return None

    def get_fred_latest(self, name):
        s = self.get_fred_series(name)
        if s is not None and len(s) > 0:
            return float(s.iloc[-1])
        return None

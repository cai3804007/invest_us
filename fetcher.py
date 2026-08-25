import yfinance as yf
import pandas as pd
import requests
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import (YAHOO_TICKERS, LEADING_STOCKS, FRED_SERIES, FRED_API_KEY,
                    FRED_SCALE, LOOKBACK_CALENDAR_DAYS, POSITION_TARGETS)


class MarketDataFetcher:

    def __init__(self):
        self.yahoo_data = {}
        self.fred_data = {}
        self.fear_greed = None
        self.fear_greed_label = ""
        self.valuation = {}
        self._errors = []

    def fetch_all(self, console=None):
        if console:
            console.print("[bold cyan]正在获取市场数据...[/]")
        self._fetch_yahoo(console)
        self._fetch_fred(console)
        self._fetch_fear_greed(console)
        self._fetch_valuation(console)
        if console and self._errors:
            for err in self._errors:
                console.print(f"  [yellow]{err}[/]")
        return self

    @property
    def errors(self):
        return list(self._errors)

    # ------------------------------------------------------------------
    # Yahoo Finance
    # ------------------------------------------------------------------

    def _download_one(self, symbol):
        """Return (df, error). Never raises — the caller records the reason."""
        try:
            end = datetime.now()
            start = end - timedelta(days=LOOKBACK_CALENDAR_DAYS)
            tk = yf.Ticker(symbol)
            df = tk.history(start=start, end=end, auto_adjust=True)
            if df is None or df.empty:
                return pd.DataFrame(), "返回空数据"
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            return df, None
        except Exception as e:
            # Keep the reason: a silent `pass` here makes Yahoo outages
            # indistinguishable from a genuinely quiet market.
            return pd.DataFrame(), f"{type(e).__name__}: {e}"

    def _fetch_yahoo(self, console=None):
        all_items = list(YAHOO_TICKERS.items())
        all_items += [(s, s) for s in LEADING_STOCKS]

        # Add position-target tickers (e.g. QQQM) that aren't already covered.
        known_symbols = {sym for _, sym in all_items}
        for cfg in POSITION_TARGETS.values():
            ticker = cfg["ticker"]
            if ticker not in known_symbols:
                all_items.append((ticker, ticker))
                known_symbols.add(ticker)

        if console:
            console.print(f"  [dim]Yahoo Finance: {len(all_items)} 个标的...[/]")

        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = {pool.submit(self._download_one, sym): (name, sym)
                       for name, sym in all_items}
            for future in as_completed(futures):
                name, sym = futures[future]
                try:
                    df, err = future.result()
                except Exception as e:
                    self._errors.append(f"Yahoo: {name} ({sym}) 失败 ({e})")
                    continue
                if not df.empty:
                    self.yahoo_data[name] = df
                else:
                    self._errors.append(f"Yahoo: {name} ({sym}) 无数据 — {err}")

    # ------------------------------------------------------------------
    # FRED
    # ------------------------------------------------------------------

    def _fetch_one_fred(self, series_id, start_str, end_str):
        """Return (df, error). Values are left in FRED's native unit here;
        scaling happens in _fetch_fred so the mapping stays in one place."""
        try:
            resp = requests.get(
                "https://api.stlouisfed.org/fred/series/observations",
                params={
                    "series_id": series_id,
                    "api_key": FRED_API_KEY,
                    "file_type": "json",
                    "observation_start": start_str,
                    "observation_end": end_str,
                    "sort_order": "asc",
                },
                timeout=15,
            )
            data = resp.json()
            if "observations" not in data:
                detail = data.get("error_message", f"HTTP {resp.status_code}")
                return None, str(detail)
            rows = [{"date": o["date"], "value": float(o["value"])}
                    for o in data["observations"] if o["value"] != "."]
            if not rows:
                return None, "无有效观测值"
            df = pd.DataFrame(rows)
            df["date"] = pd.to_datetime(df["date"])
            return df.set_index("date").sort_index(), None
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"

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

        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = {
                pool.submit(self._fetch_one_fred, series_id, start_str, end_str): name
                for name, series_id in FRED_SERIES.items()
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    df, err = future.result()
                except Exception as e:
                    self._errors.append(f"FRED: {name} 失败 ({e})")
                    continue
                if df is None:
                    self._errors.append(f"FRED: {name} 失败 ({err})")
                    continue
                scale = FRED_SCALE.get(name)
                if scale is not None:
                    df["value"] = df["value"] * scale
                self.fred_data[name] = df

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
            else:
                self._errors.append(f"CNN Fear & Greed: 响应缺少 fear_and_greed 字段 (HTTP {resp.status_code})")
        except Exception as e:
            self.fear_greed = None
            self.fear_greed_label = ""
            self._errors.append(f"CNN Fear & Greed 获取失败 ({type(e).__name__}: {e})")

    # ------------------------------------------------------------------
    # Valuation (index P/E)
    #
    # The whole system had no valuation input at all. yfinance exposes a
    # trailing P/E on the index ETFs; forwardPE is usually absent, so the
    # earnings yield is derived from the trailing figure and labelled as such.
    # ------------------------------------------------------------------

    def _fetch_valuation(self, console=None):
        if console:
            console.print("  [dim]估值 (指数 P/E)...[/]")
        for name in ("SPY", "QQQ"):
            try:
                info = yf.Ticker(name).info or {}
                pe = info.get("trailingPE")
                if pe and pe > 0:
                    self.valuation[name] = {
                        "pe": float(pe),
                        "earnings_yield": 100.0 / float(pe),
                    }
                else:
                    self._errors.append(f"估值: {name} 无 trailingPE")
            except Exception as e:
                self._errors.append(f"估值: {name} 失败 ({type(e).__name__}: {e})")

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

import pandas as pd
import rebalance
from config import (MA50, MA200, MA250, RSI_PERIOD, LEADING_STOCKS,
                    POSITION_TARGETS, SIGNAL_LEVELS, TRADING_DAYS_YEAR,
                    CRITICAL_SERIES, CRITICAL_DERIVED, MACRO_SERIES,
                    SIGNALS, signal_meta, threshold, RISK_BANDS,
                    PMI_PROXY_SERIES, PMI_LEVELS, CYCLE_LEVELS, CYCLE_GATES,
                    MA_WEEKS_FAST, MA_WEEKS_SLOW, VALUATION_LEVELS,
                    CORR_WINDOW, CORR_LEVELS, SKEW_LOOKBACK,
                    SKEW_PCTILE_HIGH, SKEW_PCTILE_EXTREME)


# ======================================================================
# None-safe comparisons
#
# Indicator values are None whenever a feed is missing. Substituting a
# numeric default (the old `g.get("SPY_MA200") or 0`) silently turned a
# missing moving average into "price is above its MA", i.e. missing data
# read as bullish. These helpers make a missing input fail the test instead.
# ======================================================================

def gt(a, b):
    return a is not None and b is not None and a > b


def lt(a, b):
    return a is not None and b is not None and a < b


def gte(a, b):
    return a is not None and b is not None and a >= b


# ======================================================================
# Technical helpers
# ======================================================================

def calc_sma(series, window):
    if series is None or len(series) < window:
        return None
    return series.rolling(window=window).mean()


def calc_rsi(series, period=RSI_PERIOD):
    if series is None or len(series) < period + 1:
        return None
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_macd(series, fast=12, slow=26, signal=9):
    if series is None or len(series) < slow + signal:
        return None, None, None
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def days_below(series, reference, lookback=10):
    """Consecutive most-recent sessions with series < reference.

    The strategy document asks for persistence in several places —
    「QQQ跌破MA200且**无法快速收回**」,「PMI**连续**跌破50」— but every check
    was evaluated on the latest bar alone, so a single-day dip flipped the
    verdict. Returns 0 if the latest bar is not below.
    """
    if series is None or reference is None or len(series) == 0:
        return 0
    if not isinstance(reference, pd.Series):
        reference = pd.Series(reference, index=series.index)
    aligned = pd.DataFrame({"s": series, "r": reference}).dropna()
    if aligned.empty:
        return 0
    below = (aligned["s"] < aligned["r"]).iloc[-lookback:]
    n = 0
    for v in reversed(below.tolist()):
        if v:
            n += 1
        else:
            break
    return n


def weekly_ma_cross(series, fast_weeks, slow_weeks):
    """Detect a cross of the fast weekly MA through the slow one.

    spec 阶段5 asks for 「大盘周线死叉（21周线跌破50周线）」. The old code used
    the *daily* MA50/MA200 cross, which fires on a completely different
    timescale. Returns "death" / "golden" / None plus the two MA values.
    """
    if series is None or len(series) == 0:
        return None, None, None
    wk = series.resample("W").last().dropna()
    if len(wk) < slow_weeks + 2:
        return None, None, None
    fast = wk.rolling(fast_weeks).mean()
    slow = wk.rolling(slow_weeks).mean()
    if pd.isna(fast.iloc[-1]) or pd.isna(slow.iloc[-1]):
        return None, None, None
    if pd.isna(fast.iloc[-2]) or pd.isna(slow.iloc[-2]):
        return None, float(fast.iloc[-1]), float(slow.iloc[-1])
    prev = float(fast.iloc[-2] - slow.iloc[-2])
    curr = float(fast.iloc[-1] - slow.iloc[-1])
    cross = None
    if prev >= 0 and curr < 0:
        cross = "death"
    elif prev <= 0 and curr > 0:
        cross = "golden"
    return cross, float(fast.iloc[-1]), float(slow.iloc[-1])


def latest(series):
    if series is not None and len(series) > 0:
        v = series.iloc[-1]
        if pd.notna(v):
            return float(v)
    return None


def pct_above(price, ma):
    if price is not None and ma is not None and ma != 0:
        return (price - ma) / ma * 100
    return None


def check_rsi_divergence(price_series, rsi_series, lookback=20, recent=5):
    """Return 'bearish' / 'bullish' / None.

    A divergence means price made a new extreme while RSI failed to confirm it.
    RSI is therefore sampled *at the prior price extreme* rather than taken as
    the window's own max/min — comparing against the window's peak RSI would
    flag almost any new high, since RSI oscillates below its peak most days.
    """
    if price_series is None or rsi_series is None:
        return None
    if len(price_series) < lookback or len(rsi_series) < lookback:
        return None

    p = price_series.iloc[-lookback:]
    r = rsi_series.iloc[-lookback:].reindex(p.index)
    prior_p = p.iloc[:-recent]
    prior_r = r.iloc[:-recent]
    if len(prior_p) == 0 or prior_r.isna().all():
        return None

    price_now = float(p.iloc[-1])
    rsi_now = r.iloc[-1]
    if pd.isna(rsi_now):
        return None
    rsi_now = float(rsi_now)

    high_at = prior_p.idxmax()
    low_at = prior_p.idxmin()
    rsi_at_prev_high = prior_r.get(high_at)
    rsi_at_prev_low = prior_r.get(low_at)

    if (price_now >= float(prior_p.max()) and rsi_at_prev_high is not None
            and pd.notna(rsi_at_prev_high) and rsi_now < float(rsi_at_prev_high) - 2):
        return "bearish"
    if (price_now <= float(prior_p.min()) and rsi_at_prev_low is not None
            and pd.notna(rsi_at_prev_low) and rsi_now > float(rsi_at_prev_low) + 2):
        return "bullish"
    return None


# ======================================================================
# MarketAnalyzer
# ======================================================================

class MarketAnalyzer:

    def __init__(self, fetcher):
        self.f = fetcher
        self.signals = []
        self.risk_score = 0
        self.indicators = {}
        self.leader_health = []
        self.combos = []
        self.data_health = {}
        self._signal_groups = {}

    def analyze(self):
        self._gather_indicators()
        self._gather_cycle_indicators()
        self._check_data_health()
        self._analyze_liquidity()
        self._analyze_sentiment()
        self._analyze_leading()
        self._analyze_macro()
        self._analyze_technical()
        self._analyze_leaders()
        self._check_dangerous_combos()

        risk_level = self._risk_level()
        phase = self._detect_phase()
        rec, rec_detail = self._recommendation()

        cycle_result = self._detect_economic_cycle()
        position_signals = self._analyze_position_targets()
        # Inert unless the user supplies a portfolio file — see rebalance.py.
        rebalance_result = rebalance.analyse(cycle_result["allocation"])

        return {
            "indicators": self.indicators,
            "signals": self.signals,
            "risk_score": self.risk_score,
            "risk_level": risk_level,
            "danger_count": self.danger_count,
            "market_phase": phase,
            "recommendation": rec,
            "recommendation_detail": rec_detail,
            "leader_health": self.leader_health,
            "combos": self.combos,
            "economic_cycle": cycle_result,
            "position_signals": position_signals,
            "data_health": self.data_health,
            "rebalance": rebalance_result,
        }

    # ------------------------------------------------------------------
    # Data-quality gate
    #
    # A run with no data produces no signals, which the net risk score reads
    # as 0 -> "low risk / hold". That is the most dangerous possible failure
    # mode: a broken pipeline rendering as reassurance. Detect it explicitly
    # and let the verdict say "insufficient data" instead.
    # ------------------------------------------------------------------

    def _check_data_health(self):
        g = self.indicators
        missing = [name for name in CRITICAL_SERIES if g.get(name) is None]
        missing += [name for name in CRITICAL_DERIVED if g.get(name) is None]
        macro_missing = [name for name in MACRO_SERIES if g.get(name) is None]

        self.data_health = {
            "ok": not missing,
            "missing_critical": missing,
            "missing_macro": macro_missing,
            "fetch_errors": list(getattr(self.f, "errors", [])),
        }

    @property
    def usable(self):
        return self.data_health.get("ok", True)

    @property
    def danger_count(self):
        """Number of active danger-level signals.

        The net risk score can be pushed back to zero by bullish confirmations
        (up to -65 points of them), so a count that cannot be offset is kept
        alongside it.
        """
        return sum(1 for s in self.signals if s["level"] == "danger")

    # ------------------------------------------------------------------
    # Gather all current indicator values
    # ------------------------------------------------------------------

    def _gather_indicators(self):
        g = self.indicators

        g["US10Y"] = self.f.get_latest("US10Y")
        g["US2Y"] = self.f.get_fred_latest("US2Y")
        g["TIPS"] = self.f.get_fred_latest("TIPS")
        g["T10Y2Y"] = self.f.get_fred_latest("T10Y2Y")
        g["DXY"] = self.f.get_latest("DXY")
        g["HY_OAS"] = self.f.get_fred_latest("HY_OAS")

        m2_series = self.f.get_fred_series("M2")
        if m2_series is not None and len(m2_series) >= 13:
            m2_now = m2_series.iloc[-1]
            m2_year_ago = m2_series.iloc[-13]
            g["M2_YOY"] = (m2_now - m2_year_ago) / m2_year_ago * 100
        else:
            g["M2_YOY"] = None

        g["VIX"] = self.f.get_latest("VIX")
        g["VXN"] = self.f.get_latest("VXN")
        g["VIX3M"] = self.f.get_latest("VIX3M")
        g["SKEW"] = self.f.get_latest("SKEW")
        # Percentile within its own trailing distribution — see SKEW_LOOKBACK.
        skew_s = self.f.get_series("SKEW")
        g["SKEW_PCTILE"] = None
        if skew_s is not None and len(skew_s) >= 60:
            window = skew_s.iloc[-SKEW_LOOKBACK:]
            g["SKEW_PCTILE"] = float((window <= float(skew_s.iloc[-1])).mean())
        g["FEAR_GREED"] = self.f.fear_greed
        g["FEAR_GREED_LABEL"] = getattr(self.f, "fear_greed_label", "")

        vix = g.get("VIX")
        vix3m = g.get("VIX3M")
        if vix is not None and vix3m is not None and vix3m != 0:
            g["VIX_TERM"] = vix / vix3m
        else:
            g["VIX_TERM"] = None

        g["SOX"] = self.f.get_latest("SOX")
        g["SPY"] = self.f.get_latest("SPY")
        g["QQQ"] = self.f.get_latest("QQQ")
        g["RSP"] = self.f.get_latest("RSP")

        market_summary = []
        for name, label in [("SPX", "标普500"), ("NDX", "纳指100"), ("DJI", "道琼斯"),
                            ("SOX", "半导体"), ("DXY", "美元"), ("US10Y", "10Y美债"),
                            ("GOLD", "黄金"), ("VIX", "VIX")]:
            s = self.f.get_series(name)
            if s is not None and len(s) >= 2:
                price = float(s.iloc[-1])
                prev = float(s.iloc[-2])
                chg = price - prev
                chg_pct = (chg / prev) * 100
                is_yield = name == "US10Y"
                market_summary.append({
                    "name": name, "label": label, "price": price,
                    "change": chg, "change_pct": chg_pct, "is_yield": is_yield,
                })
        g["MARKET_SUMMARY"] = market_summary
        g["SAHM"] = self.f.get_fred_latest("SAHM")
        g["UNRATE"] = self.f.get_fred_latest("UNRATE")

        spy_s = self.f.get_series("SPY")
        qqq_s = self.f.get_series("QQQ")
        g["SPY_MA200"] = latest(calc_sma(spy_s, MA200))
        g["QQQ_MA200"] = latest(calc_sma(qqq_s, MA200))
        g["SPY_MA50"] = latest(calc_sma(spy_s, MA50))
        g["QQQ_MA50"] = latest(calc_sma(qqq_s, MA50))
        # spec 阶段1 checks price against the 200-day *or* 250-day average.
        g["SPY_MA250"] = latest(calc_sma(spy_s, MA250))
        g["QQQ_MA250"] = latest(calc_sma(qqq_s, MA250))

        g["SPY_DAYS_BELOW_MA200"] = days_below(spy_s, calc_sma(spy_s, MA200))
        g["QQQ_DAYS_BELOW_MA200"] = days_below(qqq_s, calc_sma(qqq_s, MA200))

        wk_cross, wk_fast, wk_slow = weekly_ma_cross(spy_s, MA_WEEKS_FAST, MA_WEEKS_SLOW)
        g["SPY_WEEKLY_CROSS"] = wk_cross
        g["SPY_MA21W"] = wk_fast
        g["SPY_MA50W"] = wk_slow

        g["SPY_RSI"] = latest(calc_rsi(spy_s))
        g["QQQ_RSI"] = latest(calc_rsi(qqq_s))

        spy_macd, spy_sig, _ = calc_macd(spy_s)
        g["SPY_MACD_BULL"] = (latest(spy_macd) is not None and latest(spy_sig) is not None
                              and latest(spy_macd) > latest(spy_sig))

        g["SPY_VS_MA200"] = pct_above(g["SPY"], g["SPY_MA200"])
        g["QQQ_VS_MA200"] = pct_above(g["QQQ"], g["QQQ_MA200"])

        xly = self.f.get_latest("XLY")
        xlu = self.f.get_latest("XLU")
        g["XLY_XLU"] = xly / xlu if xly and xlu and xlu != 0 else None

        cu = self.f.get_latest("COPPER")
        au = self.f.get_latest("GOLD")
        g["CU_AU"] = cu / au if cu and au and au != 0 else None

        # RSP/SPY ratio
        rsp = self.f.get_series("RSP")
        spy_cs = self.f.get_series("SPY")
        if rsp is not None and spy_cs is not None:
            ratio = rsp / spy_cs
            ratio = ratio.dropna()
            if len(ratio) >= 20:
                g["RSP_SPY_RATIO"] = float(ratio.iloc[-1])
                g["RSP_SPY_20D_CHG"] = float(ratio.iloc[-1] / ratio.iloc[-20] - 1) * 100
            else:
                g["RSP_SPY_RATIO"] = None
                g["RSP_SPY_20D_CHG"] = None
        else:
            g["RSP_SPY_RATIO"] = None
            g["RSP_SPY_20D_CHG"] = None

    # ------------------------------------------------------------------
    # Gather cycle-specific indicators (reuse existing + new FRED data)
    # ------------------------------------------------------------------

    def _gather_cycle_indicators(self):
        g = self.indicators

        # Initial Jobless Claims
        icsa_s = self.f.get_fred_series("ICSA")
        if icsa_s is not None and len(icsa_s) >= 2:
            g["ICSA"] = float(icsa_s.iloc[-1])
            recent = icsa_s.iloc[-4:] if len(icsa_s) >= 4 else icsa_s
            g["ICSA_4W_AVG"] = float(recent.mean())
            if len(icsa_s) >= 13:
                g["ICSA_TREND"] = "rising" if float(icsa_s.iloc[-1]) > float(icsa_s.iloc[-13]) else "falling"
            else:
                g["ICSA_TREND"] = None
        else:
            g["ICSA"] = None
            g["ICSA_4W_AVG"] = None
            g["ICSA_TREND"] = None

        # CPI Year-over-Year
        cpi_s = self.f.get_fred_series("CPI")
        if cpi_s is not None and len(cpi_s) >= 13:
            cpi_now = float(cpi_s.iloc[-1])
            cpi_12m = float(cpi_s.iloc[-13])
            g["CPI_YOY"] = (cpi_now - cpi_12m) / cpi_12m * 100
        else:
            g["CPI_YOY"] = None

        # Nonfarm Payrolls Month-over-Month change
        payems_s = self.f.get_fred_series("PAYEMS")
        if payems_s is not None and len(payems_s) >= 2:
            g["PAYEMS_MOM"] = float(payems_s.iloc[-1] - payems_s.iloc[-2])
            if len(payems_s) >= 4:
                changes = [float(payems_s.iloc[i] - payems_s.iloc[i - 1])
                           for i in range(-3, 0)]
                g["PAYEMS_3M_AVG"] = sum(changes) / len(changes)
            else:
                g["PAYEMS_3M_AVG"] = g["PAYEMS_MOM"]
        else:
            g["PAYEMS_MOM"] = None
            g["PAYEMS_3M_AVG"] = None

        # Unemployment trend (3-month direction)
        unrate_s = self.f.get_fred_series("UNRATE")
        if unrate_s is not None and len(unrate_s) >= 4:
            g["UNRATE_TREND"] = "rising" if float(unrate_s.iloc[-1]) > float(unrate_s.iloc[-4]) else "falling"
        else:
            g["UNRATE_TREND"] = None

        # ----- Rate decomposition: nominal = real + breakeven -----
        # Previously only nominal (US10Y) and real (TIPS) were tracked, and at
        # rho = 0.945 they scored the same factor twice without ever saying
        # *why* rates moved. Breakeven separates an inflation-expectation move
        # from a real-discount-rate move, which matter very differently to
        # equity multiples.
        g["BREAKEVEN"] = self.f.get_fred_latest("BREAKEVEN")
        be_s = self.f.get_fred_series("BREAKEVEN")
        tips_s = self.f.get_fred_series("TIPS")
        g["BREAKEVEN_20D_CHG"] = None
        g["REAL_RATE_20D_CHG"] = None
        g["RATE_DRIVER"] = None
        if be_s is not None and len(be_s) >= 21:
            g["BREAKEVEN_20D_CHG"] = float(be_s.iloc[-1] - be_s.iloc[-21]) * 100
        if tips_s is not None and len(tips_s) >= 21:
            g["REAL_RATE_20D_CHG"] = float(tips_s.iloc[-1] - tips_s.iloc[-21]) * 100
        d_be, d_real = g["BREAKEVEN_20D_CHG"], g["REAL_RATE_20D_CHG"]
        if d_be is not None and d_real is not None:
            if abs(d_real) >= abs(d_be):
                g["RATE_DRIVER"] = "real" if d_real > 0 else "real_easing"
            else:
                g["RATE_DRIVER"] = "inflation" if d_be > 0 else "disinflation"

        # ----- Fed liquidity: balance sheet and reverse repo -----
        # spec 1.2 names ON RRP explicitly; liquidity had only the monthly,
        # lagging M2 to stand on.
        fa_s = self.f.get_fred_series("FED_ASSETS")
        g["FED_ASSETS"] = float(fa_s.iloc[-1]) / 1e6 if fa_s is not None and len(fa_s) else None
        g["FED_ASSETS_13W_CHG"] = None
        if fa_s is not None and len(fa_s) >= 14:
            g["FED_ASSETS_13W_CHG"] = float(fa_s.iloc[-1] - fa_s.iloc[-14]) / 1e6
        g["ON_RRP"] = self.f.get_fred_latest("ON_RRP")

        # GDP year-over-year, derived from the quarterly real GDP level so it
        # matches the spec's "GDP同比" rather than FRED's annualised QoQ print.
        gdp_s = self.f.get_fred_series("GDP")
        if gdp_s is not None and len(gdp_s) >= 5:
            g["GDP_YOY"] = float(gdp_s.iloc[-1] / gdp_s.iloc[-5] - 1) * 100
        else:
            g["GDP_YOY"] = None

        # PMI proxy: mean of the regional Fed manufacturing surveys. These are
        # diffusion indices centred on 0 (0 <-> ISM PMI 50); no scale
        # conversion is applied. Series publish on different lags, so they are
        # aligned monthly and averaged over whatever is available per month.
        frames = {}
        for key in PMI_PROXY_SERIES:
            s = self.f.get_fred_series(key)
            if s is not None and len(s) > 0:
                frames[key] = s.resample("MS").last()
        if frames:
            pmi_df = pd.DataFrame(frames)
            pmi_avg = pmi_df.mean(axis=1, skipna=True).dropna()
            g["PMI_PROXY_SOURCES"] = len(frames)
        else:
            pmi_avg = pd.Series(dtype=float)
            g["PMI_PROXY_SOURCES"] = 0

        if len(pmi_avg) > 0:
            g["PMI_PROXY"] = float(pmi_avg.iloc[-1])
            if len(pmi_avg) >= 4:
                g["PMI_TREND"] = ("rising"
                                  if float(pmi_avg.iloc[-1]) > float(pmi_avg.iloc[-4])
                                  else "falling")
            else:
                g["PMI_TREND"] = None
            # 见底拐头: recently in deep contraction, now turning up
            if len(pmi_avg) >= 6:
                window = pmi_avg.iloc[-6:]
                g["PMI_TROUGH_TURN"] = bool(
                    float(window.min()) < PMI_LEVELS["DEEP"]
                    and float(pmi_avg.iloc[-1]) > float(window.min()) + 5)
            else:
                g["PMI_TROUGH_TURN"] = False
        else:
            g["PMI_PROXY"] = None
            g["PMI_TREND"] = None
            g["PMI_TROUGH_TURN"] = False

        # Fed policy stance. The spec's tools (FedWatch, dot plot, FOMC
        # wording) have no free machine-readable source; this approximates
        # dovishness from realised cuts and from US2Y pricing below target.
        fed_s = self.f.get_fred_series("FED_UPPER")
        g["FED_UPPER"] = float(fed_s.iloc[-1]) if fed_s is not None and len(fed_s) else None
        g["FED_CUT_RECENT"] = False
        if fed_s is not None and len(fed_s) >= 90:
            g["FED_CUT_RECENT"] = bool(float(fed_s.iloc[-1]) < float(fed_s.iloc[-90]))
        us2y = g.get("US2Y")
        g["FED_MARKET_GAP"] = (us2y - g["FED_UPPER"]
                               if us2y is not None and g["FED_UPPER"] is not None else None)

        # ----- Valuation anchor -----
        # The system had no valuation input whatsoever. Earnings yield minus
        # the nominal 10Y ("Fed model" spread) says whether equities are paid
        # for relative to cash-equivalents; minus the real rate says it in
        # real terms. Deliberately not scored — see VALUATION_LEVELS.
        val = getattr(self.f, "valuation", {}) or {}
        for name in ("SPY", "QQQ"):
            entry = val.get(name) or {}
            g[f"{name}_PE"] = entry.get("pe")
            g[f"{name}_EY"] = entry.get("earnings_yield")
        ey = g.get("SPY_EY")
        g["ERP_NOMINAL"] = (ey - g["US10Y"]
                            if ey is not None and g.get("US10Y") is not None else None)
        g["ERP_REAL"] = (ey - g["TIPS"]
                         if ey is not None and g.get("TIPS") is not None else None)

        # ----- Stock/bond correlation -----
        # The cycle allocation table leans on long Treasuries as the equity
        # hedge (up to 30% in a recession). If that correlation has flipped
        # positive, the diversification the table assumes is not there.
        spy_c, tlt_c = self.f.get_series("SPY"), self.f.get_series("TLT")
        g["STOCK_BOND_CORR"] = None
        if spy_c is not None and tlt_c is not None:
            rr = pd.DataFrame({"s": spy_c, "t": tlt_c}).dropna().pct_change().dropna()
            if len(rr) >= CORR_WINDOW:
                w = rr.iloc[-CORR_WINDOW:]
                # A flat series has zero variance, which makes the correlation
                # undefined (and noisy in numpy). Skip rather than emit NaN.
                if w["s"].std() > 0 and w["t"].std() > 0:
                    c = w["s"].corr(w["t"])
                    if pd.notna(c):
                        g["STOCK_BOND_CORR"] = float(c)

        # Copper/Gold 20-day trend
        cu_s = self.f.get_series("COPPER")
        au_s = self.f.get_series("GOLD")
        if cu_s is not None and au_s is not None and len(cu_s) >= 20 and len(au_s) >= 20:
            ratio_now = float(cu_s.iloc[-1] / au_s.iloc[-1])
            ratio_20d = float(cu_s.iloc[-20] / au_s.iloc[-20])
            g["CU_AU_TREND"] = "rising" if ratio_now > ratio_20d else "falling"
        else:
            g["CU_AU_TREND"] = None

    # ------------------------------------------------------------------
    # Signal helpers
    # ------------------------------------------------------------------

    def _add_signal(self, signal_id, desc=""):
        """Emit a registered signal. Weights and display names come from
        config.SIGNALS so decision logic can match on id instead of on a
        Chinese substring of the name."""
        meta = signal_meta(signal_id)
        group = meta["group"]

        if group:
            # The strategy document scores rows like「VIX > 25 或 VXN > 30」
            # once. Within a group only the strongest reading is kept.
            prev_id = self._signal_groups.get(group)
            if prev_id is not None:
                if abs(meta["score"]) <= abs(SIGNALS[prev_id]["score"]):
                    return
                self.signals = [s for s in self.signals if s["id"] != prev_id]
                self.risk_score -= SIGNALS[prev_id]["score"]
            self._signal_groups[group] = signal_id

        self.signals.append({
            "id": signal_id,
            "name": meta["name"],
            "score": meta["score"],
            "level": meta["level"],   # "danger" / "warning" / "safe"
            "source": meta["source"],  # "spec" / "ext"
            "desc": desc,
        })
        self.risk_score += meta["score"]

    def _has(self, *signal_ids):
        """True if any of the given signals is active. Replaces the old
        substring matching, which broke silently when a name changed."""
        active = {s["id"] for s in self.signals}
        return any(sid in active for sid in signal_ids)

    # ------------------------------------------------------------------
    # Liquidity analysis
    # ------------------------------------------------------------------

    def _analyze_liquidity(self):
        g = self.indicators

        # US10Y consecutive rise
        us10y_s = self.f.get_series("US10Y")
        if us10y_s is not None and len(us10y_s) >= 6:
            last5 = us10y_s.iloc[-5:]
            diffs = last5.diff().dropna()
            if len(diffs) >= 4 and (diffs > 0).all():
                self._add_signal("US10Y_STREAK_UP", f"当前 {g['US10Y']:.2f}%")
            elif len(diffs) >= 4 and (diffs < 0).all():
                self._add_signal("US10Y_FALLING", f"当前 {g['US10Y']:.2f}%")

        us10y_high = threshold("US10Y")
        if gt(g.get("US10Y"), us10y_high):
            self._add_signal("US10Y_HIGH", f"{g['US10Y']:.2f}% > {us10y_high:.1f}%")

        # TIPS
        tips = g.get("TIPS")
        if tips is not None:
            tips_s = self.f.get_fred_series("TIPS")
            if tips_s is not None and len(tips_s) >= 5:
                tips_chg = float(tips_s.iloc[-1] - tips_s.iloc[-5])
                if tips > threshold("TIPS") and tips_chg > 0:
                    self._add_signal("TIPS_RISING", f"{tips:.2f}% 且近期上升")
                elif tips_chg < SIGNAL_LEVELS["TIPS_FALL_DELTA"]:
                    self._add_signal("TIPS_FALLING", f"{tips:.2f}%")

        # DXY
        dxy = g.get("DXY")
        if dxy is not None:
            dxy_break = threshold("DXY")
            if dxy > dxy_break:
                self._add_signal("DXY_BREAKOUT", f"当前 {dxy:.1f} > {dxy_break:.0f}")
            dxy_s = self.f.get_series("DXY")
            if dxy_s is not None and len(dxy_s) >= 6:
                week_chg = (dxy_s.iloc[-1] / dxy_s.iloc[-5] - 1) * 100
                if week_chg > SIGNAL_LEVELS["DXY_WEEK_SURGE_PCT"]:
                    self._add_signal("DXY_WEEK_SURGE", f"周涨幅 {week_chg:.1f}%")

        # HY OAS (basis points — see FRED_SCALE)
        hy = g.get("HY_OAS")
        if hy is not None:
            if hy > threshold("HY_OAS"):
                self._add_signal("HY_OAS_HIGH", f"{hy:.0f}bp > {threshold('HY_OAS'):.0f}bp")
            hy_s = self.f.get_fred_series("HY_OAS")
            if hy_s is not None and len(hy_s) >= 6:
                week_chg = float(hy_s.iloc[-1] - hy_s.iloc[-5])
                if week_chg > SIGNAL_LEVELS["HY_OAS_WEEK_WIDEN_BP"]:
                    self._add_signal("HY_OAS_WIDENING", f"周变化 +{week_chg:.0f}bp")

        # M2
        m2_yoy = g.get("M2_YOY")
        if m2_yoy is not None:
            if m2_yoy > 0:
                m2_s = self.f.get_fred_series("M2")
                if m2_s is not None and len(m2_s) >= 3:
                    recent_trend = float(m2_s.iloc[-1] - m2_s.iloc[-3])
                    if recent_trend > 0:
                        self._add_signal("M2_REBOUND", f"同比 {m2_yoy:.1f}%")
            elif m2_yoy < SIGNAL_LEVELS["M2_CONTRACT_YOY"]:
                self._add_signal("M2_CONTRACTING", f"同比 {m2_yoy:.1f}%")

    # ------------------------------------------------------------------
    # Sentiment analysis
    # ------------------------------------------------------------------

    def _analyze_sentiment(self):
        g = self.indicators

        vix = g.get("VIX")
        vxn = g.get("VXN")

        if gt(vix, threshold("VIX")):
            self._add_signal("VIX_RISK", f"VIX={vix:.1f}")
        if gt(vxn, threshold("VXN")):
            self._add_signal("VXN_RISK", f"VXN={vxn:.1f}")

        # VIX term structure
        vt = g.get("VIX_TERM")
        if gt(vt, threshold("VIX_TERM")):
            self._add_signal("VIX_TERM_INVERTED", f"VIX/VIX3M={vt:.2f}，近月恐慌高于远月")

        # SKEW — graded against its own trailing distribution. A fixed 140
        # fired on 55.7% of recent sessions and carried no information.
        skew = g.get("SKEW")
        pct = g.get("SKEW_PCTILE")
        if skew is not None and pct is not None:
            if pct >= SKEW_PCTILE_EXTREME:
                self._add_signal("SKEW_EXTREME",
                                 f"SKEW={skew:.0f}，处于近2年 {pct*100:.0f}% 分位")
            elif pct >= SKEW_PCTILE_HIGH and lt(vix, SIGNAL_LEVELS["VIX_CALM_FOR_SKEW"]):
                self._add_signal("SKEW_HIGH_VIX_LOW",
                                 f"SKEW={skew:.0f}（近2年 {pct*100:.0f}% 分位）, VIX={vix:.1f}")

        # Fear & Greed
        fg = g.get("FEAR_GREED")
        if fg is not None:
            fear_lvl = SIGNAL_LEVELS["FG_EXTREME_FEAR"]
            greed_lvl = SIGNAL_LEVELS["FG_GREED"]
            if fg < fear_lvl:
                self._add_signal("EXTREME_FEAR", f"得分={fg:.0f} < {fear_lvl:.0f}，可能是黄金坑")
            elif fg > greed_lvl:
                self._add_signal("EXTREME_GREED", f"得分={fg:.0f} > {greed_lvl:.0f}，注意过热")

    # ------------------------------------------------------------------
    # Leading indicators
    # ------------------------------------------------------------------

    def _analyze_leading(self):
        g = self.indicators

        # SOX vs MA50
        sox_s = self.f.get_series("SOX")
        if sox_s is None:
            sox_s = self.f.get_series("SOXX")

        if sox_s is not None and len(sox_s) >= MA50:
            sox_ma50 = float(sox_s.rolling(MA50).mean().iloc[-1])
            sox_now = float(sox_s.iloc[-1])
            if sox_now < sox_ma50:
                self._add_signal("SOX_BELOW_MA50", f"SOX={sox_now:.0f}, MA50={sox_ma50:.0f}")
            else:
                self._add_signal("SOX_ABOVE_MA50", f"SOX={sox_now:.0f}, MA50={sox_ma50:.0f}")

        # SOX vs QQQ relative strength (20-day return)
        qqq_s = self.f.get_series("QQQ")
        if sox_s is not None and qqq_s is not None:
            if len(sox_s) >= 20 and len(qqq_s) >= 20:
                sox_ret = (sox_s.iloc[-1] / sox_s.iloc[-20] - 1) * 100
                qqq_ret = (qqq_s.iloc[-1] / qqq_s.iloc[-20] - 1) * 100
                diff = sox_ret - qqq_ret
                g["SOX_20D"] = float(sox_ret)
                g["QQQ_20D"] = float(qqq_ret)
                if diff < SIGNAL_LEVELS["SOX_QQQ_DIVERGE_PCT"]:
                    self._add_signal("SOX_WEAKER_QQQ", f"SOX 20日={sox_ret:.1f}%, QQQ={qqq_ret:.1f}%")

        # RSP/SPY breadth
        rsp_chg = g.get("RSP_SPY_20D_CHG")
        if rsp_chg is not None:
            spy_s = self.f.get_series("SPY")
            if spy_s is not None and len(spy_s) >= 20:
                spy_ret = (spy_s.iloc[-1] / spy_s.iloc[-20] - 1) * 100
                if (spy_ret > SIGNAL_LEVELS["BREADTH_SPY_RET_PCT"]
                        and rsp_chg < SIGNAL_LEVELS["BREADTH_RSP_CHG_PCT"]):
                    self._add_signal("BREADTH_BAD", f"SPY涨{spy_ret:.1f}%但RSP/SPY 20日={rsp_chg:.1f}%")
                elif rsp_chg > 0:
                    self._add_signal("BREADTH_GOOD", f"RSP/SPY比值 20日变化={rsp_chg:.1f}%")

        # XLY/XLU sector rotation
        xly_xlu = g.get("XLY_XLU")
        if xly_xlu is not None:
            xly_s = self.f.get_series("XLY")
            xlu_s = self.f.get_series("XLU")
            if xly_s is not None and xlu_s is not None and len(xly_s) >= 20 and len(xlu_s) >= 20:
                ratio_now = xly_s.iloc[-1] / xlu_s.iloc[-1]
                ratio_20d = xly_s.iloc[-20] / xlu_s.iloc[-20]
                if ratio_now < ratio_20d * SIGNAL_LEVELS["XLY_XLU_DEFENSIVE_RATIO"]:
                    self._add_signal("SECTOR_DEFENSIVE", "XLY/XLU比值下降")

    # ------------------------------------------------------------------
    # Macro analysis
    # ------------------------------------------------------------------

    def _analyze_macro(self):
        g = self.indicators

        # Sahm Rule
        sahm = g.get("SAHM")
        sahm_trigger = threshold("SAHM")
        if gte(sahm, sahm_trigger):
            self._add_signal("SAHM_TRIGGERED", f"当前值={sahm:.2f} >= {sahm_trigger:.1f}，衰退信号")

        # Manufacturing PMI proxy (spec 4.1 / scoring table +10 / -15)
        pmi = g.get("PMI_PROXY")
        if pmi is not None:
            if pmi < PMI_LEVELS["CONTRACTION"] and g.get("PMI_TREND") == "falling":
                self._add_signal("PMI_CONTRACTING",
                                 f"制造业扩散指数={pmi:.1f} (<0 荣枯线) 且趋势下行")
            elif g.get("PMI_TROUGH_UP") or g.get("PMI_TROUGH_TURN"):
                self._add_signal("PMI_TROUGH_UP",
                                 f"制造业扩散指数={pmi:.1f}，自深度收缩区回升")

        # Fed stance (spec 1.2 — approximated, see _gather_cycle_indicators)
        gap = g.get("FED_MARKET_GAP")
        if g.get("FED_CUT_RECENT"):
            self._add_signal("FED_DOVISH",
                             f"联邦基金上限已下调至 {g['FED_UPPER']:.2f}%")
        elif lt(gap, SIGNAL_LEVELS["FED_DOVISH_GAP"]):
            self._add_signal("FED_DOVISH",
                             f"US2Y {g['US2Y']:.2f}% 低于政策利率 {g['FED_UPPER']:.2f}% "
                             f"{abs(gap)*100:.0f}bp，市场抢跑降息")

        # Yield curve de-inversion
        t10y2y = g.get("T10Y2Y")
        if t10y2y is not None:
            t_s = self.f.get_fred_series("T10Y2Y")
            if t_s is not None and len(t_s) >= 20:
                was_inverted = (t_s.iloc[-20:-5] < 0).any()
                now_positive = t10y2y > 0
                if was_inverted and now_positive and t10y2y > 0.1:
                    self._add_signal("CURVE_UNINVERT", f"10Y-2Y利差={t10y2y:.2f}%，快速转正")

    # ------------------------------------------------------------------
    # Technical analysis
    # ------------------------------------------------------------------

    def _analyze_technical(self):
        g = self.indicators

        spy = g.get("SPY")
        spy_ma200 = g.get("SPY_MA200")
        if spy is not None and spy_ma200 is not None:
            if spy < spy_ma200:
                held = g.get("SPY_DAYS_BELOW_MA200") or 0
                self._add_signal("SPY_BELOW_MA200",
                                 f"SPY={spy:.1f}, MA200={spy_ma200:.1f}，已持续{held}日")

        qqq = g.get("QQQ")
        qqq_ma200 = g.get("QQQ_MA200")
        if qqq is not None and qqq_ma200 is not None:
            if qqq < qqq_ma200:
                held = g.get("QQQ_DAYS_BELOW_MA200") or 0
                self._add_signal("QQQ_BELOW_MA200",
                                 f"QQQ={qqq:.1f}, MA200={qqq_ma200:.1f}，已持续{held}日")

        # MA golden cross / death cross
        spy_ma50 = g.get("SPY_MA50")
        if spy_ma50 is not None and spy_ma200 is not None:
            spy_s = self.f.get_series("SPY")
            if spy_s is not None and len(spy_s) > MA200:
                ma50_s = calc_sma(spy_s, MA50)
                ma200_s = calc_sma(spy_s, MA200)
                if ma50_s is not None and ma200_s is not None and len(ma50_s) >= 2:
                    prev = ma50_s.iloc[-2] - ma200_s.iloc[-2]
                    curr = ma50_s.iloc[-1] - ma200_s.iloc[-1]
                    if prev < 0 and curr > 0:
                        self._add_signal("SPY_GOLDEN_CROSS", "牛市确认信号")
                    elif prev > 0 and curr < 0:
                        self._add_signal("SPY_DEATH_CROSS", "熊市确认信号")

        # RSI divergence
        qqq_s = self.f.get_series("QQQ")
        if qqq_s is not None:
            rsi_s = calc_rsi(qqq_s)
            div = check_rsi_divergence(qqq_s, rsi_s)
            if div == "bearish":
                self._add_signal("RSI_BEAR_DIV", "上涨动能可能衰竭")
            elif div == "bullish":
                self._add_signal("RSI_BULL_DIV", "下跌动能可能衰竭")

    # ------------------------------------------------------------------
    # Leading stock health
    # ------------------------------------------------------------------

    def _analyze_leaders(self):
        weak_count = 0
        heavy_selling = []
        for stock in LEADING_STOCKS:
            s = self.f.get_series(stock)
            if s is None or len(s) < MA50:
                self.leader_health.append({
                    "name": stock, "price": None, "vs_ma50": None,
                    "vs_ma200": None, "ret_20d": None,
                    "vol_ratio": None, "heavy_down": False, "status": "N/A"
                })
                continue

            price = float(s.iloc[-1])
            ma50 = float(s.rolling(MA50).mean().iloc[-1])
            ma200_val = float(s.rolling(MA200).mean().iloc[-1]) if len(s) >= MA200 else None
            ret20 = (s.iloc[-1] / s.iloc[-20] - 1) * 100 if len(s) >= 20 else None

            vs50 = (price - ma50) / ma50 * 100
            vs200 = (price - ma200_val) / ma200_val * 100 if ma200_val else None

            # spec 3.4 asks for 滞涨或**放量下跌**. Volume was fetched but never
            # used before, so the "放量" half of that rule was unimplemented.
            vol_ratio = None
            heavy_down = False
            vol = self.f.get_series(stock, "Volume")
            if vol is not None and len(vol) >= MA50:
                avg_vol = float(vol.iloc[-MA50:].mean())
                if avg_vol > 0:
                    vol_ratio = float(vol.iloc[-1]) / avg_vol
                    down_today = len(s) >= 2 and price < float(s.iloc[-2])
                    heavy_down = bool(
                        down_today and vol_ratio >= SIGNAL_LEVELS["LEADER_VOLUME_SPIKE"])
            if heavy_down:
                heavy_selling.append(stock)

            if price < ma50:
                status = "danger"
                weak_count += 1
            elif vs50 < 2 or heavy_down:
                status = "warning"
            else:
                status = "safe"

            self.leader_health.append({
                "name": stock, "price": price,
                "vs_ma50": vs50, "vs_ma200": vs200,
                "ret_20d": float(ret20) if ret20 is not None else None,
                "vol_ratio": vol_ratio, "heavy_down": heavy_down,
                "status": status,
            })

        if weak_count >= SIGNAL_LEVELS["WEAK_LEADERS_COUNT"]:
            desc = f"{weak_count}/{len(LEADING_STOCKS)} 跌破MA50，指数可能补跌"
            if heavy_selling:
                desc += f"；放量下跌: {', '.join(heavy_selling)}"
            self._add_signal("LEADERS_WEAK", desc)

    # ------------------------------------------------------------------
    # Dangerous combos
    # ------------------------------------------------------------------

    def _check_dangerous_combos(self):
        g = self.indicators

        # Combo 1: DXY + VIX both rising
        dxy_s = self.f.get_series("DXY")
        vix_s = self.f.get_series("VIX")
        c1_triggered = False
        if dxy_s is not None and vix_s is not None and len(dxy_s) >= 5 and len(vix_s) >= 5:
            dxy_up = dxy_s.iloc[-1] > dxy_s.iloc[-5]
            vix_up = vix_s.iloc[-1] > vix_s.iloc[-5]
            dxy_chg = (dxy_s.iloc[-1] / dxy_s.iloc[-5] - 1) * 100
            vix_chg = vix_s.iloc[-1] - vix_s.iloc[-5]
            # bool() matters: pandas comparisons yield numpy.bool, which fails
            # the renderers' `is True` / `is False` identity checks and made
            # this combo always display as "needs manual observation".
            c1_triggered = bool(dxy_up and vix_up and (dxy_chg > 0.5 or vix_chg > 3))
            if c1_triggered:
                self._add_signal("COMBO_DXY_VIX", f"DXY周涨{dxy_chg:.1f}%, VIX周升{vix_chg:.1f}")
        self.combos.append({
            "name": "DXY+VIX同涨",
            "triggered": c1_triggered,
            "detail": "全球流动性收紧+恐慌" if c1_triggered else ""
        })

        # Combo 2: SOX weak + breadth bad + RSI divergence
        sox_weak = self._has("SOX_BELOW_MA50")
        breadth_bad = self._has("BREADTH_BAD")
        rsi_div = self._has("RSI_BEAR_DIV")
        c2_count = sum([sox_weak, breadth_bad, rsi_div])
        c2_triggered = c2_count >= 2
        self.combos.append({
            "name": "SOX弱+广度差+RSI背离",
            "triggered": c2_triggered,
            "detail": f"{c2_count}/3 触发"
        })

        # Combo 3: Yield curve de-inversion + Sahm Rule
        curve_signal = self._has("CURVE_UNINVERT")
        sahm_signal = self._has("SAHM_TRIGGERED")
        c3_triggered = curve_signal and sahm_signal
        self.combos.append({
            "name": "曲线解倒挂+萨姆规则",
            "triggered": c3_triggered,
            "detail": "最高级别衰退信号" if c3_triggered else ""
        })

        # Combo 4: TIPS surging + VIX calm
        tips = g.get("TIPS")
        vix = g.get("VIX")
        c4_triggered = False
        if tips is not None and vix is not None:
            tips_s = self.f.get_fred_series("TIPS")
            if tips_s is not None and len(tips_s) >= 5:
                tips_rising = float(tips_s.iloc[-1]) > float(tips_s.iloc[-5])
                c4_triggered = (tips_rising
                                and tips > SIGNAL_LEVELS["TIPS_QUIET_KILL"]
                                and vix < SIGNAL_LEVELS["VIX_CALM_FOR_TIPS"])
        self.combos.append({
            "name": "TIPS飙升+VIX平稳",
            "triggered": c4_triggered,
            "detail": "静默杀估值" if c4_triggered else ""
        })

        # Combo 5: VIX low + SKEW high
        # Uses the same trailing-percentile basis as the scored SKEW signal.
        # On the old fixed 140 this combo triggered on 55.7% of recent
        # sessions, which is not a "combo" so much as a constant.
        skew = g.get("SKEW")
        skew_pct = g.get("SKEW_PCTILE")
        c5_triggered = bool(gte(skew_pct, SKEW_PCTILE_HIGH)
                            and lt(vix, SIGNAL_LEVELS["VIX_QUIET_STORM"]))
        self.combos.append({
            "name": "VIX低+SKEW高",
            "triggered": c5_triggered,
            "detail": (f"暴风雨前的宁静 (SKEW {skew:.0f} 处 {skew_pct*100:.0f}% 分位, VIX {vix:.1f})"
                       if c5_triggered else "")
        })

        # Combo 6: news reaction (manual)
        self.combos.append({
            "name": "消息反应异变",
            "triggered": None,
            "detail": "需人工观察: 好消息不涨/小利空大跌"
        })

    # ------------------------------------------------------------------
    # Risk level
    # ------------------------------------------------------------------

    def _risk_level(self):
        if not self.usable:
            return "数据不足 (无法评级)"

        # Bands come from config.RISK_BANDS, which holds the document's
        # fractions of its own ceiling (15% / 25% / 35% of max) rather than
        # its literal 30/50/70 — those assumed a +200 scale the
        # implementation no longer has.
        s = self.risk_score
        b1, b2, b3 = RISK_BANDS
        if s <= 0:
            level = "低风险 (Risk-On)"
        elif s <= b1:
            level = "中低风险"
        elif s <= b2:
            level = "中等风险"
        elif s <= b3:
            level = "高风险 (Risk-Off)"
        else:
            level = "极高风险"

        # Bullish confirmations carry up to MAX_RISK_NEGATIVE points, enough
        # to net a genuinely dangerous tape back to "low risk". Surface the
        # raw count of danger signals so it cannot be scored away.
        dangers = self.danger_count
        if dangers >= 3 and s <= b1:
            level += f"（但有{dangers}项危险信号，勿只看总分）"
        return level

    # ------------------------------------------------------------------
    # Market phase detection
    # ------------------------------------------------------------------

    def _detect_phase(self):
        g = self.indicators
        if not self.usable:
            return "数据不足 (无法判断)"

        phases = []

        # Read raw values — no numeric fallbacks. A missing input must fail
        # its test, not be coerced into one that happens to look bullish.
        vix = g.get("VIX")
        dxy = g.get("DXY")
        sahm = g.get("SAHM")
        tips = g.get("TIPS")
        spy = g.get("SPY")
        spy_ma200 = g.get("SPY_MA200")
        above_ma200 = gt(spy, spy_ma200)

        # Risk-Off
        if gt(vix, 30) and gt(dxy, threshold("DXY", "warn")):
            phases.append("风险规避 (Risk-Off)")

        # Recession
        if gte(sahm, threshold("SAHM")) or self._has("SAHM_TRIGGERED"):
            phases.append("衰退交易")
        elif self._has("CURVE_UNINVERT"):
            phases.append("衰退交易")

        # AI/Growth Bull
        sox_strong = self._has("SOX_ABOVE_MA50")
        leaders_ok = sum(1 for lh in self.leader_health if lh["status"] == "safe") >= 4
        if sox_strong and leaders_ok and above_ma200:
            phases.append("AI成长牛市")

        # Liquidity Bull
        us10y_s = self.f.get_series("US10Y")
        us10y_falling = False
        if us10y_s is not None and len(us10y_s) >= 20:
            us10y_falling = float(us10y_s.iloc[-1]) < float(us10y_s.iloc[-20])
        if us10y_falling and lt(tips, threshold("TIPS", "warn")) and above_ma200:
            phases.append("流动性牛市")

        if not phases:
            if above_ma200:
                phases.append("标准牛市")
            elif lt(spy, spy_ma200):
                phases.append("震荡/调整")
            else:
                phases.append("趋势未知 (缺少SPY/MA200)")

        return " / ".join(phases)

    # ------------------------------------------------------------------
    # Recommendation
    # ------------------------------------------------------------------

    def _recommendation(self):
        g = self.indicators
        score = self.risk_score

        if not self.usable:
            missing = "、".join(self.data_health.get("missing_critical", []))
            return ("数据不足",
                    f"关键行情数据缺失（{missing}），本次不给出操作建议。"
                    "请检查数据源后重跑，不要把空信号当成低风险。")

        # No numeric fallbacks: a missing value leaves its condition False
        # rather than quietly satisfying or suppressing it.
        vix = g.get("VIX")
        vxn = g.get("VXN")
        spy = g.get("SPY")
        spy_ma200 = g.get("SPY_MA200")
        qqq = g.get("QQQ")
        qqq_ma200 = g.get("QQQ_MA200")
        rsi = g.get("QQQ_RSI")
        fg = g.get("FEAR_GREED")
        sahm = g.get("SAHM")
        hy = g.get("HY_OAS")

        pmi = g.get("PMI_PROXY")
        b1, b2, _ = RISK_BANDS

        # Distance to the nearest long-term average — spec 阶段1 says
        # 「价格跌至200日/250日均线附近」, so MA250 counts too.
        gaps = [pct_above(spy, g.get("SPY_MA200")), pct_above(spy, g.get("SPY_MA250"))]
        near_long_ma = any(x is not None and abs(x) < 5 for x in gaps)

        # Stage 5: Strong Sell  (spec: 5 条满足 3)
        strong_sell_conds = [
            self._has("CURVE_UNINVERT"),
            gte(sahm, threshold("SAHM")),
            # spec: PMI连续跌破50且趋势持续向下. Restored to a PMI reading now
            # that a proxy exists; it was a permanently-false test before.
            lt(pmi, PMI_LEVELS["CONTRACTION"]) and g.get("PMI_TREND") == "falling",
            # spec: 大盘**周线**死叉（21周线跌破50周线）— not the daily cross
            g.get("SPY_WEEKLY_CROSS") == "death",
            # spec adds 「且无法快速收回」 — require the break to hold rather
            # than counting a single-session dip below the average.
            (g.get("QQQ_DAYS_BELOW_MA200") or 0) >= SIGNAL_LEVELS["MA200_BREAK_DAYS"],
        ]
        if sum(strong_sell_conds) >= 3:
            return ("强烈卖出", "系统性风险极高，建议减仓至20%以下，可配置TLT对冲")

        # Stage 1: Strong Buy  (spec: 5 条满足 3; 美联储鸽派 now approximated)
        strong_buy_conds = [
            gt(vix, 35) or gt(vxn, 40),
            lt(rsi, 30) or lt(fg, SIGNAL_LEVELS["FG_EXTREME_FEAR"]),
            near_long_ma,
            self._has("US10Y_FALLING"),
            self._has("FED_DOVISH"),
        ]
        if sum(strong_buy_conds) >= 3:
            return ("强烈买入", "极端恐慌+超卖，分批重仓买入（3-5批，间隔1-2周）")

        # Stage 2: Gradual Buy  (spec: 5 条满足 3)
        # Was a VIX gate plus *one* of three sub-conditions, so a single
        # confirmation could trigger an add — far looser than the spec.
        vix_s = self.f.get_series("VIX")
        vix_easing = False
        if vix_s is not None and len(vix_s) >= 10:
            vix_easing = float(vix_s.iloc[-1]) < float(vix_s.iloc[-10])
        gradual_buy_conds = [
            vix is not None and 25 <= vix <= 35 and vix_easing,
            g.get("PMI_TROUGH_TURN") or self._has("PMI_TROUGH_UP"),
            self._has("TIPS_FALLING"),
            self._has("SOX_ABOVE_MA50"),
            gt(qqq, g.get("QQQ_MA50")),
        ]
        if sum(gradual_buy_conds) >= 3 and score < b2:
            return ("逐步买入", "宏观见底迹象，建议定投加仓，建立长线底仓")

        # Stage 4: Gradual Sell  (spec: 5 条满足 3)
        vix_dull_low = False
        if vix_s is not None and len(vix_s) >= 60 and vix is not None:
            vix_dull_low = vix <= float(vix_s.iloc[-60:].quantile(0.2))
        gradual_sell_conds = [
            vix_dull_low,
            self._has("RSI_BEAR_DIV"),
            gt(fg, SIGNAL_LEVELS["FG_GREED"]),
            self._has("DXY_BREAKOUT", "DXY_WEEK_SURGE"),
            self._has("SOX_WEAKER_QQQ"),
        ]
        if sum(gradual_sell_conds) >= 3:
            return ("逐步减仓", "技术面超买，分批止盈20-30%，停止新买入")

        # Stage 3: Hold — but a low net score built on top of several danger
        # signals is not the same as a genuinely quiet tape.
        dangers = self.danger_count
        if score <= b1:
            if dangers >= 3:
                return ("谨慎持有",
                        f"总分被利好信号对冲至{score}，但仍有{dangers}项危险信号，"
                        "维持仓位但停止加仓")
            return ("持有观望", "趋势健康，维持现有仓位，享受趋势收益")
        elif score <= b2:
            return ("谨慎持有", "部分风险信号出现，保持警惕，停止加杠杆")
        else:
            return ("考虑减仓", "多项风险信号触发，建议降低仓位至50%以下")

    # ------------------------------------------------------------------
    # Economic Cycle Detection
    # ------------------------------------------------------------------

    def _detect_economic_cycle(self):
        g = self.indicators
        expansion_score = 0
        recession_score = 0
        expansion_details = []
        recession_details = []

        # 1. Sahm Rule
        sahm = g.get("SAHM")
        if sahm is not None:
            if sahm >= threshold("SAHM"):
                recession_score += 1
                recession_details.append(f"萨姆规则触发 ({sahm:.2f}≥{threshold('SAHM'):.1f})")
            elif sahm < CYCLE_LEVELS["SAHM_SAFE"]:
                expansion_score += 1
                expansion_details.append(f"萨姆规则安全 ({sahm:.2f})")

        # 2. Unemployment trend
        unrate = g.get("UNRATE")
        unrate_trend = g.get("UNRATE_TREND")
        if unrate is not None:
            if unrate < CYCLE_LEVELS["UNRATE_LOW"] and unrate_trend == "falling":
                expansion_score += 1
                expansion_details.append(f"失业率低且下降 ({unrate:.1f}%)")
            elif unrate_trend == "rising":
                recession_score += 1
                recession_details.append(f"失业率上升趋势 ({unrate:.1f}%)")

        # 3. Yield curve
        t10y2y = g.get("T10Y2Y")
        if t10y2y is not None:
            if t10y2y > CYCLE_LEVELS["CURVE_NORMAL"]:
                expansion_score += 1
                expansion_details.append(f"收益率曲线正常 ({t10y2y:.2f}%)")
            elif t10y2y < 0:
                recession_score += 1
                recession_details.append(f"收益率曲线倒挂 ({t10y2y:.2f}%)")
            else:
                t_s = self.f.get_fred_series("T10Y2Y")
                if t_s is not None and len(t_s) >= 20:
                    was_inverted = (t_s.iloc[-20:-5] < 0).any()
                    if was_inverted and t10y2y > 0:
                        recession_score += 1
                        recession_details.append(f"收益率曲线刚解倒挂 ({t10y2y:.2f}%)")

        # 4. Credit spreads (basis points — see FRED_SCALE)
        hy = g.get("HY_OAS")
        if hy is not None:
            hy_widening = False
            hy_s = self.f.get_fred_series("HY_OAS")
            if hy_s is not None and len(hy_s) >= 21:
                hy_widening = float(hy_s.iloc[-1]) > float(hy_s.iloc[-21])
            if hy < CYCLE_LEVELS["HY_OAS_HEALTHY"]:
                expansion_score += 1
                expansion_details.append(f"信用利差健康 ({hy:.0f}bp)")
            elif hy > CYCLE_LEVELS["HY_OAS_STRESS"] and hy_widening:
                # spec requires 「> 500bp 且走阔」 — level alone is not enough
                recession_score += 1
                recession_details.append(f"信用利差走阔 ({hy:.0f}bp, 月度上行)")

        # 5. Initial Claims (thousands — see FRED_SCALE)
        icsa_avg = g.get("ICSA_4W_AVG")
        icsa_trend = g.get("ICSA_TREND")
        if icsa_avg is not None:
            if icsa_avg < CYCLE_LEVELS["ICSA_LOW"]:
                expansion_score += 1
                expansion_details.append(f"初请失业金低 ({icsa_avg:.0f}k)")
            elif icsa_avg > CYCLE_LEVELS["ICSA_HIGH"] and icsa_trend == "rising":
                recession_score += 1
                recession_details.append(f"初请失业金上升 ({icsa_avg:.0f}k)")

        # 6. Nonfarm Payrolls
        payems_avg = g.get("PAYEMS_3M_AVG")
        if payems_avg is not None:
            if payems_avg > CYCLE_LEVELS["PAYEMS_STRONG"]:
                expansion_score += 1
                expansion_details.append(f"非农强劲 (月均+{payems_avg:.0f}k)")
            elif payems_avg < 0:
                recession_score += 1
                recession_details.append(f"非农转负 (月均{payems_avg:.0f}k)")
            elif payems_avg < CYCLE_LEVELS["PAYEMS_WEAK"]:
                recession_score += 1
                recession_details.append(f"非农放缓 (月均+{payems_avg:.0f}k)")

        # 7. M2 growth
        m2 = g.get("M2_YOY")
        if m2 is not None:
            if m2 > 2:
                expansion_score += 1
                expansion_details.append(f"M2增速正 ({m2:.1f}%)")
            elif m2 < 0:
                recession_score += 1
                recession_details.append(f"M2增速负 ({m2:.1f}%)")

        # 8. Copper/Gold trend
        cu_au_trend = g.get("CU_AU_TREND")
        if cu_au_trend == "rising":
            expansion_score += 1
            expansion_details.append("铜/金比值上升")
        elif cu_au_trend == "falling":
            recession_score += 1
            recession_details.append("铜/金比值下降")

        # 9. Manufacturing PMI proxy (spec: PMI > 50 上升 / < 50 下降)
        # Replaces the former "SPY vs MA200" slot. Judging the economy partly
        # by the market's own trend, then using that judgement to set market
        # exposure, is circular — the spec's scorecard is entirely economic.
        pmi = g.get("PMI_PROXY")
        pmi_trend = g.get("PMI_TREND")
        if pmi is not None:
            if pmi > PMI_LEVELS["CONTRACTION"] and pmi_trend == "rising":
                expansion_score += 1
                expansion_details.append(f"制造业景气扩张 (扩散指数 {pmi:+.1f}, 上升)")
            elif pmi < PMI_LEVELS["CONTRACTION"] and pmi_trend == "falling":
                recession_score += 1
                recession_details.append(f"制造业景气收缩 (扩散指数 {pmi:+.1f}, 下降)")

        # 10. Real GDP year-over-year (spec: GDP同比增速 > 2%)
        # Replaces the former "XLY/XLU" slot, for the same reason.
        gdp_yoy = g.get("GDP_YOY")
        if gdp_yoy is not None:
            if gdp_yoy > CYCLE_LEVELS["GDP_YOY_STRONG"]:
                expansion_score += 1
                expansion_details.append(f"GDP同比 +{gdp_yoy:.1f}%")
            elif gdp_yoy < 0:
                recession_score += 1
                recession_details.append(f"GDP同比转负 ({gdp_yoy:.1f}%)")

        # Determine inflation level
        cpi_yoy = g.get("CPI_YOY")
        cpi_high = SIGNAL_LEVELS["CPI_HIGH_YOY"]
        cpi_moderate = SIGNAL_LEVELS["CPI_MODERATE_YOY"]
        inflation_high = gt(cpi_yoy, cpi_high)
        inflation_label = "N/A"
        if cpi_yoy is not None:
            if cpi_yoy > cpi_high:
                inflation_label = f"高通胀 ({cpi_yoy:.1f}%)"
            elif cpi_yoy > cpi_moderate:
                inflation_label = f"温和通胀 ({cpi_yoy:.1f}%)"
            else:
                inflation_label = f"低通胀 ({cpi_yoy:.1f}%)"

        # Cycle gates, per 《经济周期长期投资策略》3.3 判断规则:
        #   扩张≥7 且 衰退≤2 -> 扩张期
        #   扩张≤3 且 衰退≥6 -> 衰退期
        #   其余              -> 过渡期
        # The old code fired 衰退期 on `recession_score >= 5` alone, ignoring
        # the expansion score entirely — so 扩张9/衰退5 was classified as a
        # recession and allocated 10-15% equity where the spec says balanced.
        recession_confirmed = (
            recession_score >= CYCLE_GATES["RECESSION_MIN"]
            and expansion_score <= CYCLE_GATES["RECESSION_MAX_EXPANSION"])
        expansion_confirmed = (
            expansion_score >= CYCLE_GATES["EXPANSION_MIN"]
            and recession_score <= CYCLE_GATES["EXPANSION_MAX_RECESSION"])
        # Middle band of the spec's 过渡期, where the allocation table still
        # wants the finer 周期末期 / 滞胀前期 distinction.
        deteriorating = (recession_score >= CYCLE_GATES["MID_RECESSION_MIN"]
                         and expansion_score <= CYCLE_GATES["MID_EXPANSION_MAX"])

        # Determine cycle phase
        if recession_confirmed and inflation_high:
            cycle = "stagflation"
            cycle_cn = "滞胀期 (Stagflation)"
            cycle_desc = "经济增长停滞但通胀高企，最难赚钱的阶段"
        elif recession_confirmed:
            cycle = "recession"
            cycle_cn = "衰退期 (Recession)"
            cycle_desc = "经济收缩，保住本金优先，等待底部抄底机会"
        elif deteriorating and inflation_high:
            cycle = "late_stagflation"
            cycle_cn = "滞胀前期 (Pre-Stagflation)"
            cycle_desc = "通胀高企且经济出现放缓迹象，需要提高防御"
        elif deteriorating:
            cycle = "late_cycle"
            cycle_cn = "周期末期 (Late Cycle)"
            cycle_desc = "扩张晚期，多项衰退预警出现，逐步转向防御"
        elif expansion_confirmed:
            # 复苏期 is the early sub-phase of a confirmed expansion: growth
            # is back but unemployment is only just off its peak. It used to
            # sit in a looser `expansion_score >= 5` branch, which labelled
            # 扩张期 at scores the spec assigns to 过渡期.
            unrate_s = self.f.get_fred_series("UNRATE")
            is_recovery = False
            if unrate_s is not None and len(unrate_s) >= 6:
                peak_recent = float(unrate_s.iloc[-6:].max())
                now_val = float(unrate_s.iloc[-1])
                if peak_recent > 5.0 and now_val < peak_recent:
                    is_recovery = True
            if is_recovery:
                cycle = "recovery"
                cycle_cn = "复苏期 (Recovery)"
                cycle_desc = "经济从低谷复苏，成长股和小盘股弹性最大"
            else:
                cycle = "expansion"
                cycle_cn = "扩张期 (Expansion)"
                cycle_desc = "经济稳健增长，正常持有风险资产"
        else:
            cycle = "transition"
            cycle_cn = "过渡期 (Transition)"
            cycle_desc = "经济信号混合，扩张和衰退信号共存，保持均衡配置"

        allocation = self._cycle_allocation(cycle, inflation_high)

        # The allocation table treats long Treasuries as the equity hedge. If
        # the rolling correlation has flipped positive that assumption no
        # longer holds, so say so next to the weights instead of leaving the
        # reader to assume 2000s-style diversification.
        corr = g.get("STOCK_BOND_CORR")
        alloc_caveats = []
        if corr is not None and corr > CORR_LEVELS["HEDGE_BROKEN"]:
            alloc_caveats.append(
                f"股债{CORR_WINDOW}日相关性 {corr:+.2f} 为正 —— 长债当前不对冲股票，"
                "债券仓位的分散作用弱于配置表假设")
        elif corr is not None and corr < CORR_LEVELS["HEDGE_GOOD"]:
            alloc_caveats.append(f"股债{CORR_WINDOW}日相关性 {corr:+.2f}，长债对冲有效")
        erp_n = g.get("ERP_NOMINAL")
        if erp_n is not None and erp_n < VALUATION_LEVELS["ERP_THIN"]:
            alloc_caveats.append(
                f"标普盈利收益率 {g['SPY_EY']:.2f}% 低于10Y {g['US10Y']:.2f}%"
                f"（差 {erp_n:+.2f}pp）—— 股票相对债券无估值补偿")

        return {
            "cycle": cycle,
            "cycle_cn": cycle_cn,
            "cycle_desc": cycle_desc,
            "expansion_score": expansion_score,
            "recession_score": recession_score,
            "expansion_details": expansion_details,
            "recession_details": recession_details,
            "inflation_label": inflation_label,
            "cpi_yoy": cpi_yoy,
            "allocation": allocation,
            "allocation_caveats": alloc_caveats,
        }

    # ------------------------------------------------------------------
    # Position-target signal analysis (QQQM / SPYM)
    # ------------------------------------------------------------------

    def _analyze_position_targets(self):
        """Compute per-target buy/sell scores for each POSITION_TARGET."""
        g = self.indicators
        results = {}

        # --- Layer 1: Macro gate (shared across all targets) ---
        sahm = g.get("SAHM")
        fg = g.get("FEAR_GREED")
        hy = g.get("HY_OAS")
        vix_val = g.get("VIX")

        macro_gate = "正常"
        macro_locked_no_buy = False
        macro_downgrade = False

        if gte(sahm, threshold("SAHM")):
            macro_gate = "衰退锁定"
            macro_locked_no_buy = True
        elif gt(fg, SIGNAL_LEVELS["FG_GREED"]):
            macro_gate = "贪婪锁定"
            macro_locked_no_buy = True

        # Reachable now that HY_OAS is scaled to basis points; on the old
        # percent-scaled value this gate could never fire.
        if gt(hy, threshold("HY_OAS")):
            macro_downgrade = True
            if macro_gate == "正常":
                macro_gate = "信用风险"

        extreme_fear = lt(fg, SIGNAL_LEVELS["FG_POSITION_FEAR"])

        for target_name, cfg in POSITION_TARGETS.items():
            ticker = cfg["ticker"]
            label = cfg["label"]
            bench_vix_key = cfg["benchmark_vix"]

            series = self.f.get_series(ticker)
            if series is None or len(series) < MA200:
                results[target_name] = {
                    "label": label, "price": None,
                    "action": "数据不足", "action_level": "unknown",
                    "final_score": 0, "details": ["价格数据不足以计算MA200"],
                    "macro_gate": macro_gate,
                }
                continue

            price = float(series.iloc[-1])
            ma50_s = calc_sma(series, MA50)
            ma200_s = calc_sma(series, MA200)
            rsi_s = calc_rsi(series)
            macd_line, sig_line, _ = calc_macd(series)

            ma50_val = latest(ma50_s)
            ma200_val = latest(ma200_s)
            rsi_val = latest(rsi_s)

            # 52-week high drawdown
            high_52w = (float(series.iloc[-TRADING_DAYS_YEAR:].max())
                        if len(series) >= TRADING_DAYS_YEAR else float(series.max()))
            drawdown = (price / high_52w - 1) * 100 if high_52w > 0 else 0

            # MACD cross detection (last 2 bars)
            macd_cross = None
            if macd_line is not None and sig_line is not None and len(macd_line) >= 2:
                prev_diff = float(macd_line.iloc[-2] - sig_line.iloc[-2])
                curr_diff = float(macd_line.iloc[-1] - sig_line.iloc[-1])
                macd_val = float(macd_line.iloc[-1])
                if prev_diff <= 0 and curr_diff > 0:
                    macd_cross = "golden_cross"
                elif prev_diff >= 0 and curr_diff < 0:
                    macd_cross = "death_cross"
            else:
                macd_val = None

            # RSI divergence
            divergence = check_rsi_divergence(series, rsi_s)

            # --- Layer 2: Technical scoring ---
            score = 0
            details = []

            # Price vs MA200
            pct_ma200 = pct_above(price, ma200_val)
            if pct_ma200 is not None:
                if pct_ma200 < -10:
                    score += 3
                    details.append(f"距MA200 {pct_ma200:.1f}% 极端超卖(+3)")
                elif pct_ma200 < -5:
                    score += 2
                    details.append(f"距MA200 {pct_ma200:.1f}% 深度回调(+2)")
                elif -3 <= pct_ma200 <= 2:
                    score += 1
                    details.append(f"距MA200 {pct_ma200:.1f}% 支撑试探(+1)")
                elif pct_ma200 > 20:
                    score -= 2
                    details.append(f"距MA200 +{pct_ma200:.1f}% 显著过热(-2)")
                elif pct_ma200 > 15:
                    score -= 1
                    details.append(f"距MA200 +{pct_ma200:.1f}% 过热警告(-1)")

            # Price below MA50 but above MA200
            pct_ma50 = pct_above(price, ma50_val)
            if pct_ma50 is not None and pct_ma200 is not None:
                if pct_ma50 < 0 and pct_ma200 > 0:
                    score += 1
                    details.append(f"跌破MA50但仍在MA200上方(+1)")

            # RSI
            if rsi_val is not None:
                if rsi_val < 25:
                    score += 3
                    details.append(f"RSI={rsi_val:.1f} 极端超卖(+3)")
                elif rsi_val < 30:
                    score += 2
                    details.append(f"RSI={rsi_val:.1f} 超卖(+2)")
                elif rsi_val < 40:
                    score += 1
                    details.append(f"RSI={rsi_val:.1f} 接近超卖(+1)")
                elif rsi_val > 80:
                    score -= 2
                    details.append(f"RSI={rsi_val:.1f} 超买(-2)")
                elif rsi_val > 70:
                    score -= 1
                    details.append(f"RSI={rsi_val:.1f} 接近超买(-1)")

            # MACD cross
            if macd_cross == "golden_cross" and macd_val is not None and macd_val < 0:
                score += 2
                details.append("MACD零轴下金叉(+2)")
            elif macd_cross == "death_cross" and macd_val is not None and macd_val > 0:
                score -= 1
                details.append("MACD零轴上死叉(-1)")

            # 52-week high drawdown
            if drawdown <= -20:
                score += 3
                details.append(f"距52周高 {drawdown:.1f}% 技术性熊市(+3)")
            elif drawdown <= -15:
                score += 2
                details.append(f"距52周高 {drawdown:.1f}% 深度调整(+2)")
            elif drawdown <= -10:
                score += 1
                details.append(f"距52周高 {drawdown:.1f}% 常规回调(+1)")

            # RSI divergence
            if divergence == "bullish":
                score += 2
                details.append("RSI底背离(+2)")
            elif divergence == "bearish":
                score -= 2
                details.append("RSI顶背离(-2)")

            # VIX + oversold combo
            bench_vix = g.get(bench_vix_key)
            if bench_vix is None:
                bench_vix = vix_val
            if gt(bench_vix, 30) and lt(rsi_val, 35):
                score += 2
                details.append(f"{bench_vix_key}={bench_vix:.1f}+RSI超卖 黄金坑(+2)")

            # Valuation gate on conviction. A technically oversold entry into
            # a market whose earnings yield sits below the risk-free rate is a
            # weaker proposition than the same setup when equities are paid
            # for; this trims the add rather than adding to the risk score.
            erp = g.get("ERP_NOMINAL")
            if erp is not None and score > 0:
                if erp < VALUATION_LEVELS["ERP_THIN"]:
                    score -= 1
                    details.append(f"盈利收益率低于10Y {abs(erp):.2f}pp 估值无保护(-1)")
                elif erp > VALUATION_LEVELS["ERP_RICH"]:
                    score += 1
                    details.append(f"盈利收益率高于10Y {erp:.2f}pp 估值有补偿(+1)")

            # Fear&Greed + RSI overbought combo
            if gt(fg, 80) and gt(rsi_val, 65):
                score -= 2
                details.append(f"F&G={fg:.0f}+RSI={rsi_val:.1f} 过热(-2)")

            # Consecutive down days + cumulative decline
            # (thresholds from 30-year backtest of QQQ/SPY)
            if len(series) >= 10:
                consec_days = 0
                for j in range(len(series) - 1, 0, -1):
                    if series.iloc[j] < series.iloc[j - 1]:
                        consec_days += 1
                    else:
                        break
                if consec_days >= 3:
                    streak_start_price = float(series.iloc[-(consec_days + 1)])
                    cum_decline = (price / streak_start_price - 1) * 100
                    # Use highest matching tier only (no double counting)
                    if consec_days >= 5 and cum_decline <= -7:
                        score += 3
                        details.append(f"连续{consec_days}天下跌 累计{cum_decline:.1f}% 重仓级(+3)")
                    elif consec_days >= 4 and cum_decline <= -5:
                        score += 2
                        details.append(f"连续{consec_days}天下跌 累计{cum_decline:.1f}% 加仓级(+2)")
                    elif consec_days >= 3 and cum_decline <= -4:
                        score += 1
                        details.append(f"连续{consec_days}天下跌 累计{cum_decline:.1f}% 关注级(+1)")

            raw_score = score

            # --- Layer 1 macro adjustment ---
            # Extreme Fear is worth +2 once. Previously it was paid twice:
            # a blanket macro bonus plus a separate "extreme fear + MA200
            # support" combo, so one F&G reading could contribute +4. These
            # are now exclusive tiers, matching the no-double-counting rule
            # already applied to the consecutive-down-day scoring above.
            macro_bonus = 0
            if extreme_fear:
                macro_bonus = 2
                score += macro_bonus
                if pct_ma200 is not None and abs(pct_ma200) < 5:
                    details.append(f"F&G={fg:.0f} 极恐+MA200支撑(+2)")
                else:
                    details.append(f"F&G={fg:.0f} 宏观极恐加权(+2)")

            # --- Layer 3: Score -> action ---
            action, action_level, position_change = self._score_to_action(score)

            # Macro gate overrides
            if macro_locked_no_buy and score > 0:
                if action_level in ("strong_buy", "buy", "consider_buy"):
                    action = f"观望（{macro_gate}）"
                    action_level = "hold"
                    position_change = "维持"
                    details.append(f"⚠️ {macro_gate}: 技术面看多但宏观禁止加仓")

            if macro_downgrade and action_level == "strong_buy":
                action = "建议加仓（信用风险降级）"
                action_level = "buy"
                position_change = "5%"
                details.append("⚠️ HY OAS>500bp: 强烈加仓降级为建议加仓")

            results[target_name] = {
                "label": label,
                "price": price,
                "ma50": ma50_val,
                "ma200": ma200_val,
                "rsi": rsi_val,
                "macd_cross": macd_cross,
                "drawdown_from_high": drawdown,
                "high_52w": high_52w,
                "pct_ma200": pct_ma200,
                "pct_ma50": pct_ma50,
                "raw_score": raw_score,
                "macro_adjustment": macro_bonus,
                "final_score": score,
                "action": action,
                "action_level": action_level,
                "position_change": position_change,
                "details": details,
                "macro_gate": macro_gate,
            }

        return results

    @staticmethod
    def _score_to_action(score):
        if score >= 6:
            return ("强烈加仓", "strong_buy", "8-10%")
        elif score >= 4:
            return ("建议加仓", "buy", "5%")
        elif score >= 2:
            return ("可考虑加仓", "consider_buy", "2-3%")
        elif score >= -1:
            return ("观望", "hold", "维持")
        elif score >= -3:
            return ("考虑减仓", "consider_sell", "减5%")
        else:
            return ("建议减仓", "sell", "减10-15%")

    def _cycle_allocation(self, cycle, inflation_high):
        allocations = {
            "recovery": {
                "stocks": ("40-50%", "VOO(0.03%)+QQQM(0.15%) 30%, XLV(0.09%)+VXUS(0.05%) 10%"),
                "long_bonds": ("15-20%", "VGLT(0.04%)"),
                "cash": ("5-10%", "BOXX(0.19%)+SGOV(0.09%)"),
                "gold": ("5-10%", "IAUM(0.09%)"),
                "tips": ("10%", "SCHP(0.03%)"),
                "commodities": ("10%", "PDBC(0.59%)"),
            },
            "expansion": {
                "stocks": ("35-40%", "VOO(0.03%)+QQQM(0.15%) 30%, XLV(0.09%)+VXUS(0.05%) 10%"),
                "long_bonds": ("15%", "VGLT(0.04%)"),
                "cash": ("10-15%", "BOXX(0.19%)+SGOV(0.09%)"),
                "gold": ("10%", "IAUM(0.09%)"),
                "tips": ("10%", "SCHP(0.03%)"),
                "commodities": ("10%", "PDBC(0.59%)"),
            },
            "late_cycle": {
                "stocks": ("25-30%", "VOO(0.03%) 10%, XLV(0.09%)+XLP 15%, XLE 5%"),
                "long_bonds": ("10-15%", "VGLT(0.04%)"),
                "cash": ("20-25%", "BOXX(0.19%)+SGOV(0.09%)"),
                "gold": ("15-20%", "IAUM(0.09%)"),
                "tips": ("10-15%", "SCHP(0.03%)"),
                "commodities": ("10%", "PDBC(0.59%)"),
            },
            "stagflation": {
                "stocks": ("10-15%", "XLV(0.09%)+XLP 10%, XLE 5%"),
                "long_bonds": ("0-5%", "加息期长债暴跌，极低配置"),
                "cash": ("25-30%", "BOXX(0.19%)+SGOV(0.09%) — 0派息规避红利税"),
                "gold": ("20-25%", "IAUM(0.09%) — 滞胀期最优资产"),
                "tips": ("15%", "SCHP(0.03%) — 通胀保护"),
                "commodities": ("15%", "PDBC(0.59%)"),
            },
            "late_stagflation": {
                "stocks": ("15-20%", "XLV(0.09%)+XLP 10%, XLE 5%"),
                "long_bonds": ("5-10%", "VGLT(0.04%)"),
                "cash": ("20-25%", "BOXX(0.19%)+SGOV(0.09%)"),
                "gold": ("20%", "IAUM(0.09%)"),
                "tips": ("15%", "SCHP(0.03%)"),
                "commodities": ("10-15%", "PDBC(0.59%)"),
            },
            "recession": {
                "stocks": ("10-15%", "XLV(0.09%)+XLP 10%, SCHD(0.06%) 5% (仅底仓)"),
                "long_bonds": ("25-35%", "VGLT(0.04%) — 衰退期最优资产"),
                "cash": ("25-30%", "BOXX(0.19%)+SGOV(0.09%) — 抄底弹药"),
                "gold": ("10-15%", "IAUM(0.09%)"),
                "tips": ("5%", "SCHP(0.03%)"),
                "commodities": ("5%", "PDBC(0.59%)"),
            },
            "transition": {
                "stocks": ("30%", "VOO(0.03%)+QQQM(0.15%) 25%, XLV(0.09%) 5%"),
                "long_bonds": ("20%", "VGLT(0.04%)"),
                "cash": ("15%", "BOXX(0.19%)+SGOV(0.09%)"),
                "gold": ("15%", "IAUM(0.09%)"),
                "tips": ("10%", "SCHP(0.03%)"),
                "commodities": ("10%", "PDBC(0.59%)"),
            },
        }
        return allocations.get(cycle, allocations["transition"])

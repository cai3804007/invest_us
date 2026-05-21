import numpy as np
import pandas as pd
from config import MA50, MA200, MA250, RSI_PERIOD, LEADING_STOCKS


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


def check_rsi_divergence(price_series, rsi_series, lookback=20):
    """Return 'bearish' / 'bullish' / None"""
    if price_series is None or rsi_series is None:
        return None
    if len(price_series) < lookback or len(rsi_series) < lookback:
        return None
    p = price_series.iloc[-lookback:]
    r = rsi_series.iloc[-lookback:]
    price_now = p.iloc[-1]
    rsi_now = r.iloc[-1]
    price_prev_high = p.iloc[:-5].max()
    rsi_at_prev_high = r.iloc[:-5].max()
    price_prev_low = p.iloc[:-5].min()
    rsi_at_prev_low = r.iloc[:-5].min()
    if price_now >= price_prev_high and rsi_now < rsi_at_prev_high - 2:
        return "bearish"
    if price_now <= price_prev_low and rsi_now > rsi_at_prev_low + 2:
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

    def analyze(self):
        self._gather_indicators()
        self._gather_cycle_indicators()
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

        return {
            "indicators": self.indicators,
            "signals": self.signals,
            "risk_score": self.risk_score,
            "risk_level": risk_level,
            "market_phase": phase,
            "recommendation": rec,
            "recommendation_detail": rec_detail,
            "leader_health": self.leader_health,
            "combos": self.combos,
            "economic_cycle": cycle_result,
        }

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
        g["DIA"] = self.f.get_latest("DIA")
        g["RSP"] = self.f.get_latest("RSP")

        market_summary = []
        for name, label in [("SPY", "标普500"), ("QQQ", "纳指100"), ("DIA", "道琼斯"),
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

    def _add_signal(self, name, score, level, desc=""):
        self.signals.append({
            "name": name,
            "score": score,
            "level": level,  # "danger" / "warning" / "safe"
            "desc": desc,
        })
        self.risk_score += score

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
                self._add_signal("US10Y连续5日上涨", 10, "danger", f"当前 {g['US10Y']:.2f}%")
            elif len(diffs) >= 4 and (diffs < 0).all():
                self._add_signal("US10Y近期持续回落", -10, "safe", f"当前 {g['US10Y']:.2f}%")

        if g.get("US10Y") is not None and g["US10Y"] > 4.5:
            self._add_signal("US10Y处于高位", 10, "danger", f"{g['US10Y']:.2f}% > 4.5%")

        # TIPS
        tips = g.get("TIPS")
        if tips is not None:
            tips_s = self.f.get_fred_series("TIPS")
            if tips_s is not None and len(tips_s) >= 5:
                tips_chg = float(tips_s.iloc[-1] - tips_s.iloc[-5])
                if tips > 2.0 and tips_chg > 0:
                    self._add_signal("TIPS实际利率走高", 10, "danger", f"{tips:.2f}% 且近期上升")
                elif tips_chg < -0.1:
                    self._add_signal("TIPS实际利率回落", -10, "safe", f"{tips:.2f}%")

        # DXY
        dxy = g.get("DXY")
        if dxy is not None:
            if dxy > 105:
                self._add_signal("DXY突破105", 10, "danger", f"当前 {dxy:.1f}")
            dxy_s = self.f.get_series("DXY")
            if dxy_s is not None and len(dxy_s) >= 6:
                week_chg = (dxy_s.iloc[-1] / dxy_s.iloc[-5] - 1) * 100
                if week_chg > 2:
                    self._add_signal("DXY单周暴涨", 10, "danger", f"周涨幅 {week_chg:.1f}%")

        # HY OAS
        hy = g.get("HY_OAS")
        if hy is not None:
            hy_s = self.f.get_fred_series("HY_OAS")
            if hy_s is not None and len(hy_s) >= 6:
                week_chg = float(hy_s.iloc[-1] - hy_s.iloc[-5])
                if week_chg > 50:
                    self._add_signal("HY OAS利差急剧走阔", 10, "danger", f"周变化 +{week_chg:.0f}bp")

        # M2
        m2_yoy = g.get("M2_YOY")
        if m2_yoy is not None:
            if m2_yoy > 0:
                m2_s = self.f.get_fred_series("M2")
                if m2_s is not None and len(m2_s) >= 3:
                    recent_trend = float(m2_s.iloc[-1] - m2_s.iloc[-3])
                    if recent_trend > 0:
                        self._add_signal("M2货币供应增速回升", -10, "safe", f"同比 {m2_yoy:.1f}%")
            elif m2_yoy < -1:
                self._add_signal("M2货币供应萎缩", 5, "warning", f"同比 {m2_yoy:.1f}%")

    # ------------------------------------------------------------------
    # Sentiment analysis
    # ------------------------------------------------------------------

    def _analyze_sentiment(self):
        g = self.indicators

        vix = g.get("VIX")
        vxn = g.get("VXN")

        if vix is not None and vix > 25:
            self._add_signal("VIX进入风险区间", 10, "danger", f"VIX={vix:.1f}")
        if vxn is not None and vxn > 30:
            self._add_signal("VXN进入风险区间", 10, "danger", f"VXN={vxn:.1f}")

        # VIX term structure
        vt = g.get("VIX_TERM")
        if vt is not None and vt > 1.0:
            self._add_signal("VIX期限结构倒挂", 10, "danger",
                             f"VIX/VIX3M={vt:.2f}，近月恐慌高于远月")

        # SKEW
        skew = g.get("SKEW")
        if skew is not None and vix is not None:
            if skew > 140 and vix < 20:
                self._add_signal("SKEW高+VIX低: 暗流涌动", 5, "warning",
                                 f"SKEW={skew:.0f}, VIX={vix:.1f}")
            elif skew > 150:
                self._add_signal("SKEW极端: 尾部风险焦虑", 5, "warning", f"SKEW={skew:.0f}")

        # Fear & Greed
        fg = g.get("FEAR_GREED")
        if fg is not None:
            if fg < 15:
                self._add_signal("极度恐惧（Fear&Greed<15）", 0, "safe",
                                 f"得分={fg:.0f}，可能是黄金坑")
            elif fg > 85:
                self._add_signal("极度贪婪（Fear&Greed>85）", 5, "warning",
                                 f"得分={fg:.0f}，注意过热")

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
                self._add_signal("SOX跌破50日均线", 15, "danger",
                                 f"SOX={sox_now:.0f}, MA50={sox_ma50:.0f}")
            else:
                self._add_signal("SOX站稳50日均线上方", -10, "safe",
                                 f"SOX={sox_now:.0f}, MA50={sox_ma50:.0f}")

        # SOX vs QQQ relative strength (20-day return)
        qqq_s = self.f.get_series("QQQ")
        if sox_s is not None and qqq_s is not None:
            if len(sox_s) >= 20 and len(qqq_s) >= 20:
                sox_ret = (sox_s.iloc[-1] / sox_s.iloc[-20] - 1) * 100
                qqq_ret = (qqq_s.iloc[-1] / qqq_s.iloc[-20] - 1) * 100
                diff = sox_ret - qqq_ret
                g["SOX_20D"] = float(sox_ret)
                g["QQQ_20D"] = float(qqq_ret)
                if diff < -3:
                    self._add_signal("SOX明显弱于QQQ", 10, "danger",
                                     f"SOX 20日={sox_ret:.1f}%, QQQ={qqq_ret:.1f}%")

        # RSP/SPY breadth
        rsp_chg = g.get("RSP_SPY_20D_CHG")
        if rsp_chg is not None:
            spy_s = self.f.get_series("SPY")
            if spy_s is not None and len(spy_s) >= 20:
                spy_ret = (spy_s.iloc[-1] / spy_s.iloc[-20] - 1) * 100
                if spy_ret > 2 and rsp_chg < -1:
                    self._add_signal("市场广度恶化: SPY涨但RSP/SPY比值下降", 10, "danger",
                                     f"RSP/SPY 20日变化={rsp_chg:.1f}%")
                elif rsp_chg > 0:
                    self._add_signal("市场广度健康", -10, "safe",
                                     f"RSP/SPY比值 20日变化={rsp_chg:.1f}%")

        # XLY/XLU sector rotation
        xly_xlu = g.get("XLY_XLU")
        if xly_xlu is not None:
            xly_s = self.f.get_series("XLY")
            xlu_s = self.f.get_series("XLU")
            if xly_s is not None and xlu_s is not None and len(xly_s) >= 20 and len(xlu_s) >= 20:
                ratio_now = xly_s.iloc[-1] / xlu_s.iloc[-1]
                ratio_20d = xly_s.iloc[-20] / xlu_s.iloc[-20]
                if ratio_now < ratio_20d * 0.97:
                    self._add_signal("板块轮动: 资金转向防御", 5, "warning",
                                     f"XLY/XLU比值下降")

    # ------------------------------------------------------------------
    # Macro analysis
    # ------------------------------------------------------------------

    def _analyze_macro(self):
        g = self.indicators

        # Sahm Rule
        sahm = g.get("SAHM")
        if sahm is not None:
            if sahm >= 0.5:
                self._add_signal("萨姆规则已触发!", 20, "danger",
                                 f"当前值={sahm:.2f} >= 0.5，衰退信号")

        # Yield curve de-inversion
        t10y2y = g.get("T10Y2Y")
        if t10y2y is not None:
            t_s = self.f.get_fred_series("T10Y2Y")
            if t_s is not None and len(t_s) >= 20:
                was_inverted = (t_s.iloc[-20:-5] < 0).any()
                now_positive = t10y2y > 0
                if was_inverted and now_positive and t10y2y > 0.1:
                    self._add_signal("收益率曲线刚解倒挂!", 15, "danger",
                                     f"10Y-2Y利差={t10y2y:.2f}%，快速转正")

    # ------------------------------------------------------------------
    # Technical analysis
    # ------------------------------------------------------------------

    def _analyze_technical(self):
        g = self.indicators

        spy = g.get("SPY")
        spy_ma200 = g.get("SPY_MA200")
        if spy is not None and spy_ma200 is not None:
            if spy < spy_ma200:
                self._add_signal("SPY跌破200日均线", 10, "danger",
                                 f"SPY={spy:.1f}, MA200={spy_ma200:.1f}")

        qqq = g.get("QQQ")
        qqq_ma200 = g.get("QQQ_MA200")
        if qqq is not None and qqq_ma200 is not None:
            if qqq < qqq_ma200:
                self._add_signal("QQQ跌破200日均线", 10, "danger",
                                 f"QQQ={qqq:.1f}, MA200={qqq_ma200:.1f}")

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
                        self._add_signal("SPY金叉（MA50上穿MA200）", -10, "safe", "牛市确认信号")
                    elif prev > 0 and curr < 0:
                        self._add_signal("SPY死叉（MA50下穿MA200）", 10, "danger", "熊市确认信号")

        # RSI divergence
        qqq_s = self.f.get_series("QQQ")
        if qqq_s is not None:
            rsi_s = calc_rsi(qqq_s)
            div = check_rsi_divergence(qqq_s, rsi_s)
            if div == "bearish":
                self._add_signal("QQQ出现RSI顶背离", 5, "warning", "上涨动能可能衰竭")
            elif div == "bullish":
                self._add_signal("QQQ出现RSI底背离", -5, "safe", "下跌动能可能衰竭")

    # ------------------------------------------------------------------
    # Leading stock health
    # ------------------------------------------------------------------

    def _analyze_leaders(self):
        weak_count = 0
        for stock in LEADING_STOCKS:
            s = self.f.get_series(stock)
            if s is None or len(s) < MA50:
                self.leader_health.append({
                    "name": stock, "price": None, "vs_ma50": None,
                    "vs_ma200": None, "ret_20d": None, "status": "N/A"
                })
                continue

            price = float(s.iloc[-1])
            ma50 = float(s.rolling(MA50).mean().iloc[-1])
            ma200_val = float(s.rolling(MA200).mean().iloc[-1]) if len(s) >= MA200 else None
            ret20 = (s.iloc[-1] / s.iloc[-20] - 1) * 100 if len(s) >= 20 else None

            vs50 = (price - ma50) / ma50 * 100
            vs200 = (price - ma200_val) / ma200_val * 100 if ma200_val else None

            if price < ma50:
                status = "danger"
                weak_count += 1
            elif vs50 < 2:
                status = "warning"
            else:
                status = "safe"

            self.leader_health.append({
                "name": stock, "price": price,
                "vs_ma50": vs50, "vs_ma200": vs200,
                "ret_20d": float(ret20) if ret20 is not None else None,
                "status": status,
            })

        if weak_count >= 3:
            self._add_signal(f"多数龙头股走弱（{weak_count}/{len(LEADING_STOCKS)}跌破MA50）",
                             15, "danger", "指数可能补跌")

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
            c1_triggered = dxy_up and vix_up and (dxy_chg > 0.5 or vix_chg > 3)
            if c1_triggered:
                self._add_signal("高危组合: DXY+VIX同时上涨", 15, "danger",
                                 f"DXY周涨{dxy_chg:.1f}%, VIX周升{vix_chg:.1f}")
        self.combos.append({
            "name": "DXY+VIX同涨",
            "triggered": c1_triggered,
            "detail": "全球流动性收紧+恐慌" if c1_triggered else ""
        })

        # Combo 2: SOX weak + breadth bad + RSI divergence
        sox_weak = any(s["name"] == "SOX跌破50日均线" for s in self.signals)
        breadth_bad = any("广度恶化" in s["name"] for s in self.signals)
        rsi_div = any("RSI顶背离" in s["name"] for s in self.signals)
        c2_count = sum([sox_weak, breadth_bad, rsi_div])
        c2_triggered = c2_count >= 2
        self.combos.append({
            "name": "SOX弱+广度差+RSI背离",
            "triggered": c2_triggered,
            "detail": f"{c2_count}/3 触发"
        })

        # Combo 3: Yield curve de-inversion + Sahm Rule
        curve_signal = any("解倒挂" in s["name"] for s in self.signals)
        sahm_signal = any("萨姆规则" in s["name"] for s in self.signals)
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
                c4_triggered = tips_rising and tips > 1.8 and vix < 20
        self.combos.append({
            "name": "TIPS飙升+VIX平稳",
            "triggered": c4_triggered,
            "detail": "静默杀估值" if c4_triggered else ""
        })

        # Combo 5: VIX low + SKEW high
        skew = g.get("SKEW")
        c5_triggered = False
        if skew is not None and vix is not None:
            c5_triggered = skew > 140 and vix < 18
        self.combos.append({
            "name": "VIX低+SKEW高",
            "triggered": c5_triggered,
            "detail": "暴风雨前的宁静" if c5_triggered else ""
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
        s = self.risk_score
        if s <= 0:
            return "低风险 (Risk-On)"
        elif s <= 30:
            return "中低风险"
        elif s <= 50:
            return "中等风险"
        elif s <= 70:
            return "高风险 (Risk-Off)"
        else:
            return "极高风险"

    # ------------------------------------------------------------------
    # Market phase detection
    # ------------------------------------------------------------------

    def _detect_phase(self):
        g = self.indicators
        phases = []

        vix = g.get("VIX") or 0
        dxy = g.get("DXY") or 0
        sahm = g.get("SAHM") or 0
        tips = g.get("TIPS") or 0
        spy = g.get("SPY") or 0
        spy_ma200 = g.get("SPY_MA200") or 0

        # Risk-Off
        if vix > 30 and dxy > 103:
            phases.append("风险规避 (Risk-Off)")

        # Recession
        if sahm >= 0.5 or any("萨姆规则" in s["name"] for s in self.signals):
            phases.append("衰退交易")
        elif any("解倒挂" in s["name"] for s in self.signals):
            phases.append("衰退交易")

        # AI/Growth Bull
        sox_strong = any("SOX站稳50日均线" in s["name"] for s in self.signals)
        leaders_ok = sum(1 for lh in self.leader_health if lh["status"] == "safe") >= 4
        if sox_strong and leaders_ok and spy > spy_ma200:
            phases.append("AI成长牛市")

        # Liquidity Bull
        us10y_s = self.f.get_series("US10Y")
        us10y_falling = False
        if us10y_s is not None and len(us10y_s) >= 20:
            us10y_falling = float(us10y_s.iloc[-1]) < float(us10y_s.iloc[-20])
        if us10y_falling and tips < 1.5 and spy > spy_ma200:
            phases.append("流动性牛市")

        if not phases:
            if spy > spy_ma200:
                phases.append("标准牛市")
            else:
                phases.append("震荡/调整")

        return " / ".join(phases)

    # ------------------------------------------------------------------
    # Recommendation
    # ------------------------------------------------------------------

    def _recommendation(self):
        g = self.indicators
        score = self.risk_score

        vix = g.get("VIX") or 0
        vxn = g.get("VXN") or 0
        spy = g.get("SPY") or 0
        spy_ma200 = g.get("SPY_MA200") or 1
        qqq = g.get("QQQ") or 0
        qqq_ma200 = g.get("QQQ_MA200") or 1
        rsi = g.get("QQQ_RSI") or 50
        fg = g.get("FEAR_GREED") or 50
        sahm = g.get("SAHM") or 0

        # Stage 5: Strong Sell
        strong_sell_conds = [
            any("解倒挂" in s["name"] for s in self.signals),
            sahm >= 0.5,
            any("PMI" in s.get("name", "") and s["level"] == "danger" for s in self.signals),
            any("死叉" in s["name"] for s in self.signals),
            qqq < qqq_ma200,
        ]
        if sum(strong_sell_conds) >= 3:
            return ("强烈卖出", "系统性风险极高，建议减仓至20%以下，可配置TLT对冲")

        # Stage 1: Strong Buy
        strong_buy_conds = [
            vix > 35 or vxn > 40,
            rsi < 30 or fg < 15,
            pct_above(spy, spy_ma200) is not None and abs(pct_above(spy, spy_ma200)) < 5,
            any("US10Y" in s["name"] and "回落" in s["name"] for s in self.signals),
        ]
        if sum(strong_buy_conds) >= 3:
            return ("强烈买入", "极端恐慌+超卖，分批重仓买入（3-5批，间隔1-2周）")

        # Stage 2: Gradual Buy
        if 25 <= vix <= 35 and score < 50:
            gradual_buy_conds = [
                any("TIPS" in s["name"] and "回落" in s["name"] for s in self.signals),
                any("SOX站稳" in s["name"] for s in self.signals),
                any("M2" in s["name"] and "回升" in s["name"] for s in self.signals),
            ]
            if sum(gradual_buy_conds) >= 1:
                return ("逐步买入", "宏观见底迹象，建议定投加仓，建立长线底仓")

        # Stage 4: Gradual Sell
        gradual_sell_conds = [
            any("RSI顶背离" in s["name"] for s in self.signals),
            fg > 85 if fg else False,
            any("DXY" in s["name"] and s["level"] == "danger" for s in self.signals),
            any("SOX" in s["name"] and "弱于QQQ" in s["name"] for s in self.signals),
        ]
        if sum(gradual_sell_conds) >= 3:
            return ("逐步减仓", "技术面超买，分批止盈20-30%，停止新买入")

        # Stage 3: Hold
        if score <= 30:
            return ("持有观望", "趋势健康，维持现有仓位，享受趋势收益")
        elif score <= 50:
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
            if sahm >= 0.5:
                recession_score += 2
                recession_details.append(f"萨姆规则触发 ({sahm:.2f}≥0.5)")
            elif sahm < 0.3:
                expansion_score += 1
                expansion_details.append(f"萨姆规则安全 ({sahm:.2f})")

        # 2. Unemployment trend
        unrate = g.get("UNRATE")
        unrate_trend = g.get("UNRATE_TREND")
        if unrate is not None:
            if unrate < 5 and unrate_trend == "falling":
                expansion_score += 1
                expansion_details.append(f"失业率低且下降 ({unrate:.1f}%)")
            elif unrate_trend == "rising":
                recession_score += 1
                recession_details.append(f"失业率上升趋势 ({unrate:.1f}%)")

        # 3. Yield curve
        t10y2y = g.get("T10Y2Y")
        if t10y2y is not None:
            if t10y2y > 0.5:
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
                        recession_score += 2
                        recession_details.append(f"收益率曲线刚解倒挂 ({t10y2y:.2f}%)")

        # 4. Credit spreads
        hy = g.get("HY_OAS")
        if hy is not None:
            if hy < 350:
                expansion_score += 1
                expansion_details.append(f"信用利差健康 ({hy:.0f}bp)")
            elif hy > 500:
                recession_score += 1
                recession_details.append(f"信用利差走阔 ({hy:.0f}bp)")

        # 5. Initial Claims
        icsa_avg = g.get("ICSA_4W_AVG")
        icsa_trend = g.get("ICSA_TREND")
        if icsa_avg is not None:
            if icsa_avg < 250:
                expansion_score += 1
                expansion_details.append(f"初请失业金低 ({icsa_avg:.0f}k)")
            elif icsa_avg > 300 and icsa_trend == "rising":
                recession_score += 1
                recession_details.append(f"初请失业金上升 ({icsa_avg:.0f}k)")

        # 6. Nonfarm Payrolls
        payems_avg = g.get("PAYEMS_3M_AVG")
        if payems_avg is not None:
            if payems_avg > 150:
                expansion_score += 1
                expansion_details.append(f"非农强劲 (月均+{payems_avg:.0f}k)")
            elif payems_avg < 50:
                recession_score += 1
                recession_details.append(f"非农放缓 (月均+{payems_avg:.0f}k)")
            if payems_avg < 0:
                recession_score += 1
                recession_details.append("非农转负")

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

        # 9. SPY vs MA200
        spy_pct = g.get("SPY_VS_MA200")
        if spy_pct is not None:
            if spy_pct > 0:
                expansion_score += 1
                expansion_details.append(f"SPY在MA200上方 (+{spy_pct:.1f}%)")
            else:
                recession_score += 1
                recession_details.append(f"SPY跌破MA200 ({spy_pct:.1f}%)")

        # 10. XLY/XLU sector rotation
        xly_s = self.f.get_series("XLY")
        xlu_s = self.f.get_series("XLU")
        if xly_s is not None and xlu_s is not None and len(xly_s) >= 20 and len(xlu_s) >= 20:
            ratio_now = float(xly_s.iloc[-1] / xlu_s.iloc[-1])
            ratio_20d = float(xly_s.iloc[-20] / xlu_s.iloc[-20])
            if ratio_now > ratio_20d:
                expansion_score += 1
                expansion_details.append("板块轮动偏进攻 (XLY>XLU)")
            else:
                recession_score += 1
                recession_details.append("板块轮动偏防御 (XLU>XLY)")

        # Determine inflation level
        cpi_yoy = g.get("CPI_YOY")
        inflation_high = cpi_yoy is not None and cpi_yoy > 4.0
        inflation_moderate = cpi_yoy is not None and 2.5 < cpi_yoy <= 4.0
        inflation_label = "N/A"
        if cpi_yoy is not None:
            if cpi_yoy > 4.0:
                inflation_label = f"高通胀 ({cpi_yoy:.1f}%)"
            elif cpi_yoy > 2.5:
                inflation_label = f"温和通胀 ({cpi_yoy:.1f}%)"
            else:
                inflation_label = f"低通胀 ({cpi_yoy:.1f}%)"

        # Determine cycle phase
        if recession_score >= 5 and inflation_high:
            cycle = "stagflation"
            cycle_cn = "滞胀期 (Stagflation)"
            cycle_desc = "经济增长停滞但通胀高企，最难赚钱的阶段"
        elif recession_score >= 5:
            cycle = "recession"
            cycle_cn = "衰退期 (Recession)"
            cycle_desc = "经济收缩，保住本金优先，等待底部抄底机会"
        elif recession_score >= 3 and inflation_high:
            cycle = "late_stagflation"
            cycle_cn = "滞胀前期 (Pre-Stagflation)"
            cycle_desc = "通胀高企且经济出现放缓迹象，需要提高防御"
        elif recession_score >= 3 and expansion_score <= 4:
            cycle = "late_cycle"
            cycle_cn = "周期末期 (Late Cycle)"
            cycle_desc = "扩张晚期，多项衰退预警出现，逐步转向防御"
        elif expansion_score >= 7:
            cycle = "expansion"
            cycle_cn = "扩张期 (Expansion)"
            cycle_desc = "经济稳健增长，正常持有风险资产"
        elif expansion_score >= 5 and recession_score <= 2:
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
        }

    def _cycle_allocation(self, cycle, inflation_high):
        allocations = {
            "recovery": {
                "stocks": ("40-50%", "QQQM(0.15%)/VUG(0.04%) 30%, AVUV(0.25%)/VBR(0.07%) 10%, VNQ(0.12%) 5%"),
                "long_bonds": ("15-20%", "VGLT(0.04%) / DTLA(UCITS 0.07%)"),
                "cash": ("5-10%", "SGOV(0.09%) / IB01(UCITS 0.07%)"),
                "gold": ("5-10%", "IAUM(0.09%) / SGLN(UCITS 0.12%)"),
                "tips": ("10%", "SCHP(0.03%)"),
                "commodities": ("10%", "PDBC(0.59%)"),
            },
            "expansion": {
                "stocks": ("35-40%", "VOO(0.03%)/QQQM(0.15%) 30%, VXUS(0.05%) 5%, XLV(0.09%) 5%"),
                "long_bonds": ("15%", "VGLT(0.04%) / DTLA(UCITS 0.07%)"),
                "cash": ("10-15%", "SGOV(0.09%) / IB01(UCITS 0.07%)"),
                "gold": ("10%", "IAUM(0.09%) / SGLN(UCITS 0.12%)"),
                "tips": ("10%", "SCHP(0.03%)"),
                "commodities": ("10%", "PDBC(0.59%)"),
            },
            "late_cycle": {
                "stocks": ("25-30%", "XLV/XLP 15%, VOO(0.03%) 10%, XLE 5%"),
                "long_bonds": ("10-15%", "VGLT(0.04%) / DTLA(UCITS 0.07%)"),
                "cash": ("20-25%", "SGOV(0.09%) + USFR(0.15%,加息期)"),
                "gold": ("15-20%", "IAUM(0.09%) / SGLN(UCITS 0.12%)"),
                "tips": ("10-15%", "SCHP(0.03%)"),
                "commodities": ("10%", "PDBC(0.59%)"),
            },
            "stagflation": {
                "stocks": ("10-15%", "XLU/XLV/XLP 10%, XLE 5%"),
                "long_bonds": ("0-5%", "加息期长债暴跌，极低配置"),
                "cash": ("25-30%", "SGOV(0.09%) + USFR(0.15%,浮动利率优先)"),
                "gold": ("20-25%", "IAUM(0.09%) / SGLN(UCITS 0.12%) — 滞胀期最优资产"),
                "tips": ("15%", "SCHP(0.03%) — 通胀保护"),
                "commodities": ("15%", "PDBC(0.59%)"),
            },
            "late_stagflation": {
                "stocks": ("15-20%", "XLU/XLV/XLP 10%, XLE 5%"),
                "long_bonds": ("5-10%", "VGLT(0.04%) / DTLA(UCITS 0.07%)"),
                "cash": ("20-25%", "SGOV(0.09%) + USFR(0.15%)"),
                "gold": ("20%", "IAUM(0.09%) / SGLN(UCITS 0.12%)"),
                "tips": ("15%", "SCHP(0.03%)"),
                "commodities": ("10-15%", "PDBC(0.59%)"),
            },
            "recession": {
                "stocks": ("10-15%", "XLV/XLP 10%, SCHD(0.06%) 5% (仅底仓)"),
                "long_bonds": ("25-35%", "VGLT(0.04%)/EDV(0.06%) / DTLA(UCITS 0.07%) — 衰退期最优资产"),
                "cash": ("25-30%", "SGOV(0.09%) — 抄底弹药"),
                "gold": ("10-15%", "IAUM(0.09%) / SGLN(UCITS 0.12%)"),
                "tips": ("5%", "SCHP(0.03%)"),
                "commodities": ("5%", "PDBC(0.59%)"),
            },
            "transition": {
                "stocks": ("30%", "VOO(0.03%)/VTI(0.03%) 25%, XLV 5%"),
                "long_bonds": ("20%", "VGLT(0.04%) / DTLA(UCITS 0.07%)"),
                "cash": ("15%", "SGOV(0.09%)"),
                "gold": ("15%", "IAUM(0.09%) / SGLN(UCITS 0.12%)"),
                "tips": ("10%", "SCHP(0.03%)"),
                "commodities": ("10%", "PDBC(0.59%)"),
            },
        }
        return allocations.get(cycle, allocations["transition"])

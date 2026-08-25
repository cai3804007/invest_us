import os

FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
SERPAPI_API_KEYS = os.environ.get("SERPAPI_API_KEYS", "")
TAVILY_API_KEYS = os.environ.get("TAVILY_API_KEYS", "")
SERVERCHAN3_SENDKEY = os.environ.get("SERVERCHAN3_SENDKEY", "")

# Gemini model. Use a floating alias so a retired point-release does not
# silently disable the AI section (gemini-2.0-flash broke exactly that way).
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")

# Optional prefix for the push title, e.g. "日报" / "周期". Set by CI.
REPORT_TYPE_LABEL = os.environ.get("REPORT_TYPE_LABEL", "")

YAHOO_TICKERS = {
    "SPX": "^GSPC",
    "NDX": "^NDX",
    "DJI": "^DJI",
    "SPY": "SPY",
    "QQQ": "QQQ",
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
    # Long Treasuries — needed to test whether bonds are still hedging
    # equities, which the whole 永久组合 premise depends on.
    "TLT": "TLT",
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
    # Real GDP level — YoY is derived from this to match the spec's "GDP同比".
    "GDP": "GDPC1",
    # Fed policy: target upper bound. Dovishness is inferred from cuts and
    # from US2Y trading below the target (i.e. the market pricing cuts).
    "FED_UPPER": "DFEDTARU",
    # ISM manufacturing PMI was withdrawn from FRED (series NAPM no longer
    # exists). These three regional Fed manufacturing surveys are averaged
    # into a PMI proxy — see PMI_PROXY_SERIES / PMI_LEVELS.
    "PMI_NY": "GACDISA066MSFRBNY",
    "PMI_PHI": "GACDFSA066MSFRBPHI",
    "PMI_DAL": "BACTSAMFRBDAL",
    # 10Y breakeven. Nominal = real + breakeven, so this is the missing third
    # leg: it separates "rates up because inflation expectations rose" from
    # "rates up because the real discount rate repriced" — very different for
    # equity multiples, and previously indistinguishable here.
    "BREAKEVEN": "T10YIE",
    # Fed balance sheet and overnight reverse repo. spec 1.2 names ON RRP
    # explicitly; liquidity was proxied only by M2, which is monthly, lagging
    # and a weak read post-2020.
    "FED_ASSETS": "WALCL",
    "ON_RRP": "RRPONTSYD",
}

# Averaged into one diffusion index. NOTE: these are diffusion indices centred
# on 0, not the 50-centred ISM scale. No conversion is applied — inventing a
# regression to fake "PMI = 47.3" would be false precision. Thresholds below
# are stated on the native scale, with the ISM equivalent noted for reading.
PMI_PROXY_SERIES = ["PMI_NY", "PMI_PHI", "PMI_DAL"]

# ------------------------------------------------------------------
# Valuation and cross-asset context.
#
# These are deliberately NOT scored into the risk total. Valuation is a poor
# short-horizon timing signal — expensive markets stay expensive for years —
# so folding it into a daily risk score would add noise and would also
# invalidate the band calibration. It is surfaced as context and used to
# temper position-add conviction instead.
# ------------------------------------------------------------------
VALUATION_LEVELS = {
    "ERP_THIN": 0.0,        # 盈利收益率 - 10Y名义 < 0: 股票收益率低于无风险利率
    "ERP_RICH": 2.0,        # > 2%: 股票相对债券有明显补偿
    "PE_HIGH": 25.0,
    "PE_EXTREME": 30.0,
}

# Rolling stock/bond correlation. Positive means long bonds are no longer
# hedging equities, which undercuts the permanent-portfolio diversification
# assumption behind the cycle allocation table.
CORR_WINDOW = 120
CORR_LEVELS = {
    "HEDGE_BROKEN": 0.2,    # > 0.2: 对冲效果显著削弱
    "HEDGE_GOOD": -0.2,     # < -0.2: 正常负相关，对冲有效
}

# ------------------------------------------------------------------
# SKEW is graded by its own trailing distribution rather than a fixed level.
# The document's 140 threshold was crossed on 1.3% of sessions in 2010-2015
# but 55.7% in 2021-2026 (median 141.5), so a fixed number no longer
# discriminates. Market microstructure drift — 0DTE volume, dealer
# positioning — moves the whole distribution, so the percentile is the
# stable formulation.
# ------------------------------------------------------------------
SKEW_LOOKBACK = 504          # ~2 交易年
SKEW_PCTILE_HIGH = 0.80
SKEW_PCTILE_EXTREME = 0.95

PMI_LEVELS = {
    "CONTRACTION": 0.0,     # 0 = 荣枯线, 对应 ISM PMI 50
    "DEEP": -20.0,          # 深度收缩, 大致对应 ISM PMI 45 以下
}

# ------------------------------------------------------------------
# FRED unit normalisation
#
# FRED publishes each series in its own native unit, which does not always
# match the unit the rest of this codebase reasons in. Scaling once at fetch
# time keeps every downstream comparison and every printed label honest.
#
#   HY_OAS (BAMLH0A0HYM2) is published in Percent (e.g. 2.73). The signal
#     thresholds and all display labels are in basis points -> x100.
#   ICSA is published as a raw person count (e.g. 204000). The cycle
#     thresholds and the "k" suffix are in thousands -> x0.001.
# ------------------------------------------------------------------
FRED_SCALE = {
    "HY_OAS": 100.0,
    "ICSA": 0.001,
}

# ~3 years. Needs to cover MA250 with history to spare, plus the 50-week
# moving average used for the weekly death cross (spec 阶段5).
LOOKBACK_CALENDAR_DAYS = 1100
MA50 = 50
MA200 = 200
MA250 = 250
RSI_PERIOD = 14
TRADING_DAYS_YEAR = 252

# Weekly moving averages for the spec's 周线死叉 (21周线跌破50周线).
MA_WEEKS_FAST = 21
MA_WEEKS_SLOW = 50

# ------------------------------------------------------------------
# Data-quality gate
#
# Without these series the analyzer cannot form an opinion. A run that is
# missing them must say so rather than reporting the resulting empty signal
# set as "low risk".
# ------------------------------------------------------------------
CRITICAL_SERIES = ["SPY", "QQQ", "VIX"]
CRITICAL_DERIVED = ["SPY_MA200", "QQQ_MA200"]

# Missing these degrades the macro/cycle read but still allows a verdict.
MACRO_SERIES = ["SAHM", "T10Y2Y", "HY_OAS"]

# ------------------------------------------------------------------
# Up/down colour convention for the market-overview section.
#   "us" -> green = up, red = down (Western convention)
#   "cn" -> red = up, green = down (A-share convention)
# Applies to both the terminal dashboard and the Markdown report so the two
# outputs can never disagree about what green means.
# ------------------------------------------------------------------
UP_COLOR_CONVENTION = os.environ.get("UP_COLOR_CONVENTION", "us")

# ------------------------------------------------------------------
# Indicator grading thresholds — the single source of truth shared by the
# analyzer's signal triggers and both renderers' status icons.
#
# Format: name -> (direction, warn, danger)
#   "high_bad"   value >= danger -> danger, >= warn -> warning
#   "low_bad"    value <= danger -> danger, <= warn -> warning
#   "two_sided"  warn/danger are (low, high) pairs; outside danger -> danger
# ------------------------------------------------------------------
THRESHOLDS = {
    "US10Y": ("high_bad", 4.0, 4.5),
    "US2Y": ("high_bad", 4.5, 5.0),
    "TIPS": ("high_bad", 1.5, 2.0),
    "DXY": ("high_bad", 103.0, 105.0),
    "HY_OAS": ("high_bad", 350.0, 500.0),          # basis points
    "M2_YOY": ("low_bad", 2.0, 0.0),
    "VIX": ("high_bad", 20.0, 25.0),
    "VXN": ("high_bad", 25.0, 30.0),
    "VIX_TERM": ("high_bad", 0.95, 1.0),
    "SAHM": ("high_bad", 0.3, 0.5),
    "T10Y2Y": ("low_bad", 0.2, 0.0),
    "RSP_SPY_20D_CHG": ("low_bad", -0.5, -2.0),
    "SPY_VS_MA200": ("low_bad", 2.0, 0.0),
    "QQQ_VS_MA200": ("low_bad", 2.0, 0.0),
    "FEAR_GREED": ("two_sided", (20.0, 80.0), (15.0, 85.0)),
    "SPY_RSI": ("two_sided", (30.0, 70.0), (20.0, 80.0)),
    "QQQ_RSI": ("two_sided", (30.0, 70.0), (20.0, 80.0)),
    "PMI_PROXY": ("low_bad", 0.0, -20.0),      # 0 = 荣枯线
    "GDP_YOY": ("low_bad", 2.0, 0.0),
}


def threshold(name, kind="danger"):
    """Look up a single grading level, so the analyzer and the renderers can
    never drift apart on what counts as dangerous."""
    spec = THRESHOLDS.get(name)
    if spec is None:
        raise KeyError(f"no threshold configured for {name}")
    return spec[1] if kind == "warn" else spec[2]


def grade(name, value):
    """Grade a value as 'safe' / 'warning' / 'danger', or None if unavailable."""
    if value is None:
        return None
    spec = THRESHOLDS.get(name)
    if spec is None:
        return "safe"
    direction, warn, danger = spec
    if direction == "high_bad":
        if value >= danger:
            return "danger"
        return "warning" if value >= warn else "safe"
    if direction == "low_bad":
        if value <= danger:
            return "danger"
        return "warning" if value <= warn else "safe"
    if direction == "two_sided":
        low_w, high_w = warn
        low_d, high_d = danger
        if value <= low_d or value >= high_d:
            return "danger"
        return "warning" if (value <= low_w or value >= high_w) else "safe"
    return "safe"


# ------------------------------------------------------------------
# Analyzer-only signal levels that are not simple indicator grades
# (rates of change, combination gates, relative strength).
# ------------------------------------------------------------------
SIGNAL_LEVELS = {
    "DXY_WEEK_SURGE_PCT": 2.0,
    "TIPS_FALL_DELTA": -0.1,
    "HY_OAS_WEEK_WIDEN_BP": 50.0,
    "M2_CONTRACT_YOY": -1.0,
    "VIX_CALM_FOR_SKEW": 20.0,
    "VIX_CALM_FOR_TIPS": 20.0,
    "TIPS_QUIET_KILL": 1.8,
    "VIX_QUIET_STORM": 18.0,
    "FG_EXTREME_FEAR": 15.0,
    "FG_GREED": 85.0,
    "FG_POSITION_FEAR": 20.0,
    "SOX_QQQ_DIVERGE_PCT": -3.0,
    "BREADTH_SPY_RET_PCT": 2.0,
    "BREADTH_RSP_CHG_PCT": -1.0,
    "XLY_XLU_DEFENSIVE_RATIO": 0.97,
    "WEAK_LEADERS_COUNT": 3,
    "MA200_BREAK_DAYS": 3,        # spec「无法快速收回」: 跌破需连续保持 3 日
    "LEADER_VOLUME_SPIKE": 1.5,   # 放量: 成交量 >= 50日均量的 1.5 倍
    "FED_DOVISH_GAP": -0.5,       # US2Y 低于政策利率 50bp 以上 = 市场抢跑降息
    "CPI_HIGH_YOY": 4.0,
    "CPI_MODERATE_YOY": 2.5,
}

# ------------------------------------------------------------------
# Position-adding / reducing indicator targets
# ------------------------------------------------------------------
POSITION_TARGETS = {
    "QQQM": {
        "ticker": "QQQM",         # Yahoo Finance ticker for data
        "label": "QQQM (纳指100)",
        "benchmark_vix": "VXN",   # corresponding volatility index
    },
    "SPYM": {
        "ticker": "SPY",          # SPYM tracks S&P 500; use SPY data
        "label": "SPYM (标普500)",
        "benchmark_vix": "VIX",
    },
}

# ------------------------------------------------------------------
# Asset-class presentation, shared by the dashboard, the Markdown report
# and the AI prompt builder.
# ------------------------------------------------------------------
ASSET_CLASSES = ["stocks", "long_bonds", "cash", "gold", "tips", "commodities"]

ASSET_LABELS = {
    "stocks": "股票",
    "long_bonds": "长期国债",
    "cash": "现金/短债",
    "gold": "黄金",
    "tips": "TIPS通胀保护",
    "commodities": "大宗商品",
}

ASSET_EMOJI = {
    "stocks": "📈",
    "long_bonds": "🏛️",
    "cash": "💵",
    "gold": "🥇",
    "tips": "🛡️",
    "commodities": "🛢️",
}

# ------------------------------------------------------------------
# Economic-cycle presentation, shared by both renderers.
# ------------------------------------------------------------------
CYCLE_EMOJI = {
    "recovery": "🌱",
    "expansion": "☀️",
    "late_cycle": "🌤️",
    "late_stagflation": "🌧️",
    "stagflation": "🔥",
    "recession": "❄️",
    "transition": "🔄",
}

CYCLE_STYLES = {
    "recovery": "bold green",
    "expansion": "green",
    "late_cycle": "yellow",
    "late_stagflation": "bold yellow",
    "stagflation": "bold red",
    "recession": "bold red",
    "transition": "cyan",
}

# key, name, economic features, best assets, worst assets
CYCLE_REFERENCE = [
    ("recovery", "复苏期",
     "GDP转正，失业率见顶回落，央行维持宽松，通胀低位",
     "成长股、小盘股", "现金"),
    ("expansion", "扩张期",
     "GDP稳健(2-4%)，就业持续改善，通胀温和上升",
     "大盘股、大宗商品", "长期国债"),
    ("late_cycle", "周期末期",
     "增长放缓，通胀升温，央行收紧，领先指标转弱",
     "防御板块、黄金", "成长股"),
    ("stagflation", "滞胀期",
     "经济停滞+高通胀，央行被迫加息，利润率受挤压",
     "黄金、大宗商品、TIPS", "股票、长期国债"),
    ("recession", "衰退期",
     "GDP负增长，失业飙升，央行紧急降息/QE",
     "长期国债、现金", "股票、大宗商品"),
    ("transition", "过渡期",
     "信号混合，扩张与衰退指标共存，方向不明",
     "均衡配置", "避免集中持仓"),
]


# ==================================================================
# Signal registry
#
# Every scored signal is declared here with a stable id. Three problems this
# solves:
#
#   1. Decision logic used to match signals by Chinese substring
#      (`"解倒挂" in s["name"]`). Renaming a signal silently disabled the
#      condition that depended on it — exactly how the PMI condition in
#      阶段5 died unnoticed. Conditions now match on id.
#   2. The risk bands were calibrated against the strategy document's
#      ±200/±110 scale, but the implementation drifted to +260/-65. With
#      every weight declared in one table, the attainable range is computed
#      rather than assumed, and the bands scale with it.
#   3. Several document rows are "A 或 B" (one score for either condition),
#      e.g. 「VIX > 25 或 VXN > 30 +10」. The code fired both and scored +20.
#      `group` marks those rows: at most one signal per group may fire, and
#      the attainable maximum counts the group once.
#
# Fields: score, level, name, source, group
#   source "spec" = listed in 《美股综合交易策略》四、风险评分系统
#          "ext"  = extension not in that table (kept, but visible as such)
# ==================================================================
def _sig(score, level, name, source, group=None):
    return {"score": score, "level": level, "name": name,
            "source": source, "group": group}


SIGNALS = {
    # --- 流动性 ---
    # spec row: 「US10Y连续5日上涨或突破关键位 +10」 -> one score, either way
    "US10Y_STREAK_UP":    _sig(10,  "danger",  "US10Y连续5日上涨", "spec", "US10Y_RISK"),
    "US10Y_HIGH":         _sig(10,  "danger",  "US10Y处于高位", "spec", "US10Y_RISK"),
    "US10Y_FALLING":      _sig(-10, "safe",    "US10Y近期持续回落", "spec"),
    # rho(US10Y, TIPS) = 0.945 on levels — nominal and real 10Y are one rate
    # factor here, so they share a group rather than scoring +20 together.
    "TIPS_RISING":        _sig(10,  "danger",  "TIPS实际利率走高", "spec", "US10Y_RISK"),
    "TIPS_FALLING":       _sig(-10, "safe",    "TIPS实际利率回落", "spec"),
    # spec row: 「DXY上涨且 > 105 +10」 -> level and weekly surge share one score
    "DXY_BREAKOUT":       _sig(10,  "danger",  "DXY突破关键位", "spec", "USD_VOL_RISK"),
    "DXY_WEEK_SURGE":     _sig(10,  "danger",  "DXY单周暴涨", "spec", "USD_VOL_RISK"),
    "HY_OAS_WIDENING":    _sig(10,  "danger",  "HY OAS利差急剧走阔", "spec"),
    "HY_OAS_HIGH":        _sig(10,  "danger",  "HY OAS信用利差处于高位", "ext"),
    "M2_REBOUND":         _sig(-10, "safe",    "M2货币供应增速回升", "spec"),
    "M2_CONTRACTING":     _sig(5,   "warning", "M2货币供应萎缩", "ext"),
    "FED_DOVISH":         _sig(-15, "safe",    "美联储转鸽/降息预期升温", "spec"),

    # --- 情绪 ---
    # spec row: 「VIX > 25 或 VXN > 30 +10」 -> one score for either
    "VIX_RISK":           _sig(10,  "danger",  "VIX进入风险区间", "spec", "VOL_RISK"),
    "VXN_RISK":           _sig(10,  "danger",  "VXN进入风险区间", "spec", "VOL_RISK"),
    "VIX_TERM_INVERTED":  _sig(10,  "danger",  "VIX期限结构倒挂", "spec"),
    "SKEW_HIGH_VIX_LOW":  _sig(5,   "warning", "SKEW高+VIX低: 暗流涌动", "spec", "SKEW_RISK"),
    "SKEW_EXTREME":       _sig(5,   "warning", "SKEW极端: 尾部风险焦虑", "ext", "SKEW_RISK"),
    "EXTREME_FEAR":       _sig(0,   "safe",    "极度恐惧", "ext"),
    "EXTREME_GREED":      _sig(5,   "warning", "极度贪婪", "ext"),

    # --- 领先指标 ---
    "SOX_BELOW_MA50":     _sig(15,  "danger",  "SOX跌破50日均线", "spec"),
    "SOX_ABOVE_MA50":     _sig(-10, "safe",    "SOX站稳50日均线上方", "spec"),
    "SOX_WEAKER_QQQ":     _sig(10,  "danger",  "SOX明显弱于QQQ", "spec"),
    "BREADTH_BAD":        _sig(10,  "danger",  "市场广度恶化", "spec"),
    "BREADTH_GOOD":       _sig(-10, "safe",    "市场广度健康", "spec"),
    "SECTOR_DEFENSIVE":   _sig(5,   "warning", "板块轮动: 资金转向防御", "ext"),
    "LEADERS_WEAK":       _sig(15,  "danger",  "多数龙头股走弱", "spec"),

    # --- 宏观 ---
    "SAHM_TRIGGERED":     _sig(20,  "danger",  "萨姆规则已触发!", "spec"),
    "CURVE_UNINVERT":     _sig(15,  "danger",  "收益率曲线刚解倒挂!", "spec"),
    "PMI_CONTRACTING":    _sig(10,  "danger",  "制造业景气跌破荣枯线且下行", "spec"),
    "PMI_TROUGH_UP":      _sig(-15, "safe",    "制造业景气见底拐头向上", "spec"),

    # --- 技术面 ---
    # rho(SPY, QQQ) = 0.948; when one breaks MA200 the other does so 95% of
    # the time. One trend break, one score.
    "SPY_BELOW_MA200":    _sig(10,  "danger",  "SPY跌破200日均线", "ext", "INDEX_MA200"),
    "QQQ_BELOW_MA200":    _sig(10,  "danger",  "QQQ跌破200日均线", "ext", "INDEX_MA200"),
    "SPY_GOLDEN_CROSS":   _sig(-10, "safe",    "SPY金叉（MA50上穿MA200）", "ext"),
    "SPY_DEATH_CROSS":    _sig(10,  "danger",  "SPY死叉（MA50下穿MA200）", "ext"),
    "RSI_BEAR_DIV":       _sig(5,   "warning", "QQQ出现RSI顶背离", "spec"),
    "RSI_BULL_DIV":       _sig(-5,  "safe",    "QQQ出现RSI底背离", "ext"),

    # --- 组合 ---
    # Shares the group with its own components: the conjunction escalates the
    # score to +15 instead of adding +15 on top of their +20.
    "COMBO_DXY_VIX":      _sig(15,  "danger",  "高危组合: DXY+VIX同时上涨", "spec", "USD_VOL_RISK"),
}


def signal_meta(signal_id):
    try:
        return SIGNALS[signal_id]
    except KeyError:
        raise KeyError(f"unknown signal id: {signal_id!r}") from None


def _score_span(source=None):
    """Maximum attainable positive / negative total, counting each exclusivity
    group only once (its largest member)."""
    items = [v for v in SIGNALS.values() if source is None or v["source"] == source]
    pos = sum(v["score"] for v in items if v["score"] > 0 and not v["group"])
    neg = sum(v["score"] for v in items if v["score"] < 0 and not v["group"])
    groups = {}
    for v in items:
        if v["group"]:
            groups.setdefault(v["group"], []).append(v["score"])
    for scores in groups.values():
        hi, lo = max(scores), min(scores)
        if hi > 0:
            pos += hi
        if lo < 0:
            neg += lo
    return pos, neg


MAX_RISK_POSITIVE, MAX_RISK_NEGATIVE = _score_span()
SPEC_RISK_POSITIVE, SPEC_RISK_NEGATIVE = _score_span("spec")

# The document's bands (≤0 / 30 / 50 / 70) sit at these fractions of its own
# +200 ceiling. Holding the fractions fixed keeps the calibration intact as
# signals are added or removed.
RISK_BAND_FRACTIONS = [0.15, 0.25, 0.35]

RISK_BANDS = [round(f * MAX_RISK_POSITIVE) for f in RISK_BAND_FRACTIONS]

# ------------------------------------------------------------------
# Economic-cycle scoring — thresholds and gates from
# 《经济周期长期投资策略》三、3.3 周期识别综合评分卡
# ------------------------------------------------------------------
CYCLE_LEVELS = {
    "UNRATE_LOW": 6.0,          # spec: 失业率低于6%且下降趋势
    "GDP_YOY_STRONG": 2.0,      # spec: GDP同比增速 > 2%
    "PAYEMS_STRONG": 150.0,     # spec: 非农每月 > 15万
    "PAYEMS_WEAK": 50.0,
    "CURVE_NORMAL": 0.5,        # spec: 收益率曲线利差 > 0.5%
    "HY_OAS_HEALTHY": 400.0,    # spec: 信用利差 < 400bp
    "HY_OAS_STRESS": 500.0,     # spec: 信用利差 > 500bp 且走阔
    "ICSA_LOW": 250.0,          # spec: 初次申请失业金 < 25万
    "ICSA_HIGH": 300.0,         # spec: 4周均值 > 30万且上升
    "SAHM_SAFE": 0.3,
}

# spec 判断规则: 扩张≥7 且 衰退≤2 -> 扩张期
#                扩张≤3 且 衰退≥6 -> 衰退期
#                其余             -> 过渡期
CYCLE_GATES = {
    "EXPANSION_MIN": 7,
    "EXPANSION_MAX_RECESSION": 2,
    "RECESSION_MIN": 6,
    "RECESSION_MAX_EXPANSION": 3,
    # Middle band, used to place the extra phases the allocation table needs
    # (周期末期 / 滞胀前期) inside the spec's 过渡期 zone.
    "MID_RECESSION_MIN": 4,
    "MID_EXPANSION_MAX": 4,
}

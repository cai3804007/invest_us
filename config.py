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

LOOKBACK_CALENDAR_DAYS = 500
MA50 = 50
MA200 = 200
RSI_PERIOD = 14
TRADING_DAYS_YEAR = 252

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
    "SKEW": ("high_bad", 140.0, 150.0),
    "VIX_TERM": ("high_bad", 0.95, 1.0),
    "SAHM": ("high_bad", 0.3, 0.5),
    "T10Y2Y": ("low_bad", 0.2, 0.0),
    "RSP_SPY_20D_CHG": ("low_bad", -0.5, -2.0),
    "SPY_VS_MA200": ("low_bad", 2.0, 0.0),
    "QQQ_VS_MA200": ("low_bad", 2.0, 0.0),
    "FEAR_GREED": ("two_sided", (20.0, 80.0), (15.0, 85.0)),
    "SPY_RSI": ("two_sided", (30.0, 70.0), (20.0, 80.0)),
    "QQQ_RSI": ("two_sided", (30.0, 70.0), (20.0, 80.0)),
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
    "SKEW_QUIET_STORM": 140.0,
    "VIX_QUIET_STORM": 18.0,
    "FG_EXTREME_FEAR": 15.0,
    "FG_GREED": 85.0,
    "FG_POSITION_FEAR": 20.0,
    "SOX_QQQ_DIVERGE_PCT": -3.0,
    "BREADTH_SPY_RET_PCT": 2.0,
    "BREADTH_RSP_CHG_PCT": -1.0,
    "XLY_XLU_DEFENSIVE_RATIO": 0.97,
    "WEAK_LEADERS_COUNT": 3,
    "RECESSION_SCORE_GATE": 5,
    "EXPANSION_SCORE_GATE": 7,
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

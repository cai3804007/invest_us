from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.columns import Columns

from config import (grade, ASSET_CLASSES, ASSET_LABELS, ASSET_EMOJI,
                    CYCLE_EMOJI, CYCLE_STYLES, CYCLE_REFERENCE,
                    UP_COLOR_CONVENTION, RISK_BANDS, MAX_RISK_POSITIVE,
                    CORR_WINDOW, CORR_LEVELS, VALUATION_LEVELS)


def _status_icon(level):
    if level == "danger":
        return "[bold red]●[/]"
    elif level == "warning":
        return "[bold yellow]●[/]"
    elif level == "safe":
        return "[bold green]●[/]"
    return "[dim]○[/]"


def _md_icon(level):
    if level == "danger":
        return "🔴"
    elif level == "warning":
        return "🟡"
    elif level == "safe":
        return "🟢"
    return "⚪"


def _fmt(val, decimals=2, suffix=""):
    if val is None:
        return "[dim]N/A[/]"
    return f"{val:.{decimals}f}{suffix}"


def _md_val(val, decimals=2, suffix=""):
    if val is None:
        return "N/A"
    return f"{val:.{decimals}f}{suffix}"


# ----------------------------------------------------------------------
# Up/down presentation, driven by UP_COLOR_CONVENTION so the terminal and
# the Markdown report can never disagree about what green means. The two
# renderers previously hardcoded opposite conventions.
# ----------------------------------------------------------------------

def _up_down_color(pct):
    if pct == 0:
        return "white"
    rising = pct > 0
    if UP_COLOR_CONVENTION == "cn":
        return "red" if rising else "green"
    return "green" if rising else "red"


def _up_down_emoji(pct):
    if pct == 0:
        return "➖"
    rising = pct > 0
    if UP_COLOR_CONVENTION == "cn":
        return "🔴" if rising else "🟢"
    return "🟢" if rising else "🔴"


def _price_strings(item):
    """Format price and change consistently for both renderers."""
    chg = item["change"]
    if item["is_yield"]:
        return f"{item['price']:.2f}%", f"{chg:+.2f}"
    if item["name"] == "VIX":
        return f"{item['price']:.1f}", f"{chg:+.1f}"
    if item["price"] > 1000:
        return f"{item['price']:,.0f}", f"{chg:+,.0f}"
    return f"{item['price']:.1f}", f"{chg:+.1f}"


# ----------------------------------------------------------------------
# Indicator row specification — the single description of which indicators
# are shown, how they are labelled, and what reference text explains them.
# Status grading comes from config.grade() so the analyzer's signal triggers
# and these icons are always derived from the same thresholds.
# ----------------------------------------------------------------------

def _fmt_curve(g):
    v = g.get("T10Y2Y")
    if v is None:
        return None
    return f"{v:.2f}% ({'倒挂' if v < 0 else '正常'})"


def _fmt_vix_term(g):
    v = g.get("VIX_TERM")
    if v is None:
        return None
    return f"{'倒挂' if v > 1 else '正常'} ({v:.2f})"


def _fmt_fear_greed(g):
    v = g.get("FEAR_GREED")
    if v is None:
        return None
    label = g.get("FEAR_GREED_LABEL", "")
    return f"{v:.0f} {label}".strip()


def _fmt_cu_au(g):
    v = g.get("CU_AU")
    if v is None:
        return None
    return f"{v:.6f}" if v < 0.01 else f"{v:.4f}"


def _fmt_macd(g):
    return "多头" if g.get("SPY_MACD_BULL") else "空头"


def _fmt_skew(g):
    v = g.get("SKEW")
    if v is None:
        return None
    p = g.get("SKEW_PCTILE")
    return f"{v:.0f}" if p is None else f"{v:.0f} (近2年 {p*100:.0f}% 分位)"


def _fmt_pmi(g):
    v = g.get("PMI_PROXY")
    if v is None:
        return None
    n = g.get("PMI_PROXY_SOURCES") or 0
    trend = {"rising": "上升", "falling": "下降"}.get(g.get("PMI_TREND"), "—")
    return f"{v:+.1f} ({trend}, {n}源均值)"


def _fmt_weekly_cross(g):
    fast, slow = g.get("SPY_MA21W"), g.get("SPY_MA50W")
    if fast is None or slow is None:
        return None
    cross = g.get("SPY_WEEKLY_CROSS")
    tag = {"death": "本周死叉!", "golden": "本周金叉"}.get(cross)
    state = "多头排列" if fast > slow else "空头排列"
    return f"{state} ({fast:.0f}/{slow:.0f})" + (f" {tag}" if tag else "")


def _fmt_fed(g):
    upper = g.get("FED_UPPER")
    if upper is None:
        return None
    gap = g.get("FED_MARKET_GAP")
    if gap is None:
        return f"{upper:.2f}%"
    lean = "市场抢跑降息" if gap < -0.25 else "市场预期加息" if gap > 0.25 else "预期中性"
    return f"{upper:.2f}% (US2Y差 {gap:+.2f}%, {lean})"


def _fmt_rate_split(g):
    be, real = g.get("BREAKEVEN"), g.get("TIPS")
    if be is None or real is None:
        return None
    driver = {"real": "实际利率推动(杀估值)", "real_easing": "实际利率回落(利好估值)",
              "inflation": "通胀预期推动", "disinflation": "通胀预期回落"}.get(
                  g.get("RATE_DRIVER"), "—")
    return f"实际 {real:.2f}% + 预期 {be:.2f}% ({driver})"


def _fmt_erp(g):
    ey, erp = g.get("SPY_EY"), g.get("ERP_NOMINAL")
    if ey is None:
        return None
    pe = g.get("SPY_PE")
    if pe:
        tier = ("极高" if pe >= VALUATION_LEVELS["PE_EXTREME"]
                else "偏高" if pe >= VALUATION_LEVELS["PE_HIGH"] else "合理")
        base = f"PE {pe:.1f}({tier}) / 盈利收益率 {ey:.2f}%"
    else:
        base = f"盈利收益率 {ey:.2f}%"
    return base + (f"，减10Y {erp:+.2f}pp" if erp is not None else "")


def _fmt_corr(g):
    c = g.get("STOCK_BOND_CORR")
    if c is None:
        return None
    hi, lo = CORR_LEVELS["HEDGE_BROKEN"], CORR_LEVELS["HEDGE_GOOD"]
    verdict = "长债不对冲股票" if c > hi else "对冲有效" if c < lo else "对冲减弱"
    return f"{c:+.2f} ({CORR_WINDOW}日, {verdict})"


def _fmt_fed_liquidity(g):
    assets = g.get("FED_ASSETS")
    if assets is None:
        return None
    chg = g.get("FED_ASSETS_13W_CHG")
    rrp = g.get("ON_RRP")
    parts = [f"{assets:.2f}万亿"]
    if chg is not None:
        parts.append(f"13周{chg:+.3f}万亿 ({'扩表' if chg > 0 else 'QT缩表'})")
    if rrp is not None:
        parts.append(f"逆回购 {rrp:.0f}十亿")
    return "，".join(parts)


# Indicators whose status is not a simple threshold comparison.
GRADE_OVERRIDES = {
    "SPY_MACD_BULL": lambda g: "safe" if g.get("SPY_MACD_BULL") else "danger",
    "CURVE": lambda g: grade("T10Y2Y", g.get("T10Y2Y")),
    "SKEW": lambda g: (
        None if g.get("SKEW_PCTILE") is None
        else "danger" if g["SKEW_PCTILE"] >= 0.95
        else "warning" if g["SKEW_PCTILE"] >= 0.80 else "safe"),
    "SPY_WEEKLY_CROSS": lambda g: (
        "danger" if g.get("SPY_WEEKLY_CROSS") == "death"
        else None if g.get("SPY_MA21W") is None
        else "safe" if g.get("SPY_MA21W") > g.get("SPY_MA50W") else "warning"),
    # Informational: US2Y below the policy rate is a liquidity tailwind,
    # above it simply means no cuts are priced — not a risk in itself.
    "FED_UPPER": lambda g: (None if g.get("FED_UPPER") is None else "safe"),
    "RATE_SPLIT": lambda g: (
        None if g.get("BREAKEVEN") is None
        else "danger" if g.get("RATE_DRIVER") == "real"
        else "safe" if g.get("RATE_DRIVER") in ("real_easing", "disinflation")
        else "warning"),
    "ERP_NOMINAL": lambda g: (
        None if g.get("ERP_NOMINAL") is None
        else "danger" if g["ERP_NOMINAL"] < VALUATION_LEVELS["ERP_THIN"]
        else "safe" if g["ERP_NOMINAL"] > VALUATION_LEVELS["ERP_RICH"] else "warning"),
    "STOCK_BOND_CORR": lambda g: (
        None if g.get("STOCK_BOND_CORR") is None
        else "danger" if g["STOCK_BOND_CORR"] > CORR_LEVELS["HEDGE_BROKEN"]
        else "safe" if g["STOCK_BOND_CORR"] < CORR_LEVELS["HEDGE_GOOD"] else "warning"),
    "FED_LIQUIDITY": lambda g: (
        None if g.get("FED_ASSETS") is None
        else "safe" if (g.get("FED_ASSETS_13W_CHG") or 0) > 0 else "warning"),
}


def _row_grade(key, g):
    if key in GRADE_OVERRIDES:
        return GRADE_OVERRIDES[key](g)
    return grade(key, g.get(key))


# (key, label, decimals, suffix, formatter, reference)
INDICATOR_GROUPS = [
    ("第一层: 流动性", "💧 流动性", [
        ("US10Y", "US10Y", 2, "%", None,
         "<4.0% 利好(买) / >4.5% 压制估值(警惕) / >5.0% 强烈利空(卖)"),
        ("US2Y", "US2Y", 2, "%", None,
         "反映降息预期，快速下行=市场抢跑降息(利好)"),
        ("TIPS", "TIPS实际利率", 2, "%", None,
         "<1.5% 友好(买) / >2.0% 纳指承压(减仓)"),
        ("T10Y2Y", "10Y-2Y利差", 2, "%", _fmt_curve,
         "倒挂预示衰退 / **解倒挂快速转正=最危险(强烈卖出)**"),
        ("DXY", "DXY", 1, "", None,
         "<100 宽松(利好) / >103 偏紧 / >105 收紧(利空)"),
        ("HY_OAS", "HY OAS", 0, "bp", None,
         "<350bp 利好 / >500bp 利空 / >700bp 危机"),
        ("M2_YOY", "M2同比增速", 1, "%", None,
         ">2% 流动性充裕(利好) / <0% 萎缩(利空)"),
        ("RATE_SPLIT", "10Y拆解", 2, "", _fmt_rate_split,
         "名义=实际+通胀预期。**实际利率推动的上行才真正杀估值**"),
        ("FED_LIQUIDITY", "美联储流动性", 2, "", _fmt_fed_liquidity,
         "扩表=注入流动性 / QT缩表=抽水；逆回购余额是体系冗余流动性"),
    ]),
    ("第二层: 情绪", "😰 情绪", [
        ("VIX", "VIX", 1, "", None,
         "<20 平静 / >25 风险区间 / 25-35 关注买入 / **>35 黄金坑**"),
        ("VXN", "VXN", 1, "", None,
         "纳指专用恐慌指数 / >30 风险区间 / **>40 极端恐慌(强烈买入)**"),
        ("VIX_TERM", "VIX期限结构", 2, "", _fmt_vix_term,
         ">1倒挂=真正恐慌，比VIX绝对值更可靠"),
        ("SKEW", "SKEW", 0, "", _fmt_skew,
         "**按近2年分位数判定**（固定140已失效: 2021年后55.7%的交易日都超过）/ >80%分位+VIX低=暗流涌动"),
        ("FEAR_GREED", "恐惧贪婪指数", 0, "", _fmt_fear_greed,
         "<15 极度恐惧(配合VIX=买) / >85 贪婪(减仓)"),
    ]),
    ("第三层: 领先指标", "🔮 领先指标", [
        ("SOX", "SOX半导体", 0, "", None,
         "纳指领先指标，SOX先弱→纳指补跌"),
        ("RSP_SPY_20D_CHG", "RSP/SPY 20日", 1, "%", None,
         "下降=只有巨头撑场面(虚胖牛市)"),
        ("XLY_XLU", "XLY/XLU", 2, "", None,
         "可选消费/公用事业，下降=资金转防御"),
        ("CU_AU", "铜/金比值", 4, "", _fmt_cu_au,
         "上升=经济预期改善 / 下降=避险情绪升温"),
    ]),
    ("第四层: 宏观经济", "🏛️ 宏观经济", [
        ("SAHM", "萨姆规则", 2, "", None,
         "<0.3 安全 / **≥0.5 衰退确认(强烈卖出)**"),
        ("UNRATE", "失业率", 1, "%", None,
         "见顶回落=复苏 / 持续上升=衰退风险"),
        ("CURVE", "收益率曲线", 2, "", _fmt_curve,
         "倒挂预示衰退，解倒挂是最危险的信号"),
        ("PMI_PROXY", "制造业景气", 1, "", _fmt_pmi,
         "地区联储制造业调查均值，**0=荣枯线(对应ISM PMI 50)** / <-20 深度收缩"),
        ("GDP_YOY", "GDP同比", 1, "%", None,
         ">2% 稳健扩张 / <0% 衰退"),
        ("FED_UPPER", "联邦基金上限", 2, "%", _fmt_fed,
         "US2Y 低于政策利率=市场抢跑降息(利好流动性)"),
    ]),
    ("第六层: 估值与跨资产", "💰 估值与跨资产", [
        ("ERP_NOMINAL", "股债性价比", 2, "", _fmt_erp,
         "盈利收益率-10Y。**<0 表示股票收益率低于无风险利率(无估值保护)** / >2pp 有补偿"),
        ("STOCK_BOND_CORR", "股债相关性", 2, "", _fmt_corr,
         "永久组合假设长债对冲股票。**转正=对冲失效，债券仓位不再分散风险**"),
    ]),
    ("第五层: 技术面", "📉 技术面", [
        ("SPY_VS_MA200", "SPY vs MA200", 1, "%", None,
         ">0% 牛市(持有) / **<0% 熊市信号(减仓)**"),
        ("QQQ_VS_MA200", "QQQ vs MA200", 1, "%", None,
         "纳指趋势，跌破MA200信号更强烈"),
        ("SPY_RSI", "SPY RSI(14)", 1, "", None,
         "<30 超卖(配合VIX=买) / >70 看背离非绝对值"),
        ("QQQ_RSI", "QQQ RSI(14)", 1, "", None,
         "<30 超卖 / >70 超买，背离比绝对值更重要"),
        ("SPY_MACD_BULL", "SPY MACD", 0, "", _fmt_macd,
         "多头=趋势向上 / 空头=趋势向下"),
        ("SPY_WEEKLY_CROSS", "SPY周线21/50", 0, "", _fmt_weekly_cross,
         "**周线死叉=系统性撤退信号**(阶段5条件)，比日线死叉可靠"),
    ]),
]


def _row_value(key, decimals, suffix, formatter, g):
    if formatter is not None:
        return formatter(g)
    val = g.get(key)
    if val is None:
        return None
    return f"{val:.{decimals}f}{suffix}"


class Dashboard:

    def __init__(self, result):
        self.r = result
        self.console = Console()

    def render(self):
        self.console.print()
        self._header()
        self._data_health()
        self._market_overview()
        self._risk_summary()
        self._cycle_panel()
        self._position_panel()
        self._rebalance_panel()
        self._indicator_tables()
        self._leader_table()
        self._signals_panel()
        self._combos_panel()
        self._recommendation_panel()
        self.console.print()

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    def _header(self):
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        title = Text("📊 美股市场监控仪表盘", style="bold white")
        subtitle = Text(f"更新时间: {now}", style="dim")
        content = Text.assemble(title, "\n", subtitle)
        self.console.print(Panel(content, border_style="cyan", expand=True))

    # ------------------------------------------------------------------
    # Data health — a broken pipeline must not render as a calm market
    # ------------------------------------------------------------------

    def _data_health(self):
        health = self.r.get("data_health") or {}
        missing = health.get("missing_critical") or []
        macro_missing = health.get("missing_macro") or []
        errors = health.get("fetch_errors") or []

        if not missing and not macro_missing and not errors:
            return

        lines = []
        if missing:
            lines.append(f"[bold red]关键数据缺失: {', '.join(missing)}[/]")
            lines.append("[bold red]→ 本次不给出风险评级和操作建议（空信号 ≠ 低风险）[/]")
        if macro_missing:
            lines.append(f"[yellow]宏观数据缺失: {', '.join(macro_missing)}[/]")
        for err in errors[:8]:
            lines.append(f"[dim]• {err}[/]")
        if len(errors) > 8:
            lines.append(f"[dim]• ...另有 {len(errors) - 8} 条[/]")

        border = "red" if missing else "yellow"
        self.console.print(Panel("\n".join(lines),
                                 title="[bold]⚠️ 数据质量[/]", border_style=border))

    # ------------------------------------------------------------------
    # Market overview (today's indices)
    # ------------------------------------------------------------------

    def _market_overview(self):
        summary = self.r["indicators"].get("MARKET_SUMMARY", [])
        if not summary:
            return

        t = Table(title="📈 今日行情", show_header=True, header_style="bold cyan",
                  expand=True, show_lines=False, padding=(0, 1))
        t.add_column("指数", style="bold", min_width=8)
        t.add_column("点位", justify="right", min_width=10)
        t.add_column("涨跌", justify="right", min_width=10)
        t.add_column("涨跌幅", justify="right", min_width=8)

        for item in summary:
            pct = item["change_pct"]
            price_str, chg_str = _price_strings(item)
            color = _up_down_color(pct)
            t.add_row(item["label"], price_str,
                      f"[{color}]{chg_str}[/{color}]",
                      f"[{color}]{pct:+.2f}%[/{color}]")

        self.console.print(t)

    # ------------------------------------------------------------------
    # Risk summary
    # ------------------------------------------------------------------

    def _risk_summary(self):
        score = self.r["risk_score"]
        level = self.r["risk_level"]
        dangers = self.r.get("danger_count", 0)

        b1, b2, _ = RISK_BANDS
        if "数据不足" in level:
            style, border = "bold white on red", "red"
        elif score <= b1:
            style, border = "bold green", "green"
        elif score <= b2:
            style, border = "bold yellow", "yellow"
        else:
            style, border = "bold red", "red"

        content = Text()
        content.append("风险评分: ", style="bold")
        content.append(f"{score}", style=style)
        content.append("    等级: ", style="bold")
        content.append(level, style=style)
        content.append("    危险信号: ", style="bold")
        content.append(f"{dangers} 项", style="bold red" if dangers >= 3 else "dim")
        content.append(f"\n市场阶段: {self.r['market_phase']}", style="cyan")
        content.append(f"\n[评分区间 0~{MAX_RISK_POSITIVE}，档位 {b1}/{b2}/{RISK_BANDS[2]}]",
                       style="dim")

        self.console.print(Panel(content, title="[bold]🎯 综合评估[/]", border_style=border))

    # ------------------------------------------------------------------
    # Economic cycle
    # ------------------------------------------------------------------

    def _cycle_panel(self):
        cycle = self.r.get("economic_cycle")
        if not cycle:
            return

        style = CYCLE_STYLES.get(cycle["cycle"], "cyan")
        cpi = cycle.get("cpi_yoy")

        lines = Text()
        lines.append("经济周期: ", style="bold")
        lines.append(cycle["cycle_cn"], style=style)
        lines.append(f"\n{cycle['cycle_desc']}", style="dim")
        lines.append("\n通胀水平: ", style="bold")
        lines.append(cycle["inflation_label"],
                     style="yellow" if cpi is not None and cpi > 3 else "green")
        lines.append("\n扩张信号: ", style="bold")
        lines.append(f"{cycle['expansion_score']}/10", style="green")
        lines.append("    衰退信号: ", style="bold")
        lines.append(f"{cycle['recession_score']}/10", style="red")

        self.console.print(Panel(lines, title="[bold]🔄 经济周期判断[/]", border_style="magenta"))

        # Cycle reference table (shared definition from config)
        ct = Table(title="📖 经济周期参考", show_header=True,
                   header_style="bold cyan", expand=True, show_lines=True, padding=(0, 1))
        ct.add_column("阶段", style="bold", min_width=8)
        ct.add_column("经济特征", min_width=20)
        ct.add_column("最优资产", min_width=12)
        ct.add_column("最差资产", min_width=12)

        current = cycle["cycle"]
        for key, name, features, best, worst in CYCLE_REFERENCE:
            display_name = f"{CYCLE_EMOJI.get(key, '')} {name}"
            if key == current:
                ct.add_row(f"[bold]{display_name} ← 当前[/bold]", f"[bold]{features}[/bold]",
                           f"[bold]{best}[/bold]", f"[bold]{worst}[/bold]")
            else:
                ct.add_row(display_name, features, best, worst)

        self.console.print(ct)

        # Scoring details
        detail_lines = []
        if cycle["expansion_details"]:
            detail_lines.append("[green]扩张信号:[/] " + " | ".join(cycle["expansion_details"]))
        if cycle["recession_details"]:
            detail_lines.append("[red]衰退信号:[/] " + " | ".join(cycle["recession_details"]))
        if detail_lines:
            self.console.print(Panel("\n".join(detail_lines),
                                     title="[bold]📋 周期评分明细[/]", border_style="dim"))

        # Asset allocation table
        alloc = cycle["allocation"]
        t = Table(title="📊 推荐资产配置 (基于当前经济周期)", show_header=True,
                  header_style="bold magenta", expand=True, show_lines=False, padding=(0, 1))
        t.add_column("资产类别", style="bold", min_width=10)
        t.add_column("建议权重", justify="center", min_width=10)
        t.add_column("推荐标的", min_width=30)

        for key in ASSET_CLASSES:
            weight, detail = alloc[key]
            t.add_row(ASSET_LABELS[key], weight, detail)

        self.console.print(t)

        caveats = cycle.get("allocation_caveats") or []
        if caveats:
            lines = []
            for c in caveats:
                style = "yellow" if "不对冲" in c or "无估值补偿" in c else "dim"
                lines.append(f"[{style}]• {c}[/{style}]")
            self.console.print(Panel("\n".join(lines),
                                     title="[bold]⚠️ 配置前提检查[/]", border_style="yellow"))

    # ------------------------------------------------------------------
    # Position target signals panel
    # ------------------------------------------------------------------

    def _position_panel(self):
        pos = self.r.get("position_signals")
        if not pos:
            return

        t = Table(title="📊 标的加仓信号", show_header=True,
                  header_style="bold magenta", expand=True, show_lines=True, padding=(0, 1))
        t.add_column("标的", style="bold", min_width=14)
        t.add_column("价格", justify="right", min_width=8)
        t.add_column("MA50", justify="right", min_width=8)
        t.add_column("MA200", justify="right", min_width=8)
        t.add_column("RSI", justify="right", min_width=6)
        t.add_column("距52周高", justify="right", min_width=8)
        t.add_column("评分", justify="center", min_width=6)
        t.add_column("操作建议", min_width=16)

        for sig in pos.values():
            if sig.get("price") is None:
                t.add_row(sig["label"], "N/A", "N/A", "N/A", "N/A", "N/A", "N/A", sig["action"])
                continue

            level = sig["action_level"]
            if level in ("strong_buy", "buy"):
                score_style = "bold green"
            elif level == "consider_buy":
                score_style = "green"
            elif level == "hold":
                score_style = "cyan"
            elif level == "consider_sell":
                score_style = "yellow"
            else:
                score_style = "bold red"

            action_str = f"{sig['action']}\n仓位: {sig['position_change']}"
            dd = sig.get("drawdown_from_high")

            t.add_row(
                sig["label"], f"${sig['price']:.2f}",
                _fmt(sig.get("ma50"), 2), _fmt(sig.get("ma200"), 2),
                _fmt(sig.get("rsi"), 1),
                _fmt(dd, 1, "%"),
                f"[{score_style}]{sig['final_score']}[/{score_style}]",
                f"[{score_style}]{action_str}[/{score_style}]",
            )

        self.console.print(t)

        detail_lines = []
        for sig in pos.values():
            if not sig.get("details"):
                continue
            detail_lines.append(f"[bold]{sig['label']}[/]  [dim]宏观: {sig['macro_gate']}[/]")
            for d in sig["details"]:
                color = "green" if "(+" in d else "red" if "(-" in d else "dim"
                detail_lines.append(f"  [{color}]• {d}[/{color}]")

        if detail_lines:
            self.console.print(Panel("\n".join(detail_lines),
                                     title="[bold]📋 加仓信号明细[/]",
                                     border_style="magenta"))

    # ------------------------------------------------------------------
    # Rebalancing (spec 五、再平衡策略)
    # ------------------------------------------------------------------

    def _rebalance_panel(self):
        rb = self.r.get("rebalance")
        if not rb:
            return
        if not rb.get("available"):
            self.console.print(Panel(f"[yellow]{rb.get('error', '组合数据不可用')}[/]",
                                     title="[bold]⚖️ 再平衡检查[/]", border_style="yellow"))
            return

        t = Table(title=f"⚖️ 再平衡检查 (组合 ${rb['total']:,.0f})", show_header=True,
                  header_style="bold cyan", expand=True, padding=(0, 1))
        t.add_column("资产类别", style="bold", min_width=10)
        t.add_column("当前", justify="right", min_width=7)
        t.add_column("目标", justify="right", min_width=7)
        t.add_column("偏离", justify="right", min_width=8)
        t.add_column("交易额", justify="right", min_width=10)
        t.add_column("状态", min_width=30)

        styles = {"force": "bold red", "trigger": "red", "observe": "yellow", "ok": "dim"}
        for r in rb["rows"]:
            st = styles.get(r["status"], "dim")
            t.add_row(r["label"], f"{r['current']:.1f}%", f"{r['target']:.1f}%",
                      f"[{st}]{r['deviation']:+.1f}pp[/{st}]",
                      f"${r['trade_value']:,.0f}" if r["status"] != "ok" else "[dim]—[/]",
                      f"[{st}]{r['reason']}[/{st}]")
        self.console.print(t)
        border = "red" if rb["actions"] else "yellow" if rb["quarterly_due"] else "green"
        self.console.print(Panel(rb["summary"], title="[bold]⚖️ 再平衡结论[/]",
                                 border_style=border))

    # ------------------------------------------------------------------
    # Indicator tables
    # ------------------------------------------------------------------

    def _indicator_tables(self):
        g = self.r["indicators"]
        tables = []

        for title, _md_title, rows in INDICATOR_GROUPS:
            t = Table(title=title, show_header=True, header_style="bold cyan",
                      expand=True, show_lines=False, padding=(0, 1))
            t.add_column("指标", style="bold", min_width=10)
            t.add_column("当前值", justify="right", min_width=10)
            t.add_column("状态", justify="center", min_width=4)

            for key, label, decimals, suffix, formatter, _ref in rows:
                value = _row_value(key, decimals, suffix, formatter, g)
                t.add_row(label,
                          value if value is not None else "[dim]N/A[/]",
                          _status_icon(_row_grade(key, g)))
            tables.append(t)

        # Three groups on the first row, the remaining two below.
        self.console.print(Columns(tables[:3], equal=True, expand=True))
        self.console.print(Columns(tables[3:], equal=True, expand=True))

    # ------------------------------------------------------------------
    # Leader health table
    # ------------------------------------------------------------------

    def _leader_table(self):
        leaders = self.r["leader_health"]
        if not leaders:
            return

        t = Table(title="🏢 龙头股健康度", show_header=True, header_style="bold magenta",
                  expand=True, show_lines=False, padding=(0, 1))
        t.add_column("股票", style="bold", min_width=6)
        t.add_column("价格", justify="right", min_width=8)
        t.add_column("vs MA50", justify="right", min_width=8)
        t.add_column("vs MA200", justify="right", min_width=8)
        t.add_column("20日涨幅", justify="right", min_width=8)
        t.add_column("量比", justify="right", min_width=6)
        t.add_column("状态", justify="center", min_width=4)

        for lh in leaders:
            price = f"${lh['price']:.1f}" if lh["price"] is not None else "[dim]N/A[/]"
            vr = lh.get("vol_ratio")
            vr_str = "[dim]N/A[/]" if vr is None else (
                f"[bold red]{vr:.1f}x[/]" if lh.get("heavy_down") else f"{vr:.1f}x")
            t.add_row(lh["name"], price,
                      _fmt(lh["vs_ma50"], 1, "%"),
                      _fmt(lh["vs_ma200"], 1, "%"),
                      _fmt(lh["ret_20d"], 1, "%"),
                      vr_str,
                      _status_icon(lh["status"]))

        self.console.print(t)

    # ------------------------------------------------------------------
    # Signals panel
    # ------------------------------------------------------------------

    def _signals_panel(self):
        signals = self.r["signals"]
        if not signals:
            self.console.print(Panel("[green]当前无活跃信号[/]", title="[bold]🔔 活跃信号[/]"))
            return

        lines = []
        for s in sorted(signals, key=lambda x: -abs(x["score"])):
            icon = _status_icon(s["level"])
            score_str = f"+{s['score']}" if s["score"] > 0 else str(s["score"])
            color = "red" if s["score"] > 0 else "green"
            desc = f"  [dim]{s['desc']}[/]" if s.get("desc") else ""
            tag = "" if s.get("source", "spec") == "spec" else " [dim](扩展)[/]"
            lines.append(f"  {icon} [{color}][风险{score_str}][/{color}] {s['name']}{tag}{desc}")

        self.console.print(Panel("\n".join(lines), title="[bold]🔔 活跃信号[/]",
                                 border_style="yellow"))

    # ------------------------------------------------------------------
    # Combos panel
    # ------------------------------------------------------------------

    def _combos_panel(self):
        lines = []
        for c in self.r["combos"]:
            detail = c.get("detail", "")
            if c["triggered"] is None:
                lines.append(f"  [dim]👁  {c['name']}  —  {detail}[/]")
            elif c["triggered"]:
                lines.append(f"  [bold red]🔴 {c['name']}  —  已触发！{detail}[/]")
            else:
                extra = f"  ({detail})" if detail else ""
                lines.append(f"  [green]✅ {c['name']}  —  未触发{extra}[/]")

        self.console.print(Panel("\n".join(lines), title="[bold]⚠️ 高危组合监控[/]",
                                 border_style="red"))

    # ------------------------------------------------------------------
    # Recommendation
    # ------------------------------------------------------------------

    def _recommendation_panel(self):
        rec = self.r["recommendation"]
        detail = self.r["recommendation_detail"]

        if "数据不足" in rec:
            style, border = "bold white on red", "red"
        elif "强烈卖出" in rec:
            style, border = "bold white on red", "red"
        elif "减仓" in rec:
            style, border = "bold red", "red"
        elif "强烈买入" in rec:
            style, border = "bold white on green", "green"
        elif "买入" in rec:
            style, border = "bold green", "green"
        else:
            style, border = "bold cyan", "blue"

        content = Text()
        content.append("操作建议: ", style="bold")
        content.append(rec, style=style)
        content.append(f"\n{detail}", style="dim")
        content.append("\n\n[免责声明] 本工具仅供参考，不构成投资建议。投资有风险，决策需谨慎。",
                       style="dim italic")

        self.console.print(Panel(content, title="[bold]📋 操作建议[/]", border_style=border))


# ======================================================================
# Markdown output (for GitHub Actions / CI)
# ======================================================================

class MarkdownReport:

    def __init__(self, result, news_articles=None, ai_summary=""):
        self.r = result
        self.news_articles = news_articles or []
        self.ai_summary = ai_summary
        self.lines = []

    def render(self):
        self.lines = []
        self._header()
        self._data_health()
        self._market_overview()
        self._risk_summary()
        self._cycle_section()
        self._position_section()
        self._rebalance_section()
        self._ai_section()
        self._indicator_guide()
        self._leader_table()
        self._signals()
        self._combos()
        self._recommendation()
        return "\n".join(self.lines)

    def _w(self, text=""):
        self.lines.append(text)

    def _header(self):
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        self._w("# 📊 美股市场监控报告")
        self._w(f"> 更新时间: {now}")
        self._w()

    # ------------------------------------------------------------------
    # Data health
    # ------------------------------------------------------------------

    def _data_health(self):
        health = self.r.get("data_health") or {}
        missing = health.get("missing_critical") or []
        macro_missing = health.get("missing_macro") or []
        errors = health.get("fetch_errors") or []

        if not missing and not macro_missing and not errors:
            return

        self._w("## ⚠️ 数据质量")
        self._w()
        if missing:
            self._w(f"> 🔴 **关键数据缺失: {', '.join(missing)}**")
            self._w("> ")
            self._w("> 本次不给出风险评级和操作建议 —— 空信号不等于低风险。")
            self._w()
        if macro_missing:
            self._w(f"- 🟡 宏观数据缺失: {', '.join(macro_missing)}")
        for err in errors[:8]:
            self._w(f"- ⚪ {err}")
        if len(errors) > 8:
            self._w(f"- ⚪ ...另有 {len(errors) - 8} 条")
        self._w()

    def _market_overview(self):
        summary = self.r["indicators"].get("MARKET_SUMMARY", [])
        if not summary:
            return

        self._w("## 📈 今日行情")
        self._w()
        for item in summary:
            pct = item["change_pct"]
            price_str, chg_str = _price_strings(item)
            self._w(f"- {_up_down_emoji(pct)} **{item['label']}** "
                    f"{price_str}（{chg_str} / {pct:+.2f}%）")
        self._w()

    def _risk_summary(self):
        score = self.r["risk_score"]
        level = self.r["risk_level"]
        dangers = self.r.get("danger_count", 0)

        b1, b2, b3 = RISK_BANDS
        if "数据不足" in level:
            badge = "⚠️"
        elif score <= b1:
            badge = "🟢"
        elif score <= b2:
            badge = "🟡"
        elif score <= b3:
            badge = "🔴"
        else:
            badge = "🔴🔴"

        cycle = self.r.get("economic_cycle", {})

        self._w("## 🎯 综合评估")
        self._w()
        self._w(f"- 风险评分: {badge} **{score}** / {MAX_RISK_POSITIVE} — {level}")
        self._w(f"  <sub>档位: ≤0 低 / ≤{b1} 中低 / ≤{b2} 中等 / ≤{b3} 高 / >{b3} 极高</sub>")
        self._w(f"- 危险信号: **{dangers}** 项"
                + ("（总分可被利好信号对冲，请同时看这一项）" if dangers >= 3 else ""))
        self._w(f"- 市场阶段: {self.r['market_phase']}")
        self._w(f"- 操作建议: **{self.r['recommendation']}**")
        self._w(f"- 经济周期: {cycle.get('cycle_cn', 'N/A')}")
        self._w()

    def _cycle_section(self):
        cycle = self.r.get("economic_cycle")
        if not cycle:
            return

        current = cycle["cycle"]
        emoji = CYCLE_EMOJI.get(current, "🔄")

        self._w("## 🔄 经济周期判断")
        self._w()
        self._w("| 项目 | 结果 |")
        self._w("|------|------|")
        self._w(f"| 经济周期 | {emoji} **{cycle['cycle_cn']}** |")
        self._w(f"| 周期描述 | {cycle['cycle_desc']} |")
        self._w(f"| 通胀水平 | {cycle['inflation_label']} |")
        self._w(f"| 扩张信号 | {cycle['expansion_score']}/10 |")
        self._w(f"| 衰退信号 | {cycle['recession_score']}/10 |")
        self._w()

        if cycle["expansion_details"]:
            self._w(f"**扩张信号明细:** {' | '.join(cycle['expansion_details'])}")
            self._w()
        if cycle["recession_details"]:
            self._w(f"**衰退信号明细:** {' | '.join(cycle['recession_details'])}")
            self._w()

        self._w("### 📖 经济周期参考")
        self._w()
        for key, name, features, best, worst in CYCLE_REFERENCE:
            display_name = f"{CYCLE_EMOJI.get(key, '')} {name}"
            if key == current:
                self._w(f"**👉 {display_name} ← 当前**")
            else:
                self._w(f"**{display_name}**")
            self._w(f"> {features}")
            self._w(f"> 最优: {best} / 最差: {worst}")
            self._w()

        alloc = cycle["allocation"]
        self._w("### 📊 推荐资产配置")
        self._w()
        for key in ASSET_CLASSES:
            weight, detail = alloc[key]
            self._w(f"- {ASSET_EMOJI[key]} {ASSET_LABELS[key]}: **{weight}**")
            self._w(f"  {detail}")
        self._w()

        caveats = cycle.get("allocation_caveats") or []
        if caveats:
            self._w("**⚠️ 配置前提检查:**")
            self._w()
            for c in caveats:
                self._w(f"- {c}")
            self._w()

    def _position_section(self):
        pos = self.r.get("position_signals")
        if not pos:
            return

        self._w("## 📊 标的加仓信号")
        self._w()

        for sig in pos.values():
            if sig.get("price") is None:
                self._w(f"### {sig['label']}")
                self._w(f"> ⚠️ {sig['action']}")
                self._w()
                continue

            level = sig["action_level"]
            if level in ("strong_buy", "buy"):
                emoji = "🟢"
            elif level == "consider_buy":
                emoji = "🔵"
            elif level == "hold":
                emoji = "⚪"
            elif level == "consider_sell":
                emoji = "🟡"
            else:
                emoji = "🔴"

            mc = sig.get("macd_cross")
            mc_label = ("金叉" if mc == "golden_cross"
                        else "死叉" if mc == "death_cross" else "无")

            self._w(f"### {emoji} {sig['label']}")
            self._w()
            self._w("| 指标 | 值 |")
            self._w("|------|------|")
            self._w(f"| 当前价 | ${sig['price']:.2f} |")
            self._w(f"| MA50 | {_md_val(sig.get('ma50'), 2)} |")
            self._w(f"| MA200 | {_md_val(sig.get('ma200'), 2)} |")
            self._w(f"| 距MA200 | {_md_val(sig.get('pct_ma200'), 1, '%')} |")
            self._w(f"| RSI(14) | {_md_val(sig.get('rsi'), 1)} |")
            self._w(f"| MACD交叉 | {mc_label} |")
            self._w(f"| 距52周高 | {_md_val(sig.get('drawdown_from_high'), 1, '%')} |")
            self._w(f"| **综合评分** | **{sig['final_score']}** |")
            self._w(f"| **操作建议** | **{emoji} {sig['action']}** |")
            self._w(f"| 仓位变动 | {sig['position_change']} |")
            self._w(f"| 宏观环境 | {sig['macro_gate']} |")
            self._w()

            if sig.get("details"):
                self._w("**触发条件:**")
                for d in sig["details"]:
                    self._w(f"- {d}")
                self._w()

    def _rebalance_section(self):
        rb = self.r.get("rebalance")
        if not rb:
            return
        self._w("## ⚖️ 再平衡检查")
        self._w()
        if not rb.get("available"):
            self._w(f"> ⚠️ {rb.get('error', '组合数据不可用')}")
            self._w()
            return

        self._w(f"> **{rb['summary']}**  ·  组合总额 ${rb['total']:,.0f}"
                f"  ·  最小起振 ${rb['min_trade']:,.0f}")
        self._w()
        self._w("| 资产类别 | 当前 | 目标 | 偏离 | 交易额 | 状态 |")
        self._w("|------|------|------|------|------|------|")
        icons = {"force": "🔴", "trigger": "🟠", "observe": "🟡", "ok": "🟢"}
        for r in rb["rows"]:
            trade = f"${r['trade_value']:,.0f}" if r["status"] != "ok" else "—"
            self._w(f"| {icons.get(r['status'], '⚪')} {r['label']} | {r['current']:.1f}% | "
                    f"{r['target']:.1f}% | {r['deviation']:+.1f}pp | {trade} | {r['reason']} |")
        self._w()

    def _ai_section(self):
        if not self.ai_summary:
            return
        self._w("## 🤖 AI 智能研判（已结合实时新闻）")
        self._w()
        for line in self.ai_summary.strip().split("\n"):
            self._w(f"> {line}")
        self._w()

    def _indicator_guide(self):
        g = self.r["indicators"]
        self._w("## 📊 核心指标")
        self._w()

        for _title, md_title, rows in INDICATOR_GROUPS:
            self._w(f"### {md_title}")
            self._w()
            for key, label, decimals, suffix, formatter, ref in rows:
                value = _row_value(key, decimals, suffix, formatter, g)
                icon = _md_icon(_row_grade(key, g))
                self._w(f"- {icon} **{label}**: {value if value is not None else 'N/A'}")
                self._w(f"  {ref}")
            self._w()

    def _leader_table(self):
        leaders = self.r["leader_health"]
        if not leaders:
            return

        self._w("## 🏢 龙头股健康度")
        self._w()
        for lh in leaders:
            icon = _md_icon(lh["status"])
            price = f"${lh['price']:.1f}" if lh["price"] is not None else "N/A"
            vr = lh.get("vol_ratio")
            vol_str = "" if vr is None else (
                f" | 量比: {vr:.1f}x" + (" ⚠️放量下跌" if lh.get("heavy_down") else ""))
            self._w(f"- {icon} **{lh['name']}** {price} | "
                    f"MA50: {_md_val(lh['vs_ma50'], 1, '%')} | "
                    f"20日: {_md_val(lh['ret_20d'], 1, '%')}{vol_str}")
        self._w()

    def _signals(self):
        signals = self.r["signals"]
        self._w("## 🔔 活跃信号")
        self._w()

        if not signals:
            self._w("> 🟢 当前无活跃信号")
            self._w()
            return

        for s in sorted(signals, key=lambda x: -abs(x["score"])):
            icon = _md_icon(s["level"])
            score_str = f"+{s['score']}" if s["score"] > 0 else str(s["score"])
            desc = f" — {s['desc']}" if s.get("desc") else ""
            tag = "" if s.get("source", "spec") == "spec" else " *(扩展)*"
            self._w(f"- {icon} **[风险{score_str}]** {s['name']}{tag}{desc}")
        self._w()

    def _combos(self):
        self._w("## ⚠️ 高危组合监控")
        self._w()

        for c in self.r["combos"]:
            detail = c.get("detail", "")
            if c["triggered"] is None:
                self._w(f"- 👁 {c['name']} — {detail}")
            elif c["triggered"]:
                self._w(f"- 🔴 **{c['name']}** — 已触发！{detail}")
            else:
                extra = f" ({detail})" if detail else ""
                self._w(f"- ✅ {c['name']} — 未触发{extra}")
        self._w()

    def _recommendation(self):
        rec = self.r["recommendation"]
        detail = self.r["recommendation_detail"]

        if "数据不足" in rec:
            emoji = "⚠️"
        elif "强烈卖出" in rec or "减仓" in rec:
            emoji = "🚨"
        elif "强烈买入" in rec or "买入" in rec:
            emoji = "💰"
        else:
            emoji = "📋"

        self._w("---")
        self._w()
        self._w(f"> {emoji} **操作建议: {rec}**")
        self._w(">")
        self._w(f"> {detail}")
        self._w()
        self._w("---")
        self._w("*⚠️ 本工具仅供参考，不构成投资建议。投资有风险，决策需谨慎。*")

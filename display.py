from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.columns import Columns


def _status_icon(level):
    if level == "danger":
        return "[bold red]●[/]"
    elif level == "warning":
        return "[bold yellow]●[/]"
    elif level == "safe":
        return "[bold green]●[/]"
    return "[dim]○[/]"


def _color_val(value, thresholds, reverse=False):
    """Color a value based on thresholds: (low, high).
    Green if below low, yellow between, red above high.
    If reverse=True, green is above high."""
    if value is None:
        return "[dim]N/A[/]"
    low, high = thresholds
    if reverse:
        if value >= high:
            return f"[green]{value}[/]"
        elif value <= low:
            return f"[red]{value}[/]"
        return f"[yellow]{value}[/]"
    else:
        if value <= low:
            return f"[green]{value}[/]"
        elif value >= high:
            return f"[red]{value}[/]"
        return f"[yellow]{value}[/]"


def _fmt(val, decimals=2, suffix=""):
    if val is None:
        return "[dim]N/A[/]"
    return f"{val:.{decimals}f}{suffix}"


class Dashboard:

    def __init__(self, result):
        self.r = result
        self.console = Console()

    def render(self):
        self.console.print()
        self._header()
        self._risk_summary()
        self._cycle_panel()
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
    # Risk summary
    # ------------------------------------------------------------------

    def _risk_summary(self):
        score = self.r["risk_score"]
        level = self.r["risk_level"]
        phase = self.r["market_phase"]

        if score <= 0:
            score_style = "bold green"
        elif score <= 30:
            score_style = "green"
        elif score <= 50:
            score_style = "yellow"
        elif score <= 70:
            score_style = "bold red"
        else:
            score_style = "bold red on white"

        lines = Text()
        lines.append("风险评分: ", style="bold")
        lines.append(f"{score}", style=score_style)
        lines.append(f"    风险等级: ", style="bold")
        lines.append(level, style=score_style)
        lines.append(f"\n市场阶段: ", style="bold")
        lines.append(phase, style="cyan")

        self.console.print(Panel(lines, title="[bold]综合评估[/]", border_style="blue"))

    # ------------------------------------------------------------------
    # Economic Cycle panel
    # ------------------------------------------------------------------

    def _cycle_panel(self):
        cycle = self.r.get("economic_cycle")
        if not cycle:
            return

        cycle_colors = {
            "recovery": "bold green",
            "expansion": "green",
            "late_cycle": "yellow",
            "late_stagflation": "bold yellow",
            "stagflation": "bold red",
            "recession": "bold red",
            "transition": "cyan",
        }
        style = cycle_colors.get(cycle["cycle"], "cyan")

        lines = Text()
        lines.append("经济周期: ", style="bold")
        lines.append(cycle["cycle_cn"], style=style)
        lines.append(f"\n{cycle['cycle_desc']}", style="dim")
        lines.append(f"\n通胀水平: ", style="bold")
        lines.append(cycle["inflation_label"], style="yellow" if cycle.get("cpi_yoy") and cycle["cpi_yoy"] > 3 else "green")
        lines.append(f"\n扩张信号: ", style="bold")
        lines.append(f"{cycle['expansion_score']}/10", style="green")
        lines.append(f"    衰退信号: ", style="bold")
        lines.append(f"{cycle['recession_score']}/10", style="red")

        self.console.print(Panel(lines, title="[bold]🔄 经济周期判断[/]", border_style="magenta"))

        # Cycle reference table
        ct = Table(title="📖 经济周期参考", show_header=True,
                   header_style="bold cyan", expand=True, show_lines=True, padding=(0, 1))
        ct.add_column("阶段", style="bold", min_width=8)
        ct.add_column("经济特征", min_width=20)
        ct.add_column("最优资产", min_width=12)
        ct.add_column("最差资产", min_width=12)

        cycle_ref = [
            ("recovery", "🌱 复苏期",
             "GDP转正，失业率见顶回落，央行维持宽松，通胀低位",
             "成长股、小盘股", "现金"),
            ("expansion", "☀️ 扩张期",
             "GDP稳健(2-4%)，就业持续改善，通胀温和上升",
             "大盘股、大宗商品", "长期国债"),
            ("late_cycle", "🌤️ 周期末期",
             "增长放缓，通胀升温，央行收紧，领先指标转弱",
             "防御板块、黄金", "成长股"),
            ("stagflation", "🔥 滞胀期",
             "经济停滞+高通胀，央行被迫加息，利润率受挤压",
             "黄金、大宗商品、TIPS", "股票、长期国债"),
            ("recession", "❄️ 衰退期",
             "GDP负增长，失业飙升，央行紧急降息/QE",
             "长期国债、现金", "股票、大宗商品"),
            ("transition", "🔄 过渡期",
             "信号混合，扩张与衰退指标共存，方向不明",
             "均衡配置", "避免集中持仓"),
        ]

        current = cycle["cycle"]
        for key, name, features, best, worst in cycle_ref:
            is_current = key == current
            marker = " ← 当前" if is_current else ""
            if is_current:
                ct.add_row(f"[bold]{name}{marker}[/bold]",
                           f"[bold]{features}[/bold]",
                           f"[bold]{best}[/bold]",
                           f"[bold]{worst}[/bold]")
            else:
                ct.add_row(name, features, best, worst)

        self.console.print(ct)

        # Scoring details
        detail_lines = []
        if cycle["expansion_details"]:
            detail_lines.append("[green]扩张信号:[/] " + " | ".join(cycle["expansion_details"]))
        if cycle["recession_details"]:
            detail_lines.append("[red]衰退信号:[/] " + " | ".join(cycle["recession_details"]))
        if detail_lines:
            self.console.print(Panel("\n".join(detail_lines), title="[bold]📋 周期评分明细[/]", border_style="dim"))

        # Asset allocation table
        alloc = cycle["allocation"]
        t = Table(title="📊 推荐资产配置 (基于当前经济周期)", show_header=True,
                  header_style="bold magenta", expand=True, show_lines=False, padding=(0, 1))
        t.add_column("资产类别", style="bold", min_width=10)
        t.add_column("建议权重", justify="center", min_width=10)
        t.add_column("推荐标的", min_width=30)

        labels = {
            "stocks": "股票",
            "long_bonds": "长期国债",
            "cash": "现金/短债",
            "gold": "黄金",
            "tips": "TIPS通胀保护",
            "commodities": "大宗商品",
        }
        for key in ["stocks", "long_bonds", "cash", "gold", "tips", "commodities"]:
            weight, detail = alloc[key]
            t.add_row(labels[key], weight, detail)

        self.console.print(t)

    # ------------------------------------------------------------------
    # Indicator tables
    # ------------------------------------------------------------------

    def _indicator_tables(self):
        g = self.r["indicators"]
        panels = []

        # ----- Liquidity -----
        t = Table(title="第一层: 流动性", show_header=True, header_style="bold cyan",
                  expand=True, show_lines=False, padding=(0, 1))
        t.add_column("指标", style="bold", min_width=10)
        t.add_column("当前值", justify="right", min_width=10)
        t.add_column("状态", justify="center", min_width=4)

        us10y = g.get("US10Y")
        t.add_row("US10Y", _fmt(us10y, suffix="%"),
                   _status_icon("danger" if us10y and us10y > 4.5 else
                                "warning" if us10y and us10y > 4.0 else "safe"))

        us2y = g.get("US2Y")
        t.add_row("US2Y", _fmt(us2y, suffix="%"),
                   _status_icon("warning" if us2y and us2y > 4.5 else "safe"))

        tips = g.get("TIPS")
        t.add_row("TIPS实际利率", _fmt(tips, suffix="%"),
                   _status_icon("danger" if tips and tips > 2.0 else
                                "warning" if tips and tips > 1.5 else "safe"))

        t10y2y = g.get("T10Y2Y")
        t.add_row("10Y-2Y利差", _fmt(t10y2y, suffix="%"),
                   _status_icon("danger" if t10y2y is not None and t10y2y < 0 else "safe"))

        dxy = g.get("DXY")
        t.add_row("DXY", _fmt(dxy, 1),
                   _status_icon("danger" if dxy and dxy > 105 else
                                "warning" if dxy and dxy > 103 else "safe"))

        hy = g.get("HY_OAS")
        t.add_row("HY OAS", _fmt(hy, 0, "bp") if hy else "[dim]N/A[/]",
                   _status_icon("danger" if hy and hy > 500 else
                                "warning" if hy and hy > 350 else "safe"))

        m2 = g.get("M2_YOY")
        t.add_row("M2同比增速", _fmt(m2, 1, "%"),
                   _status_icon("safe" if m2 and m2 > 2 else
                                "warning" if m2 and m2 > 0 else
                                "danger" if m2 and m2 < 0 else "safe"))

        panels.append(t)

        # ----- Sentiment -----
        t2 = Table(title="第二层: 情绪", show_header=True, header_style="bold cyan",
                   expand=True, show_lines=False, padding=(0, 1))
        t2.add_column("指标", style="bold", min_width=10)
        t2.add_column("当前值", justify="right", min_width=10)
        t2.add_column("状态", justify="center", min_width=4)

        vix = g.get("VIX")
        t2.add_row("VIX", _fmt(vix, 1),
                    _status_icon("danger" if vix and vix > 30 else
                                 "warning" if vix and vix > 20 else "safe"))

        vxn = g.get("VXN")
        t2.add_row("VXN", _fmt(vxn, 1),
                    _status_icon("danger" if vxn and vxn > 35 else
                                 "warning" if vxn and vxn > 25 else "safe"))

        vt = g.get("VIX_TERM")
        vt_label = "倒挂" if vt and vt > 1 else "正常" if vt else "N/A"
        t2.add_row("VIX期限结构", f"{vt_label} ({_fmt(vt)})" if vt else "[dim]N/A[/]",
                    _status_icon("danger" if vt and vt > 1 else "safe"))

        skew = g.get("SKEW")
        t2.add_row("SKEW", _fmt(skew, 0),
                    _status_icon("danger" if skew and skew > 150 else
                                 "warning" if skew and skew > 140 else "safe"))

        fg = g.get("FEAR_GREED")
        fg_label = g.get("FEAR_GREED_LABEL", "")
        t2.add_row("恐惧贪婪指数", f"{_fmt(fg, 0)} {fg_label}" if fg else "[dim]N/A[/]",
                    _status_icon("warning" if fg and (fg > 80 or fg < 20) else "safe"))

        panels.append(t2)

        # ----- Leading -----
        t3 = Table(title="第三层: 领先指标", show_header=True, header_style="bold cyan",
                   expand=True, show_lines=False, padding=(0, 1))
        t3.add_column("指标", style="bold", min_width=12)
        t3.add_column("当前值", justify="right", min_width=10)
        t3.add_column("状态", justify="center", min_width=4)

        sox = g.get("SOX")
        t3.add_row("SOX半导体", _fmt(sox, 0), _status_icon("safe"))

        rsp_spy = g.get("RSP_SPY_20D_CHG")
        t3.add_row("RSP/SPY 20日", _fmt(rsp_spy, 1, "%"),
                    _status_icon("danger" if rsp_spy and rsp_spy < -2 else
                                 "warning" if rsp_spy and rsp_spy < -0.5 else "safe"))

        xly_xlu = g.get("XLY_XLU")
        t3.add_row("XLY/XLU", _fmt(xly_xlu),
                    _status_icon("safe"))

        cu_au = g.get("CU_AU")
        t3.add_row("铜/金比值", _fmt(cu_au, 6) if cu_au and cu_au < 0.01 else _fmt(cu_au, 4),
                    _status_icon("safe"))

        panels.append(t3)
        self.console.print(Columns(panels, equal=True, expand=True))

        # ----- Second row: Macro + Technical -----
        panels2 = []

        t4 = Table(title="第四层: 宏观经济", show_header=True, header_style="bold cyan",
                   expand=True, show_lines=False, padding=(0, 1))
        t4.add_column("指标", style="bold", min_width=10)
        t4.add_column("当前值", justify="right", min_width=10)
        t4.add_column("状态", justify="center", min_width=4)

        sahm = g.get("SAHM")
        t4.add_row("萨姆规则", _fmt(sahm),
                    _status_icon("danger" if sahm and sahm >= 0.5 else
                                 "warning" if sahm and sahm >= 0.3 else "safe"))

        unrate = g.get("UNRATE")
        t4.add_row("失业率", _fmt(unrate, 1, "%"), _status_icon("safe"))

        curve = g.get("T10Y2Y")
        curve_label = "倒挂" if curve is not None and curve < 0 else "正常"
        t4.add_row("收益率曲线", f"{curve_label} ({_fmt(curve)}%)" if curve is not None else "[dim]N/A[/]",
                    _status_icon("danger" if curve is not None and curve < 0 else "safe"))

        panels2.append(t4)

        t5 = Table(title="第五层: 技术面", show_header=True, header_style="bold cyan",
                   expand=True, show_lines=False, padding=(0, 1))
        t5.add_column("指标", style="bold", min_width=12)
        t5.add_column("当前值", justify="right", min_width=10)
        t5.add_column("状态", justify="center", min_width=4)

        spy_pct = g.get("SPY_VS_MA200")
        t5.add_row("SPY vs MA200", _fmt(spy_pct, 1, "%"),
                    _status_icon("danger" if spy_pct is not None and spy_pct < 0 else "safe"))

        qqq_pct = g.get("QQQ_VS_MA200")
        t5.add_row("QQQ vs MA200", _fmt(qqq_pct, 1, "%"),
                    _status_icon("danger" if qqq_pct is not None and qqq_pct < 0 else "safe"))

        spy_rsi = g.get("SPY_RSI")
        t5.add_row("SPY RSI(14)", _fmt(spy_rsi, 1),
                    _status_icon("warning" if spy_rsi and (spy_rsi > 70 or spy_rsi < 30) else "safe"))

        qqq_rsi = g.get("QQQ_RSI")
        t5.add_row("QQQ RSI(14)", _fmt(qqq_rsi, 1),
                    _status_icon("warning" if qqq_rsi and (qqq_rsi > 70 or qqq_rsi < 30) else "safe"))

        macd_status = "多头" if g.get("SPY_MACD_BULL") else "空头"
        t5.add_row("SPY MACD", macd_status,
                    _status_icon("safe" if g.get("SPY_MACD_BULL") else "danger"))

        panels2.append(t5)
        self.console.print(Columns(panels2, equal=True, expand=True))

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
        t.add_column("状态", justify="center", min_width=4)

        for lh in leaders:
            price = f"${lh['price']:.1f}" if lh["price"] else "N/A"
            vs50 = _fmt(lh["vs_ma50"], 1, "%") if lh["vs_ma50"] is not None else "[dim]N/A[/]"
            vs200 = _fmt(lh["vs_ma200"], 1, "%") if lh["vs_ma200"] is not None else "[dim]N/A[/]"
            ret = _fmt(lh["ret_20d"], 1, "%") if lh["ret_20d"] is not None else "[dim]N/A[/]"
            t.add_row(lh["name"], price, vs50, vs200, ret, _status_icon(lh["status"]))

        self.console.print(t)

    # ------------------------------------------------------------------
    # Signals panel
    # ------------------------------------------------------------------

    def _signals_panel(self):
        signals = self.r["signals"]
        if not signals:
            self.console.print(Panel("[green]当前无活跃信号[/]", title="[bold]🔔 活跃信号[/]"))
            return

        sorted_signals = sorted(signals, key=lambda x: -abs(x["score"]))
        lines = []
        for s in sorted_signals:
            icon = _status_icon(s["level"])
            score_str = f"+{s['score']}" if s["score"] > 0 else str(s["score"])
            color = "red" if s["score"] > 0 else "green"
            desc = f"  [dim]{s['desc']}[/]" if s.get("desc") else ""
            lines.append(f"  {icon} [{color}][风险{score_str}][/{color}] {s['name']}{desc}")

        self.console.print(Panel("\n".join(lines), title="[bold]🔔 活跃信号[/]", border_style="yellow"))

    # ------------------------------------------------------------------
    # Combos panel
    # ------------------------------------------------------------------

    def _combos_panel(self):
        combos = self.r["combos"]
        lines = []
        for c in combos:
            detail = c.get("detail", "")
            if c["triggered"] is True:
                lines.append(f"  [bold red]🔴 {c['name']}  —  已触发！{detail}[/]")
            elif c["triggered"] is False:
                extra = f"  ({detail})" if detail else ""
                lines.append(f"  [green]✅ {c['name']}  —  未触发{extra}[/]")
            else:
                lines.append(f"  [dim]👁  {c['name']}  —  {detail}[/]")

        self.console.print(Panel("\n".join(lines), title="[bold]⚠️ 高危组合监控[/]", border_style="red"))

    # ------------------------------------------------------------------
    # Recommendation
    # ------------------------------------------------------------------

    def _recommendation_panel(self):
        rec = self.r["recommendation"]
        detail = self.r["recommendation_detail"]

        if "强烈卖出" in rec:
            style = "bold white on red"
            border = "red"
        elif "减仓" in rec:
            style = "bold red"
            border = "red"
        elif "强烈买入" in rec:
            style = "bold white on green"
            border = "green"
        elif "买入" in rec:
            style = "bold green"
            border = "green"
        else:
            style = "bold cyan"
            border = "blue"

        content = Text()
        content.append("操作建议: ", style="bold")
        content.append(rec, style=style)
        content.append(f"\n{detail}", style="dim")
        content.append("\n\n[免责声明] 本工具仅供参考，不构成投资建议。投资有风险，决策需谨慎。", style="dim italic")

        self.console.print(Panel(content, title="[bold]📋 操作建议[/]", border_style=border))


# ======================================================================
# Markdown output (for GitHub Actions / CI)
# ======================================================================

def _md_icon(level):
    if level == "danger":
        return "🔴"
    elif level == "warning":
        return "🟡"
    elif level == "safe":
        return "🟢"
    return "⚪"


def _md_val(val, decimals=2, suffix=""):
    if val is None:
        return "N/A"
    return f"{val:.{decimals}f}{suffix}"


class MarkdownReport:

    def __init__(self, result, news_articles=None, ai_summary=""):
        self.r = result
        self.news_articles = news_articles or []
        self.ai_summary = ai_summary
        self.lines = []

    def render(self):
        self._header()
        self._market_overview()
        self._risk_summary()
        self._cycle_section()
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

    def _market_overview(self):
        summary = self.r["indicators"].get("MARKET_SUMMARY", [])
        if not summary:
            return

        self._w("## 📈 今日行情")
        self._w()
        for item in summary:
            chg = item["change"]
            pct = item["change_pct"]

            if item["is_yield"]:
                price_str = f"{item['price']:.2f}%"
                chg_str = f"{chg:+.2f}"
            elif item["name"] == "VIX":
                price_str = f"{item['price']:.1f}"
                chg_str = f"{chg:+.1f}"
            elif item["price"] > 1000:
                price_str = f"{item['price']:,.0f}"
                chg_str = f"{chg:+,.0f}"
            else:
                price_str = f"{item['price']:.1f}"
                chg_str = f"{chg:+.1f}"

            if pct > 0:
                arrow = "🔴"
            elif pct < 0:
                arrow = "🟢"
            else:
                arrow = "➖"

            self._w(f"- {arrow} **{item['label']}** {price_str}（{chg_str} / {pct:+.2f}%）")
        self._w()

    def _risk_summary(self):
        score = self.r["risk_score"]
        level = self.r["risk_level"]
        phase = self.r["market_phase"]
        rec = self.r["recommendation"]

        if score <= 0:
            badge = "🟢"
        elif score <= 30:
            badge = "🟢"
        elif score <= 50:
            badge = "🟡"
        elif score <= 70:
            badge = "🔴"
        else:
            badge = "🔴🔴"

        cycle = self.r.get("economic_cycle", {})
        cycle_cn = cycle.get("cycle_cn", "N/A")

        self._w("## 🎯 综合评估")
        self._w()
        self._w(f"- 风险评分: {badge} **{score}** — {level}")
        self._w(f"- 市场阶段: {phase}")
        self._w(f"- 操作建议: **{rec}**")
        self._w(f"- 经济周期: {cycle_cn}")
        self._w()


    def _cycle_section(self):
        cycle = self.r.get("economic_cycle")
        if not cycle:
            return

        cycle_emoji = {
            "recovery": "🌱", "expansion": "☀️", "late_cycle": "🌤️",
            "late_stagflation": "🌧️", "stagflation": "🔥", "recession": "❄️",
            "transition": "🔄",
        }
        emoji = cycle_emoji.get(cycle["cycle"], "🔄")

        self._w("## 🔄 经济周期判断")
        self._w()
        self._w(f"| 项目 | 结果 |")
        self._w(f"|------|------|")
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

        cycle_markers = {
            "recovery": "🌱", "expansion": "☀️", "late_cycle": "🌤️",
            "late_stagflation": "🌧️", "stagflation": "🔥", "recession": "❄️",
            "transition": "🔄",
        }
        current = cycle["cycle"]

        self._w("### 📖 经济周期参考")
        self._w()

        cycle_ref = [
            ("recovery", "🌱 复苏期",
             "GDP转正，失业率见顶回落，央行宽松，低通胀",
             "成长股、小盘股", "现金"),
            ("expansion", "☀️ 扩张期",
             "GDP稳健(2-4%)，就业改善，通胀温和",
             "大盘股、大宗商品", "长期国债"),
            ("late_cycle", "🌤️ 周期末期",
             "增长放缓，通胀升温，央行收紧",
             "防御板块、黄金", "成长股"),
            ("stagflation", "🔥 滞胀期",
             "经济停滞+高通胀，被迫加息",
             "黄金、商品、TIPS", "股票、长债"),
            ("recession", "❄️ 衰退期",
             "GDP负增长，失业飙升，紧急降息",
             "长期国债、现金", "股票、商品"),
            ("transition", "🔄 过渡期",
             "信号混合，方向不明",
             "均衡配置", "避免集中"),
        ]

        for key, name, features, best, worst in cycle_ref:
            if key == current:
                self._w(f"**👉 {name} ← 当前**")
            else:
                self._w(f"**{name}**")
            self._w(f"> {features}")
            self._w(f"> 最优: {best} / 最差: {worst}")
            self._w()

        alloc = cycle["allocation"]
        self._w("### 📊 推荐资产配置")
        self._w()
        labels = {
            "stocks": "📈 股票", "long_bonds": "🏛️ 长期国债", "cash": "💵 现金/短债",
            "gold": "🥇 黄金", "tips": "🛡️ TIPS通胀保护", "commodities": "🛢️ 大宗商品",
        }
        for key in ["stocks", "long_bonds", "cash", "gold", "tips", "commodities"]:
            weight, detail = alloc[key]
            self._w(f"- {labels[key]}: **{weight}**")
            self._w(f"  {detail}")
        self._w()

    def _leader_table(self):
        leaders = self.r["leader_health"]
        if not leaders:
            return

        self._w("## 🏢 龙头股健康度")
        self._w()
        for lh in leaders:
            icon = _md_icon(lh["status"])
            price = f"${lh['price']:.1f}" if lh["price"] else "N/A"
            vs50 = _md_val(lh["vs_ma50"], 1, "%") if lh["vs_ma50"] is not None else "N/A"
            ret = _md_val(lh["ret_20d"], 1, "%") if lh["ret_20d"] is not None else "N/A"
            self._w(f"- {icon} **{lh['name']}** {price} | MA50: {vs50} | 20日: {ret}")
        self._w()

    def _signals(self):
        signals = self.r["signals"]
        self._w("## 🔔 活跃信号")
        self._w()

        if not signals:
            self._w("> 🟢 当前无活跃信号")
            self._w()
            return

        sorted_signals = sorted(signals, key=lambda x: -abs(x["score"]))
        for s in sorted_signals:
            icon = _md_icon(s["level"])
            score_str = f"+{s['score']}" if s["score"] > 0 else str(s["score"])
            desc = f" — {s['desc']}" if s.get("desc") else ""
            self._w(f"- {icon} **[风险{score_str}]** {s['name']}{desc}")
        self._w()

    def _combos(self):
        combos = self.r["combos"]
        self._w("## ⚠️ 高危组合监控")
        self._w()

        for c in combos:
            detail = c.get("detail", "")
            if c["triggered"] is True:
                self._w(f"- 🔴 **{c['name']}** — 已触发！{detail}")
            elif c["triggered"] is False:
                extra = f" ({detail})" if detail else ""
                self._w(f"- ✅ {c['name']} — 未触发{extra}")
            else:
                self._w(f"- 👁 {c['name']} — {detail}")
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

        def _row(icon, name, val, ref):
            self._w(f"- {icon} **{name}**: {val}")
            self._w(f"  {ref}")

        self._w("### 💧 流动性")
        self._w()
        us10y = g.get("US10Y")
        _row(_md_icon('danger' if us10y and us10y > 4.5 else 'warning' if us10y and us10y > 4.0 else 'safe'),
             "US10Y", _md_val(us10y, suffix='%'),
             "<4.0% 利好(买) / >4.5% 压制估值(警惕) / >5.0% 强烈利空(卖)")

        us2y = g.get("US2Y")
        _row(_md_icon('warning' if us2y and us2y > 4.5 else 'safe'),
             "US2Y", _md_val(us2y, suffix='%'),
             "反映降息预期，快速下行=市场抢跑降息(利好)")

        tips = g.get("TIPS")
        _row(_md_icon('danger' if tips and tips > 2.0 else 'warning' if tips and tips > 1.5 else 'safe'),
             "TIPS实际利率", _md_val(tips, suffix='%'),
             "<1.5% 友好(买) / >2.0% 纳指承压(减仓)")

        t10y2y = g.get("T10Y2Y")
        curve_label = "倒挂" if t10y2y is not None and t10y2y < 0 else "正常"
        _row(_md_icon('danger' if t10y2y is not None and t10y2y < 0 else 'safe'),
             "10Y-2Y利差", f"{_md_val(t10y2y, suffix='%')} ({curve_label})",
             "倒挂预示衰退 / **解倒挂快速转正=最危险(强烈卖出)**")

        dxy = g.get("DXY")
        _row(_md_icon('danger' if dxy and dxy > 105 else 'warning' if dxy and dxy > 103 else 'safe'),
             "DXY", _md_val(dxy, 1),
             "<100 宽松(利好) / >103 偏紧 / >105 收紧(利空)")

        hy = g.get("HY_OAS")
        _row(_md_icon('danger' if hy and hy > 500 else 'warning' if hy and hy > 350 else 'safe'),
             "HY OAS", _md_val(hy, 0, 'bp') if hy else 'N/A',
             "<300bp 利好 / >500bp 利空 / >700bp 危机")

        m2 = g.get("M2_YOY")
        _row(_md_icon('safe' if m2 and m2 > 2 else 'warning' if m2 and m2 > 0 else 'danger' if m2 and m2 < 0 else 'safe'),
             "M2同比", _md_val(m2, 1, '%'),
             ">2% 流动性充裕(利好) / <0% 萎缩(利空)")

        self._w()
        self._w("### 😰 情绪")
        self._w()
        vix = g.get("VIX")
        _row(_md_icon('danger' if vix and vix > 30 else 'warning' if vix and vix > 20 else 'safe'),
             "VIX", _md_val(vix, 1),
             "<15 极平静 / 25-35 关注买入 / **>35 黄金坑**")

        vxn = g.get("VXN")
        _row(_md_icon('danger' if vxn and vxn > 35 else 'warning' if vxn and vxn > 25 else 'safe'),
             "VXN", _md_val(vxn, 1),
             "纳指专用恐慌指数 / **>40 极端恐慌(强烈买入)**")

        vt = g.get("VIX_TERM")
        vt_label = "倒挂" if vt and vt > 1 else "正常"
        _row(_md_icon('danger' if vt and vt > 1 else 'safe'),
             "VIX期限", f"{vt_label} ({_md_val(vt)})",
             ">1倒挂=真正恐慌，比VIX绝对值更可靠")

        skew = g.get("SKEW")
        _row(_md_icon('danger' if skew and skew > 150 else 'warning' if skew and skew > 140 else 'safe'),
             "SKEW", _md_val(skew, 0),
             ">140+VIX低=暗流涌动 / >150 极度焦虑")

        fg = g.get("FEAR_GREED")
        fg_label = g.get("FEAR_GREED_LABEL", "")
        _row(_md_icon('warning' if fg and (fg > 80 or fg < 20) else 'safe'),
             "恐惧贪婪", f"{_md_val(fg, 0)} {fg_label}",
             "<15 极度恐惧(配合VIX=买) / >85 贪婪(减仓)")

        self._w()
        self._w("### 🔮 领先指标")
        self._w()
        sox = g.get("SOX")
        _row(_md_icon('safe'),
             "SOX半导体", _md_val(sox, 0),
             "纳指领先指标，SOX先弱→纳指补跌")

        rsp_spy = g.get("RSP_SPY_20D_CHG")
        _row(_md_icon('danger' if rsp_spy and rsp_spy < -2 else 'warning' if rsp_spy and rsp_spy < -0.5 else 'safe'),
             "RSP/SPY 20日", _md_val(rsp_spy, 1, '%'),
             "下降=只有巨头撑场面(虚胖牛市)")

        self._w()
        self._w("### 🏛️ 宏观 & 技术面")
        self._w()
        sahm = g.get("SAHM")
        _row(_md_icon('danger' if sahm and sahm >= 0.5 else 'warning' if sahm and sahm >= 0.3 else 'safe'),
             "萨姆规则", _md_val(sahm),
             "<0.3 安全 / **≥0.5 衰退确认(强烈卖出)**")

        spy_pct = g.get("SPY_VS_MA200")
        _row(_md_icon('danger' if spy_pct is not None and spy_pct < 0 else 'safe'),
             "SPY vs MA200", _md_val(spy_pct, 1, '%'),
             ">0% 牛市(持有) / **<0% 熊市信号(减仓)**")

        qqq_pct = g.get("QQQ_VS_MA200")
        _row(_md_icon('danger' if qqq_pct is not None and qqq_pct < 0 else 'safe'),
             "QQQ vs MA200", _md_val(qqq_pct, 1, '%'),
             "纳指趋势，跌破MA200信号更强烈")

        spy_rsi = g.get("SPY_RSI")
        qqq_rsi = g.get("QQQ_RSI")
        _row(_md_icon('warning' if qqq_rsi and (qqq_rsi > 70 or qqq_rsi < 30) else 'safe'),
             "RSI(14)", f"SPY {_md_val(spy_rsi, 1)} / QQQ {_md_val(qqq_rsi, 1)}",
             "<30 超卖(配合VIX=买) / >70 看背离非绝对值")

        macd_status = "多头" if g.get("SPY_MACD_BULL") else "空头"
        _row(_md_icon('safe' if g.get('SPY_MACD_BULL') else 'danger'),
             "MACD", macd_status,
             "多头=趋势向上 / 空头=趋势向下")

        self._w()

    def _recommendation(self):
        rec = self.r["recommendation"]
        detail = self.r["recommendation_detail"]

        if "强烈卖出" in rec or "减仓" in rec:
            emoji = "🚨"
        elif "强烈买入" in rec or "买入" in rec:
            emoji = "💰"
        else:
            emoji = "📋"

        self._w("---")
        self._w()
        self._w(f"> {emoji} **操作建议: {rec}**")
        self._w(f">")
        self._w(f"> {detail}")
        self._w()
        self._w("---")
        self._w("*⚠️ 本工具仅供参考，不构成投资建议。投资有风险，决策需谨慎。*")

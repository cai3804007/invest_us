"""Anomaly detection and push gating.

The report used to be pushed every day. A daily notification that is usually
"nothing much" trains you to ignore it, which is exactly backwards — the one
day it matters is the day you skim past it. This module decides whether a run
is worth interrupting for, and says which anomaly triggered it.

Three kinds of anomaly, handled differently:

  event      One-off price action (a down streak, a gap down). Fires whenever
             the condition holds; it is inherently about "right now".
  transition A state flip (dropped below MA200, cycle changed, a new danger
             signal). Fires only on the day it changes — comparing against
             the previous run's stored state. Without this, "SPY below MA200"
             would alert every day for months.
  standing   An absolute condition that stays true for a while (VIX > 30,
             Sahm triggered). Fires on appearance, then is rate-limited to
             once every ALERT_REPEAT_DAYS so it neither spams nor disappears.
"""

import json
import os
from datetime import date, datetime

from config import (STATE_FILE, ALERT_LEVELS, ALERT_REPEAT_DAYS,
                    STREAK_MIN_DAYS, STREAK_MIN_DROP, DAY_DROP_PCT,
                    DRAWDOWN_TIERS, threshold, CORR_LEVELS, CYCLE_REFERENCE,
                    MA200_BUFFER_PCT, DRAWDOWN_RESET_PCT,
                    ALERT_PROFILE, ALERT_MUTE, DRAWDOWN_TIERS_BY_PROFILE,
                    FG_ALERT_FEAR, FG_ALERT_GREED)

# key -> Chinese label, so alert titles read as names rather than as the
# internal cycle keys ("recovery → expansion").
_CYCLE_CN = {k: name for k, name, *_ in CYCLE_REFERENCE}

CRITICAL, WARNING, INFO = "critical", "warning", "info"

_LEVEL_ORDER = {CRITICAL: 0, WARNING: 1, INFO: 2}


# ----------------------------------------------------------------------
# State persistence
# ----------------------------------------------------------------------

def load_state(path=None):
    path = path or STATE_FILE
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        # A corrupt state file must not break the run; treat it as a first run.
        return {}


def snapshot(result, prev=None, confirmed=None, dd_deepest=None):
    """The subset of the analysis that transitions are computed against.

    `confirmed` / `dd_deepest` carry the hysteresis state forward: the MA200
    reading stored here is the *confirmed* side (only flipped once price moved
    beyond the buffer), not the raw comparison, and dd_deepest remembers which
    drawdown tier has already been announced.
    """
    g = result["indicators"]
    pa = result.get("price_action", {})
    prev = prev or {}
    confirmed = confirmed or {}
    return {
        "date": date.today().isoformat(),
        "risk_score": result["risk_score"],
        "risk_level": result["risk_level"],
        "danger_ids": sorted(s["id"] for s in result["signals"]
                             if s["level"] == "danger"),
        "cycle": (result.get("economic_cycle") or {}).get("cycle"),
        "spy_above_ma200": confirmed.get(
            "SPY", prev.get("spy_above_ma200", _above(g.get("SPY"), g.get("SPY_MA200")))),
        "qqq_above_ma200": confirmed.get(
            "QQQ", prev.get("qqq_above_ma200", _above(g.get("QQQ"), g.get("QQQ_MA200")))),
        "dd_deepest": dd_deepest if dd_deepest is not None else (prev.get("dd_deepest") or {}),
        "weekly_cross": g.get("SPY_WEEKLY_CROSS"),
        "drawdown_52w": pa.get("drawdown_52w", {}),
        "position_actions": {k: v.get("action_level")
                             for k, v in (result.get("position_signals") or {}).items()},
        "recommendation": result["recommendation"],
    }


def save_state(result, alerts, path=None, prev=None, engine=None):
    """Persist the snapshot plus when each alert last fired (for rate limiting)."""
    path = path or STATE_FILE
    state = snapshot(result, prev=prev,
                     confirmed=getattr(engine, "confirmed_ma200", None),
                     dd_deepest=getattr(engine, "dd_deepest", None))
    fired = dict((prev or {}).get("last_fired", {}))
    today = date.today().isoformat()
    for a in alerts:
        fired[a["id"]] = today
    state["last_fired"] = fired
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)          # atomic: never leave a half-written state
    return state


def _above(price, ma):
    if price is None or ma is None:
        return None
    return price > ma


def _days_since(iso):
    if not iso:
        return None
    try:
        return (date.today() - datetime.fromisoformat(iso).date()).days
    except ValueError:
        return None


# ----------------------------------------------------------------------
# Alert engine
# ----------------------------------------------------------------------

class AlertEngine:

    def __init__(self, result, prev_state=None):
        self.r = result
        self.g = result["indicators"]
        self.prev = prev_state or {}
        self.alerts = []
        # Hysteresis state, carried into the next run via save_state().
        self.confirmed_ma200 = {}
        self.dd_deepest = dict(self.prev.get("dd_deepest") or {})

    # -- helpers -------------------------------------------------------

    def _add(self, aid, level, title, detail="", category="event"):
        # ALERT_PROFILE 决定哪些报警与当前用法无关。静音发生在这里，
        # 所以检测逻辑本身不必知道用户的侧重。
        for muted in ALERT_MUTE.get(ALERT_PROFILE, ()):
            if aid.startswith(muted):
                return
        self.alerts.append({
            "id": aid, "level": level, "title": title,
            "detail": detail, "category": category,
        })

    def _standing(self, aid, level, title, detail=""):
        """Rate-limited: fires on appearance, then at most every N days."""
        since = _days_since(self.prev.get("last_fired", {}).get(aid))
        if since is not None and since < ALERT_REPEAT_DAYS:
            return
        suffix = f"（已持续 {since} 天）" if since else ""
        self._add(aid, level, title, detail + suffix, category="standing")

    @property
    def first_run(self):
        return not self.prev

    # -- detection -----------------------------------------------------

    def run(self):
        health = self.r.get("data_health") or {}
        if health.get("missing_critical"):
            self._add("DATA_MISSING", CRITICAL, "数据缺失，无法判断",
                      f"缺少 {', '.join(health['missing_critical'])}", "event")
            return self.alerts          # nothing else is trustworthy

        self._price_events()
        self._transitions()
        self._standing_conditions()
        self._opportunities()

        self.alerts.sort(key=lambda a: _LEVEL_ORDER[a["level"]])
        return self.alerts

    # A. price events
    def _price_events(self):
        pa = self.r.get("price_action", {})

        for name, st in (pa.get("streaks") or {}).items():
            days, cum = st["days"], st["cum_pct"]
            if days >= STREAK_MIN_DAYS and cum <= STREAK_MIN_DROP:
                level = CRITICAL if (days >= 5 or cum <= -5) else WARNING
                self._add(f"STREAK_{name}", level,
                          f"{name} 连续{days}天下跌",
                          f"累计 {cum:.1f}%", "event")

        for name, chg in (pa.get("day_change") or {}).items():
            if chg <= DAY_DROP_PCT:
                self._add(f"DAYDROP_{name}", WARNING,
                          f"{name} 单日大跌 {chg:.1f}%",
                          f"阈值 {DAY_DROP_PCT:.1f}%", "event")

        # Drawdown tiers ratchet: only a *deeper* tier than the one already
        # announced fires, and the memory resets only once the drawdown has
        # genuinely recovered. Comparing against yesterday's value (the old
        # approach) re-fired every time price wobbled across -10%, which
        # measured 10.3 alerts/year instead of 3.4.
        tiers = DRAWDOWN_TIERS_BY_PROFILE.get(ALERT_PROFILE, DRAWDOWN_TIERS)
        for name, dd in (pa.get("drawdown_52w") or {}).items():
            deepest = self.dd_deepest.get(name, 0.0) or 0.0
            if dd > DRAWDOWN_RESET_PCT:
                deepest = 0.0
            for tier in sorted(tiers):                 # deepest first
                if dd <= tier and deepest > tier:
                    deepest = tier
                    level = CRITICAL if tier <= -20 else WARNING
                    self._add(f"DRAWDOWN_{name}_{abs(tier):.0f}", level,
                              f"{name} 距52周高回撤跌破 {tier:.0f}%",
                              f"当前 {dd:.1f}%", "transition")
                    break
            self.dd_deepest[name] = deepest

    # B. transitions vs the previous run
    def _transitions(self):
        if self.first_run:
            return          # nothing to compare against; avoid a flood

        g, prev = self.g, self.prev

        # MA200 with a buffer band: a flip counts only once price has moved
        # more than MA200_BUFFER_PCT beyond the average. Hovering within a few
        # tenths of a percent of it is not news — unbuffered this fired 9.7
        # times a year, with the buffer 5.1.
        for name, key in (("SPY", "spy_above_ma200"), ("QQQ", "qqq_above_ma200")):
            price, ma = g.get(name), g.get(f"{name}_MA200")
            before = prev.get(key)
            if price is None or ma is None or not ma:
                continue
            gap = (price / ma - 1) * 100
            if before is None:
                self.confirmed_ma200[name] = gap > 0
                continue
            if before and gap < -MA200_BUFFER_PCT:
                self.confirmed_ma200[name] = False
                self._add(f"MA200_BREAK_{name}", CRITICAL,
                          f"{name} 跌破200日均线",
                          f"低于均线 {abs(gap):.1f}%（需超 {MA200_BUFFER_PCT:.0f}% 才确认）",
                          "transition")
            elif (not before) and gap > MA200_BUFFER_PCT:
                self.confirmed_ma200[name] = True
                self._add(f"MA200_RECLAIM_{name}", INFO,
                          f"{name} 收复200日均线",
                          f"高于均线 {gap:.1f}%", "transition")
            else:
                self.confirmed_ma200[name] = before      # 未确认，维持原状态

        # New danger signals — name them, that is the point of the alert.
        now_ids = {s["id"]: s for s in self.r["signals"] if s["level"] == "danger"}
        fresh = [i for i in now_ids if i not in set(prev.get("danger_ids", []))]
        if fresh:
            names = "、".join(now_ids[i]["name"] for i in fresh)
            self._add("NEW_DANGER", WARNING,
                      f"新增 {len(fresh)} 项危险信号", names, "transition")

        # Risk band escalation.
        # Matched most-specific-first: "低风险" is a substring of "中低风险",
        # so a naive scan in ascending order mislabels 中低风险 as 低风险.
        order = ["低风险", "中低风险", "中等风险", "高风险", "极高风险"]
        by_specificity = sorted(enumerate(order), key=lambda t: -len(t[1]))
        def band(lvl):
            if not lvl:
                return None
            for i, b in by_specificity:
                if b in lvl:
                    return i
            return None
        now_b, prev_b = band(self.r["risk_level"]), band(prev.get("risk_level"))
        if now_b is not None and prev_b is not None and now_b > prev_b:
            self._add("RISK_UP", WARNING,
                      f"风险等级上升: {order[prev_b]} → {order[now_b]}",
                      f"评分 {prev.get('risk_score')} → {self.r['risk_score']}",
                      "transition")

        cyc = (self.r.get("economic_cycle") or {})
        if cyc.get("cycle") and prev.get("cycle") and cyc["cycle"] != prev["cycle"]:
            was = _CYCLE_CN.get(prev["cycle"], prev["cycle"])
            now = _CYCLE_CN.get(cyc["cycle"], cyc["cycle"])
            self._add("CYCLE_SHIFT", CRITICAL,
                      f"经济周期切换: {was} → {now}",
                      cyc.get("cycle_desc", ""), "transition")

        if g.get("SPY_WEEKLY_CROSS") == "death" and prev.get("weekly_cross") != "death":
            self._add("WEEKLY_DEATH_CROSS", CRITICAL,
                      "SPY 周线死叉（21周下穿50周）",
                      "系统性撤退信号，但历史上触发时已跌约13%", "transition")

        prev_actions = prev.get("position_actions") or {}
        for name, sig in (self.r.get("position_signals") or {}).items():
            now_a, before_a = sig.get("action_level"), prev_actions.get(name)
            if not now_a or not before_a or now_a == before_a:
                continue
            if now_a in ("strong_buy", "buy"):
                lvl = CRITICAL if (ALERT_PROFILE == "accumulate"
                                   and now_a == "strong_buy") else WARNING
                self._add(f"POS_{name}", lvl,
                          f"{name} 加仓信号: {sig.get('action')}",
                          f"评分 {sig.get('final_score')}，建议仓位 {sig.get('position_change')}",
                          "transition")
            elif now_a in ("sell", "consider_sell"):
                self._add(f"POS_{name}", WARNING,
                          f"{name} 减仓信号: {sig.get('action')}",
                          f"评分 {sig.get('final_score')}", "transition")

    # C. standing conditions (rate-limited)
    def _standing_conditions(self):
        g = self.g

        vix = g.get("VIX")
        if vix is not None and vix > 30:
            self._standing("VIX_HIGH", WARNING, f"VIX 高位 {vix:.1f}", "恐慌区间")

        sahm = g.get("SAHM")
        if sahm is not None and sahm >= threshold("SAHM"):
            self._standing("SAHM", CRITICAL, f"萨姆规则触发 {sahm:.2f}",
                           "衰退确认指标（非领先）")

        hy = g.get("HY_OAS")
        if hy is not None and hy > threshold("HY_OAS"):
            self._standing("CREDIT_STRESS", CRITICAL,
                           f"信用利差 {hy:.0f}bp", "高于500bp，系统性风险")

        corr = g.get("STOCK_BOND_CORR")
        if corr is not None and corr > CORR_LEVELS["HEDGE_BROKEN"]:
            self._standing("HEDGE_BROKEN", INFO,
                           f"股债相关性 {corr:+.2f}", "长债当前不对冲股票")

    # D. actionable opportunities
    def _opportunities(self):
        g = self.g

        # 极端恐惧：analyzer 一直在算 FEAR_GREED，但报警层从未使用它。
        # 对"逢跌加码"的用法，这是最直接的一个机会提示。
        fg = g.get("FEAR_GREED")
        if fg is not None and fg < FG_ALERT_FEAR:
            level = CRITICAL if fg < 15 else WARNING
            self._standing("EXTREME_FEAR", level,
                           f"市场极度恐惧 (恐惧贪婪指数 {fg:.0f})",
                           f"低于 {FG_ALERT_FEAR:.0f}，历史上多对应回调中后段")

        # 极端贪婪：加码侧重下也值得知道——不是叫你卖，而是提示别追高。
        if fg is not None and fg > FG_ALERT_GREED and ALERT_PROFILE == "accumulate":
            self._standing("EXTREME_GREED_NOTE", INFO,
                           f"市场极度贪婪 (恐惧贪婪指数 {fg:.0f})",
                           "定投照常，但不宜额外追加")

        rec = self.r.get("recommendation", "")
        if rec in ("强烈买入", "强烈卖出"):
            self._standing(f"REC_{rec}", CRITICAL, f"操作建议: {rec}",
                           self.r.get("recommendation_detail", ""))


# ----------------------------------------------------------------------
# Push decision
# ----------------------------------------------------------------------

def should_push(alerts, force=False, digest=False):
    """Push when something happened, when explicitly forced, or on a digest day."""
    if force or digest:
        return True
    return any(a["level"] in ALERT_LEVELS for a in alerts)


def alert_title(alerts, result):
    """Title naming the anomaly — the point is to be readable on a lock screen."""
    if not alerts:
        return None
    top = alerts[0]
    icon = {CRITICAL: "🚨", WARNING: "⚠️", INFO: "ℹ️"}[top["level"]]
    extra = f" +{len(alerts) - 1}项" if len(alerts) > 1 else ""
    return f"{icon} {top['title']}{extra}"


def render_alerts(alerts):
    """Markdown block placed at the very top of the report."""
    if not alerts:
        return []
    icons = {CRITICAL: "🚨", WARNING: "⚠️", INFO: "ℹ️"}
    labels = {"event": "价格异动", "transition": "状态变化", "standing": "持续condition"}
    labels["standing"] = "持续状态"
    out = ["## 🔔 本次触发的异常", ""]
    for a in alerts:
        tag = labels.get(a["category"], "")
        line = f"- {icons[a['level']]} **{a['title']}**"
        if a["detail"]:
            line += f" — {a['detail']}"
        if tag:
            line += f"  `{tag}`"
        out.append(line)
    out.append("")
    return out

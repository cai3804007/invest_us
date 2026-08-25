"""Rebalancing checks — 《经济周期长期投资策略》五、再平衡策略.

That chapter is the most mechanical part of the whole strategy ("再平衡是纪律，
不是判断") and was the only chapter with no implementation at all. It defines:

  * 日历触发   — quarterly, on the first trading day of Jan/Apr/Jul/Oct
  * 阈值触发   — any class off target by ±5pp enters观察期, ±10pp forces action
  * 缓冲带规则1 — a ±5pp breach must hold for 3 consecutive sessions
  * 缓冲带规则2 — a trade below max(1% of portfolio, $2,000) is deferred

Rule 1 needs memory across runs, so deviation streaks are persisted in
STATE_FILE. Everything here is inert until the user supplies PORTFOLIO_FILE:
holdings are theirs to state, not for this tool to guess.
"""

import json
import os
from datetime import date

from config import ASSET_CLASSES, ASSET_LABELS

PORTFOLIO_FILE = os.environ.get("PORTFOLIO_FILE", "portfolio.json")
STATE_FILE = os.environ.get("REBALANCE_STATE_FILE", ".rebalance_state.json")

OBSERVE_BAND_PP = 5.0        # ±5pp -> 进入观察期
FORCE_BAND_PP = 10.0         # ±10pp -> 强制立即再平衡
CONFIRM_SESSIONS = 3         # 连续 3 个交易日确认
MIN_TRADE_PCT = 1.0          # 最小起振: 组合的 1%
MIN_TRADE_ABS = 2000.0       # 或固定 $2,000，取较大者
QUARTER_MONTHS = (1, 4, 7, 10)


def _parse_range(text):
    """Midpoint of a weight string like '35-40%' or '10%'."""
    nums = []
    cur = ""
    for ch in str(text):
        if ch.isdigit() or ch == ".":
            cur += ch
        elif cur:
            nums.append(float(cur))
            cur = ""
    if cur:
        nums.append(float(cur))
    return sum(nums) / len(nums) if nums else 0.0


def target_weights(allocation):
    """Normalised target weights in percent.

    The document's ranges are midpoint-summed to 92-100% depending on the
    phase, so the midpoints are rescaled to 100%. Without this the "target"
    would leave several percent of the portfolio unassigned and every
    deviation would be measured against a total that isn't one.
    """
    mids = {k: _parse_range(allocation[k][0]) for k in ASSET_CLASSES}
    total = sum(mids.values())
    if total <= 0:
        return {k: 0.0 for k in ASSET_CLASSES}
    return {k: v / total * 100.0 for k, v in mids.items()}


def load_portfolio(path=None):
    """Return (holdings, error). holdings maps asset class -> market value."""
    path = path or PORTFOLIO_FILE
    if not os.path.exists(path):
        return None, None
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception as e:
        return None, f"{path} 解析失败 ({type(e).__name__}: {e})"

    holdings = raw.get("holdings", raw)
    if not isinstance(holdings, dict):
        return None, f"{path} 缺少 holdings 字段"

    cleaned, unknown = {}, []
    for k, v in holdings.items():
        if k not in ASSET_CLASSES:
            unknown.append(k)
            continue
        try:
            cleaned[k] = float(v)
        except (TypeError, ValueError):
            return None, f"{path} 中 {k} 的数值无效: {v!r}"
    if not cleaned:
        return None, f"{path} 未包含任何已知资产类别 {ASSET_CLASSES}"
    if unknown:
        return cleaned, f"忽略未知资产类别: {', '.join(unknown)}"
    return cleaned, None


def _load_state(path=None):
    path = path or STATE_FILE
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {"streaks": {}, "last_seen": None}


def _save_state(state, path=None):
    path = path or STATE_FILE
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def is_quarterly_rebalance_day(today=None):
    today = today or date.today()
    return today.month in QUARTER_MONTHS and today.day <= 5


def analyse(allocation, today=None, portfolio_path=None, state_path=None,
            persist=True):
    """Compare holdings against the cycle's target weights.

    Returns None when no portfolio file is present, so the report simply omits
    the section rather than inventing positions.
    """
    holdings, load_err = load_portfolio(portfolio_path)
    if holdings is None:
        return {"available": False, "error": load_err} if load_err else None

    today = today or date.today()
    total = sum(holdings.values())
    if total <= 0:
        return {"available": False, "error": "组合总市值为 0，无法计算偏离"}

    targets = target_weights(allocation)
    state = _load_state(state_path)
    streaks = dict(state.get("streaks") or {})
    # Only advance a streak once per calendar day, so re-running the tool
    # several times in one session cannot fake a 3-session confirmation.
    same_day = state.get("last_seen") == today.isoformat()

    min_trade = max(total * MIN_TRADE_PCT / 100.0, MIN_TRADE_ABS)
    rows, actions = [], []

    for key in ASSET_CLASSES:
        value = holdings.get(key, 0.0)
        current = value / total * 100.0
        target = targets[key]
        dev = current - target
        trade_value = abs(dev) / 100.0 * total

        prev = int(streaks.get(key, 0))
        if abs(dev) >= OBSERVE_BAND_PP:
            streak = prev if same_day else prev + 1
        else:
            streak = 0
        streaks[key] = streak

        if abs(dev) >= FORCE_BAND_PP:
            status, reason = "force", f"偏离 {dev:+.1f}pp ≥ ±{FORCE_BAND_PP:.0f}pp，强制立即再平衡"
        elif abs(dev) >= OBSERVE_BAND_PP and streak >= CONFIRM_SESSIONS:
            status, reason = "trigger", f"偏离 {dev:+.1f}pp 已连续 {streak} 日超阈值，触发再平衡"
        elif abs(dev) >= OBSERVE_BAND_PP:
            status, reason = "observe", (
                f"偏离 {dev:+.1f}pp，观察期第 {streak}/{CONFIRM_SESSIONS} 日")
        else:
            status, reason = "ok", f"偏离 {dev:+.1f}pp，在缓冲带内"

        deferred = False
        if status in ("force", "trigger") and trade_value < min_trade:
            deferred = True
            reason += f"；但交易额 ${trade_value:,.0f} < 最小起振 ${min_trade:,.0f}，推迟至季度再平衡"

        rows.append({
            "key": key, "label": ASSET_LABELS[key],
            "value": value, "current": current, "target": target,
            "deviation": dev, "trade_value": trade_value,
            "streak": streak, "status": status, "reason": reason,
            "deferred": deferred,
            "direction": "卖出" if dev > 0 else "买入",
        })
        if status in ("force", "trigger") and not deferred:
            actions.append(rows[-1])

    quarterly = is_quarterly_rebalance_day(today)
    if persist:
        _save_state({"streaks": streaks, "last_seen": today.isoformat()}, state_path)

    return {
        "available": True,
        "error": load_err,
        "total": total,
        "rows": rows,
        "actions": actions,
        "quarterly_due": quarterly,
        "min_trade": min_trade,
        "summary": _summary(rows, actions, quarterly),
    }


def _summary(rows, actions, quarterly):
    if quarterly:
        return "季度再平衡窗口：按目标权重全面校准"
    if actions:
        names = "、".join(f"{a['label']}{a['direction']}" for a in actions)
        return f"需执行再平衡：{names}"
    observing = [r for r in rows if r["status"] == "observe"]
    if observing:
        names = "、".join(f"{r['label']}({r['streak']}/{CONFIRM_SESSIONS})" for r in observing)
        return f"观察期：{names}"
    deferred = [r for r in rows if r["deferred"]]
    if deferred:
        return "有偏离但交易额低于最小起振金额，推迟至季度再平衡"
    return "各类资产均在缓冲带内，无需操作"

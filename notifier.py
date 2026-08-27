import os
import re
import requests
from config import SERVERCHAN3_SENDKEY, REPORT_TYPE_LABEL

SERVERCHAN_TITLE_LIMIT = 32


def _parse_uid(sendkey):
    """Extract uid from sendkey format: sctp{uid}t..."""
    m = re.match(r"^sctp(\d+)t", sendkey)
    return m.group(1) if m else None


def build_report_title(result, type_label=None, alerts=None):
    """Build the push title from an analysis result.

    Single definition shared by every caller — this logic previously existed
    in three near-identical copies (both branches of main() and an inline
    `python -c` block in the CI workflow).
    """
    label = REPORT_TYPE_LABEL if type_label is None else type_label
    prefix = f"[{label}] " if label else ""

    health = result.get("data_health") or {}
    if health.get("missing_critical"):
        return f"{prefix}⚠️ 美股监控 | 数据不足，未出结论"

    # When an anomaly triggered the push, the title should say which one —
    # "风险35 中低风险" on a lock screen tells you nothing actionable.
    alerts = alerts if alerts is not None else result.get("alerts") or []
    if alerts:
        icons = {"critical": "🚨", "warning": "⚠️", "info": "ℹ️"}
        top = alerts[0]
        head = f"{prefix}{icons.get(top['level'], '⚠️')} {top['title']}"
        if top.get("detail"):
            candidate = f"{head} ({top['detail']})"
            if len(candidate) <= SERVERCHAN_TITLE_LIMIT:
                head = candidate
        if len(alerts) > 1:
            more = f" +{len(alerts) - 1}项"
            if len(head) + len(more) <= SERVERCHAN_TITLE_LIMIT:
                head += more
        return head

    score = result["risk_score"]
    level = result["risk_level"]
    rec = result["recommendation"]

    # Strip any parenthetical caveat appended to the level so the title stays
    # inside Server酱's 32-character limit.
    level_short = level.split("（")[0]

    tags = []
    for name, sig in (result.get("position_signals") or {}).items():
        action = sig.get("action_level", "")
        if action in ("strong_buy", "buy"):
            tags.append(f"{name}加仓")
        elif action in ("consider_sell", "sell"):
            tags.append(f"{name}减仓")

    dangers = result.get("danger_count", 0)
    danger_note = f" ⚠️{dangers}" if dangers >= 3 else ""

    base = f"{prefix}📊 美股监控 | 风险{score}{danger_note} {level_short} | {rec}"

    # Server酱 caps the title at 32 characters. Append position tags only
    # while they fit whole, so the title never ends mid-tag ("| Q").
    for i in range(len(tags), 0, -1):
        candidate = base + " | " + "+".join(tags[:i])
        if len(candidate) <= SERVERCHAN_TITLE_LIMIT:
            return candidate
    return base


def push_to_serverchan(title, content, console=None):
    if not SERVERCHAN3_SENDKEY:
        if console:
            console.print("  [dim]未配置 SERVERCHAN3_SENDKEY，跳过推送[/]")
        return False

    if console:
        console.print("  [dim]Server酱³: 推送报告到手机...[/]")

    uid = _parse_uid(SERVERCHAN3_SENDKEY)
    if not uid:
        if console:
            console.print("  [red]Server酱³: SendKey 格式不正确，无法解析 uid[/]")
        return False

    try:
        url = f"https://{uid}.push.ft07.com/send/{SERVERCHAN3_SENDKEY}.send"

        short_desc = title[:100] if title else ""

        resp = requests.post(url, json={
            "title": title[:SERVERCHAN_TITLE_LIMIT],
            "desp": content,
            "short": short_desc,
        }, timeout=15)
        result = resp.json()

        if result.get("code") == 0:
            if console:
                console.print("  [green]Server酱³ 推送成功 ✓[/]")
            return True
        else:
            msg = result.get("message", str(result))
            if console:
                console.print(f"  [red]Server酱³ 推送失败: {msg}[/]")
            return False

    except Exception as e:
        if console:
            console.print(f"  [red]Server酱³ 推送异常: {e}[/]")
        return False


def push_markdown_file(path, type_label="", console=None):
    """Push an already-rendered Markdown report, taking its first heading as
    the title. Used by CI, which pushes even when the analysis step failed."""
    if not os.path.exists(path):
        msg = f"报告文件不存在: {path}"
        if console:
            console.print(f"  [red]{msg}[/]")
        else:
            print(msg)
        return False

    with open(path, encoding="utf-8") as fh:
        content = fh.read()

    if not content.strip():
        title = "⚠️ 美股监控 | 报告为空（运行失败）"
    else:
        title = content.split("\n", 1)[0].lstrip("# ").strip() or "美股监控报告"

    if type_label:
        title = f"[{type_label}] {title}"

    return push_to_serverchan(title, content, console=console)

import re
import requests
from config import SERVERCHAN3_SENDKEY


def _parse_uid(sendkey):
    """Extract uid from sendkey format: sctp{uid}t..."""
    m = re.match(r"^sctp(\d+)t", sendkey)
    return m.group(1) if m else None


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
            "title": title[:32],
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

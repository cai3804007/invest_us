import json
import requests
from config import GEMINI_API_KEY, GEMINI_MODEL, ASSET_CLASSES, ASSET_LABELS


SYSTEM_PROMPT = """你是一位资深的美股分析师和长期投资顾问。根据以下市场数据、经济周期判断、活跃信号和实时新闻，给出简洁的市场研判。

要求：
1. 用中文回答
2. 先用一句话总结当前市场状态和所处的经济周期阶段
3. 分析最值得关注的2-3个风险/机会点
4. 结合新闻判断市场情绪和可能的短期方向
5. 基于经济周期给出长期资产配置建议（哪类资产应该增配/减配）
6. 给出明确的短期操作建议（加仓/持有/减仓）和理由
7. 总字数控制在500字以内
8. 不要使用markdown标题格式，直接输出纯文本段落"""


def generate_ai_summary(analysis_result, news_headlines="", console=None):
    if not GEMINI_API_KEY:
        if console:
            console.print("  [dim]未配置 GEMINI_API_KEY，跳过 AI 分析[/]")
        return ""

    if console:
        console.print("  [dim]Gemini AI: 生成智能分析...[/]")

    data_summary = _build_data_summary(analysis_result)
    user_prompt = f"""## 当前市场数据

{data_summary}

## 实时新闻

{news_headlines if news_headlines else "暂无实时新闻数据"}

请根据以上信息给出你的市场研判。"""

    try:
        url = (f"https://generativelanguage.googleapis.com/v1beta/"
               f"models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}")

        payload = {
            "contents": [{
                "parts": [{"text": f"{SYSTEM_PROMPT}\n\n{user_prompt}"}]
            }],
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 800,
            }
        }

        resp = requests.post(url, json=payload, timeout=30)
        result = resp.json()

        candidates = result.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            if parts:
                return parts[0].get("text", "")

        # A failure here used to print one dim line and drop the whole AI
        # section from the report — indistinguishable from "AI disabled".
        # Report it at warning level with the API's own message.
        if console:
            err = result.get("error", {})
            msg = err.get("message") or json.dumps(result, ensure_ascii=False)[:200]
            console.print(f"  [yellow]Gemini AI 失败 (HTTP {resp.status_code}, model={GEMINI_MODEL}): {msg}[/]")
            if err.get("status") == "PERMISSION_DENIED":
                console.print("  [yellow]→ 该 API key 所属项目被拒绝访问，需要在 Google AI Studio 侧处理，"
                              "换模型无效[/]")
        return ""

    except Exception as e:
        if console:
            console.print(f"  [yellow]Gemini AI 分析异常 (model={GEMINI_MODEL}): "
                          f"{type(e).__name__}: {e}[/]")
        return ""


def _build_data_summary(r):
    g = r["indicators"]
    lines = []

    lines.append(f"风险评分: {r['risk_score']}  风险等级: {r['risk_level']}")
    lines.append(f"危险信号数: {r.get('danger_count', 0)}")
    lines.append(f"市场阶段: {r['market_phase']}")
    lines.append(f"操作建议: {r['recommendation']}")

    health = r.get("data_health") or {}
    if health.get("missing_critical"):
        lines.append(f"⚠️ 关键数据缺失: {', '.join(health['missing_critical'])}"
                     " —— 以下指标不完整，请勿据此给出确定结论")
    elif health.get("missing_macro"):
        lines.append(f"注意: 宏观数据缺失 ({', '.join(health['missing_macro'])})")
    lines.append("")

    def _v(key, label, suffix=""):
        val = g.get(key)
        return f"{label}: {val:.2f}{suffix}" if val is not None else f"{label}: N/A"

    lines.append("--- 流动性 ---")
    lines.append(_v("US10Y", "US10Y", "%"))
    lines.append(_v("US2Y", "US2Y", "%"))
    lines.append(_v("TIPS", "TIPS实际利率", "%"))
    lines.append(_v("T10Y2Y", "10Y-2Y利差", "%"))
    lines.append(_v("DXY", "DXY"))
    lines.append(_v("HY_OAS", "HY OAS", "bp"))
    lines.append(_v("M2_YOY", "M2同比增速", "%"))
    lines.append("")

    lines.append("--- 情绪 ---")
    lines.append(_v("VIX", "VIX"))
    lines.append(_v("VXN", "VXN"))
    vt = g.get("VIX_TERM")
    lines.append(f"VIX期限结构: {'倒挂' if vt > 1 else '正常'} ({vt:.2f})"
                 if vt is not None else "VIX期限结构: N/A")
    lines.append(_v("SKEW", "SKEW"))
    lines.append(_v("FEAR_GREED", "恐惧贪婪指数"))
    lines.append("")

    lines.append("--- 技术面 ---")
    lines.append(_v("SPY_VS_MA200", "SPY vs MA200", "%"))
    lines.append(_v("QQQ_VS_MA200", "QQQ vs MA200", "%"))
    lines.append(_v("SPY_RSI", "SPY RSI"))
    lines.append(_v("QQQ_RSI", "QQQ RSI"))
    lines.append(f"MACD: {'多头' if g.get('SPY_MACD_BULL') else '空头'}")
    lines.append("")

    if r.get("signals"):
        lines.append("--- 活跃信号 ---")
        for s in sorted(r["signals"], key=lambda x: -abs(x["score"])):
            score_str = f"+{s['score']}" if s["score"] > 0 else str(s["score"])
            lines.append(f"[{score_str}] {s['name']}: {s.get('desc', '')}")
        lines.append("")

    if r.get("leader_health"):
        lines.append("--- 龙头股 ---")
        for lh in r["leader_health"]:
            vs50 = f"{lh['vs_ma50']:.1f}%" if lh["vs_ma50"] is not None else "N/A"
            ret = f"{lh['ret_20d']:.1f}%" if lh["ret_20d"] is not None else "N/A"
            lines.append(f"{lh['name']}: vs MA50={vs50}, 20日={ret}, 状态={lh['status']}")

    triggered = [c for c in r.get("combos", []) if c.get("triggered") is True]
    if triggered:
        lines.append("")
        lines.append("--- 已触发的高危组合 ---")
        for c in triggered:
            lines.append(f"⚠️ {c['name']}: {c.get('detail', '')}")

    cycle = r.get("economic_cycle")
    if cycle:
        lines.append("")
        lines.append("--- 经济周期判断 ---")
        lines.append(f"当前周期: {cycle['cycle_cn']}")
        lines.append(f"周期描述: {cycle['cycle_desc']}")
        lines.append(f"通胀水平: {cycle['inflation_label']}")
        lines.append(f"扩张信号: {cycle['expansion_score']}/10 ({', '.join(cycle['expansion_details'][:5])})")
        lines.append(f"衰退信号: {cycle['recession_score']}/10 ({', '.join(cycle['recession_details'][:5])})")
        lines.append("")
        lines.append("--- 推荐资产配置 ---")
        for key in ASSET_CLASSES:
            weight, detail = cycle["allocation"][key]
            lines.append(f"{ASSET_LABELS[key]}: {weight} ({detail})")

    return "\n".join(lines)

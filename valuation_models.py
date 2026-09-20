"""多锚点估值：用几套互相独立的经典理论交叉验证，而不是只信一个数。

## 为什么要重写这一层

原来的"建议买入价"只有一个隐含假设：**PE 会向自身历史分位回归**。
这是统计规律不是估值理论，有三个说不过去的漏洞：

  1. **没有成长调整** —— 一家成长永久性放缓的公司，它的 PE 本就该长期
     下移。均值回归在这种情况下是错的，会把"合理的重新定价"误读成"便宜"。
  2. **没有利率调整** —— 2021 年的 PE 中枢是零利率环境下形成的。用它当
     锚点，等于假设利率会回到那时候。
  3. **没有内在价值概念** —— 完全是相对估值。如果整个 6 年窗口都处在
     泡沫里，分位法会把泡沫价当成"正常"。

所以这里补上四套**绝对估值**方法作为参照，并保留原来的相对估值方法，
把它诚实地标注为"相对估值/均值回归"而不是"合理价"。

## 采用的理论

| 方法 | 理论来源 | 核心假设 | 对科技股的适配度 |
|------|---------|---------|----------------|
| 两阶段 DCF | Williams (1938) 股利贴现 → 自由现金流贴现 | 企业价值 = 未来自由现金流现值 | 高，但对输入极度敏感 |
| PEG | Peter Lynch《One Up on Wall Street》 | 合理 PE ≈ 盈利增速 | 中，成长稳定时有效 |
| FCF 收益率 | Buffett "owner earnings" | 自由现金流收益率应高于无风险利率+风险溢价 | 高 |
| 格雷厄姆成长公式 | Graham《Security Analysis》 | V = EPS × (8.5 + 2g)，按当期利率调整 | **低**，为1960年代重资产企业设计 |
| 历史 PE 分位 | 统计均值回归 | 倍数回归自身历史中枢 | 中，牛市中易高估 |

## 关键立场：给区间，不给点估计

四套方法给出的数往往相差一倍以上。这个**离散度本身就是信息** ——
它告诉你这家公司的价值有多不确定。硬把它们平均成一个"目标价"是
在制造虚假精度。所以对外输出的是区间和中位数，并显式给出离散度。
"""

import math

from config import (DCF_YEARS, DCF_TERMINAL_GROWTH, DCF_ERP, DCF_MIN_DISCOUNT,
                    DCF_MAX_GROWTH, DCF_GROWTH_FADE, FCF_REQUIRED_PREMIUM,
                    PEG_FAIR, GRAHAM_BASE_PE, GRAHAM_NORM_YIELD)


def owner_earnings(info):
    """归一化的可分配现金流，用 Buffett 的 owner earnings 口径。

    为什么不用 yfinance 的 freeCashflow：
      · 该字段与现金流量表对不上（MSFT 实测 16.5B vs 报表 67.0B）
      · 更重要的是，**当期 FCF 会被资本开支周期严重扭曲**。MSFT 资本开支
        3 年从 28B 增至 116B（AI 数据中心），用它做永续贴现等于假设这轮
        投资潮永远持续，算出的内在价值只有股价的 1/10 —— 那不是"便宜"
        的反面，那是模型用错了输入。

    Owner earnings ≈ 经营现金流 − 维持性资本开支。维持性资本开支用折旧
    近似（Buffett 本人的做法）：成长性资本开支是可选投资，不该从当期
    盈利能力里扣除。

    返回 (数值, 口径说明)。
    """
    ocf_hist = info.get("cf_ocf") or []
    dep_hist = info.get("cf_dep") or []
    fcf_hist = info.get("cf_fcf") or []

    ocf = next((v for v in ocf_hist if v), None)
    dep = next((v for v in dep_hist if v), None)
    if ocf and dep and ocf > 0 and dep > 0:
        return ocf - dep, f"OCF {ocf/1e9:.0f}B − 折旧 {dep/1e9:.0f}B"

    # 退路一：报表 FCF 的多年均值（跨过单年资本开支高峰）
    valid = [v for v in fcf_hist if v and v > 0]
    if len(valid) >= 2:
        avg = sum(valid) / len(valid)
        return avg, f"报表FCF {len(valid)}年均值 {avg/1e9:.0f}B"

    # 退路二：info 字段（已知不可靠，仅兜底）
    fcf = info.get("freeCashflow")
    if fcf and fcf > 0:
        return float(fcf), f"info.freeCashflow {fcf/1e9:.0f}B（口径存疑）"
    return None, "无可用现金流"


def _safe(v, lo=None, hi=None):
    """把 None / NaN / 越界值挡在计算之外。"""
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    if lo is not None and v < lo:
        return lo
    if hi is not None and v > hi:
        return hi
    return v


# ----------------------------------------------------------------------
# 1. 两阶段自由现金流贴现（DCF）
# ----------------------------------------------------------------------

def dcf_value(info, risk_free, erp=None, terminal_growth=None):
    """两阶段 DCF。

    第一阶段按当前增速逐年衰减 DCF_GROWTH_FADE，第二阶段进入永续增长。
    折现率用 CAPM：r = 无风险利率 + beta × 股权风险溢价。

    **必须知道的局限**：DCF 对输入极度敏感 —— 折现率或永续增长率变动
    1 个百分点，结果可能变动 30% 以上。所以它的作用是提供一个数量级
    参照，不是精确目标价。sensitivity() 会给出敏感度区间。
    """
    fcf, basis = owner_earnings(info)
    fcf = _safe(fcf)
    shares = _safe(info.get("sharesOutstanding"))
    if not fcf or not shares or fcf <= 0 or shares <= 0:
        return None, {"error": "现金流为负或数据缺失，DCF 不适用"}

    beta = _safe(info.get("beta"), 0.3, 3.0) or 1.0
    rf = _safe(risk_free, 0.0, 0.15)
    if rf is None:
        rf = 0.04
    erp = DCF_ERP if erp is None else erp
    discount = max(rf + beta * erp, DCF_MIN_DISCOUNT)

    g0 = _safe(info.get("revenueGrowth"), -0.5, DCF_MAX_GROWTH)
    if g0 is None:
        g0 = 0.05
    tg = DCF_TERMINAL_GROWTH if terminal_growth is None else terminal_growth
    if discount <= tg + 0.01:        # 永续增长必须显著低于折现率
        return None, {"error": "折现率过低，DCF 发散"}

    pv, g = 0.0, g0
    cf = fcf
    for yr in range(1, DCF_YEARS + 1):
        cf *= (1 + g)
        pv += cf / ((1 + discount) ** yr)
        g = tg + (g - tg) * DCF_GROWTH_FADE      # 增速向永续增长收敛

    terminal = cf * (1 + tg) / (discount - tg)
    pv += terminal / ((1 + discount) ** DCF_YEARS)

    net_cash = (_safe(info.get("totalCash")) or 0) - (_safe(info.get("totalDebt")) or 0)
    per_share = (pv + net_cash) / shares
    if per_share <= 0:
        # 净债务吃掉了全部现金流现值。这不是"股价便宜"的反面，而是
        # 这套模型对该公司不成立 —— 钳位成 0.01 会让它伪装成一个有效
        # 估值，并把区间下界拉到近零，污染离散度判断。
        return None, {"error": f"净债务超过现金流现值，DCF 不适用"
                               f"（净现金 {net_cash/1e9:.0f}B）"}
    return per_share, {
        "折现率": f"{discount*100:.1f}%（无风险{rf*100:.1f}% + β{beta:.2f}×{erp*100:.0f}%）",
        "初始增速": f"{g0*100:.1f}%（每年向{tg*100:.1f}%衰减）",
        "永续增长": f"{tg*100:.1f}%",
        "现金流口径": basis,
    }


def dcf_sensitivity(info, risk_free):
    """折现率 ±1pp、永续增长 ±0.5pp 的四角情形。

    存在的意义是让 DCF 的不确定性可见：如果四角之间差一倍，那这个
    "目标价"就不该被当成一个数来用。
    """
    vals = []
    for erp in (DCF_ERP - 0.01, DCF_ERP + 0.01):
        for tg in (DCF_TERMINAL_GROWTH - 0.005, DCF_TERMINAL_GROWTH + 0.005):
            v, _ = dcf_value(info, risk_free, erp=erp, terminal_growth=tg)
            if v:
                vals.append(v)
    return (min(vals), max(vals)) if vals else (None, None)


# ----------------------------------------------------------------------
# 2. PEG（Peter Lynch）
# ----------------------------------------------------------------------

def peg_value(info):
    """合理 PE ≈ 盈利增速（PEG = 1）。Lynch 的经验法则。

    局限：增速为负或极端时完全失效；对成熟期公司会系统性低估。
    """
    eps = _safe(info.get("trailingEps"))
    growth = _safe(info.get("earningsGrowth"))
    if growth is None:
        growth = _safe(info.get("revenueGrowth"))
    if not eps or eps <= 0 or growth is None:
        return None, {"error": "EPS 为负或无增速数据"}
    g_pct = growth * 100
    if g_pct <= 0:
        return None, {"error": f"盈利增速为负（{g_pct:.0f}%），PEG 不适用"}
    g_pct = min(g_pct, 40.0)        # 增速上限，避免把一次性暴增外推成永久
    fair_pe = g_pct * PEG_FAIR
    return eps * fair_pe, {
        "合理PE": f"{fair_pe:.1f}（增速 {g_pct:.0f}% × PEG {PEG_FAIR}）",
        "TTM EPS": f"{eps:.2f}",
    }


# ----------------------------------------------------------------------
# 3. 自由现金流收益率（Buffett owner earnings）
# ----------------------------------------------------------------------

def fcf_yield_value(info, risk_free):
    """要求的 FCF 收益率 = 无风险利率 + 风险溢价，反推价格。"""
    fcf, basis = owner_earnings(info)
    fcf = _safe(fcf)
    shares = _safe(info.get("sharesOutstanding"))
    if not fcf or not shares or fcf <= 0 or shares <= 0:
        return None, {"error": "现金流为负或数据缺失"}
    rf = _safe(risk_free, 0.0, 0.15)
    if rf is None:
        rf = 0.04
    required = rf + FCF_REQUIRED_PREMIUM
    fcf_ps = fcf / shares
    return fcf_ps / required, {
        "要求收益率": f"{required*100:.1f}%（无风险{rf*100:.1f}% + 溢价{FCF_REQUIRED_PREMIUM*100:.0f}%）",
        "每股现金流": f"{fcf_ps:.2f}",
        "口径": basis,
    }


# ----------------------------------------------------------------------
# 4. 格雷厄姆成长公式（按利率调整）
# ----------------------------------------------------------------------

def graham_value(info, risk_free):
    """V = EPS × (8.5 + 2g) × 4.4 / Y

    Graham 原式针对 1960 年代 AAA 公司债收益率 4.4% 标定。这里按当期
    利率调整。**对科技股适配度低** —— 它假设的是重资产、低成长、
    盈利稳定的工业企业，纳入是作为保守下限参照，不是主要依据。
    """
    eps = _safe(info.get("trailingEps"))
    growth = _safe(info.get("earningsGrowth")) or _safe(info.get("revenueGrowth"))
    if not eps or eps <= 0 or growth is None:
        return None, {"error": "EPS 为负或无增速"}
    g = min(max(growth * 100, 0.0), 20.0)     # Graham 建议增速上限约 20%
    y = (_safe(risk_free, 0.01, 0.15) or 0.04) * 100
    val = eps * (GRAHAM_BASE_PE + 2 * g) * GRAHAM_NORM_YIELD / y
    return val, {
        "公式": f"EPS {eps:.2f} × ({GRAHAM_BASE_PE} + 2×{g:.0f}) × {GRAHAM_NORM_YIELD}/{y:.1f}",
        "适配度": "低（为重资产工业企业设计）",
    }


# ----------------------------------------------------------------------
# 汇总
# ----------------------------------------------------------------------

MODEL_LABELS = {
    "dcf": "两阶段DCF",
    "peg": "PEG(Lynch)",
    "fcf": "FCF收益率",
    "graham": "格雷厄姆",
    "hist_pe": "历史PE分位",
}


def evaluate(info, risk_free, hist_pe_target=None, price=None):
    """跑全部模型，返回各自估值、区间、离散度。

    刻意不做加权平均 —— 各模型假设不同，平均出来的数没有理论含义。
    区间与离散度才是应该看的东西。
    """
    models, notes = {}, {}

    for key, fn in (("dcf", lambda: dcf_value(info, risk_free)),
                    ("peg", lambda: peg_value(info)),
                    ("fcf", lambda: fcf_yield_value(info, risk_free)),
                    ("graham", lambda: graham_value(info, risk_free))):
        try:
            val, meta = fn()
        except Exception as e:
            val, meta = None, {"error": f"{type(e).__name__}: {e}"}
        # 不钳位：钳位会把"发散/无意义"的结果伪装成一个数字。
        # 越界一律判为该模型不适用，并保留原因。
        val = _safe(val)
        if val is not None and not (0 < val < 1e6):
            meta = {"error": f"结果越界（{val:.3g}），模型不适用"}
            val = None
        models[key] = val
        notes[key] = meta

    if hist_pe_target:
        models["hist_pe"] = hist_pe_target
        notes["hist_pe"] = {"说明": "自身近6年PE中位数对应价格（相对估值）"}

    vals = sorted(v for v in models.values() if v)
    if not vals:
        return {"models": models, "notes": notes, "low": None, "high": None,
                "median": None, "dispersion": None, "vs_price": None, "count": 0}

    mid = vals[len(vals)//2] if len(vals) % 2 else (vals[len(vals)//2 - 1] + vals[len(vals)//2]) / 2
    dispersion = (max(vals) / min(vals)) if min(vals) > 0 else None
    vs_price = ((mid / price - 1) * 100) if price else None

    return {
        "models": models, "notes": notes,
        "low": min(vals), "high": max(vals), "median": mid,
        "dispersion": dispersion, "vs_price": vs_price, "count": len(vals),
    }

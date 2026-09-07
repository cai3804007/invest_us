"""七姐妹（Magnificent 7）基本面与估值判断。

设计上的两个立场，都和这个项目其他部分保持一致：

1. **估值用自身历史分位，不用固定 PE 阈值。**
   "PE > 30 就贵" 对 NVDA 和 AAPL 意味着完全不同的事，跨公司不可比；
   同一家公司的 PE 中枢也会随成长阶段漂移。这里和 SKEW 的处理一样，
   拿当前 PE 在它自己近 6 年分布里的分位来判断。

2. **便宜不等于该买。** 低 PE 分位可能是市场对基本面恶化的正确定价 ——
   也就是价值陷阱。所以估值分位必须和基本面质量一起看，两者背离时
   给出的是"价值陷阱风险"警告，而不是买入提示。

数据来源全部是 yfinance：
   · get_earnings_dates() 给到约 49 个季度的实际 EPS（可回溯至 2014）
   · info 给到成长率、利润率、ROE、FCF 等
基本面按季度变化，价格按天变化，所以 EPS 序列与 info 会被缓存，
PE 每次用最新价格重算。
"""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import yfinance as yf

from config import (MAG7_TICKERS, FUND_CACHE_FILE, FUND_CACHE_DAYS,
                    VAL_PCTILE_CHEAP, VAL_PCTILE_EXPENSIVE,
                    VAL_HISTORY_YEARS, QUALITY_LEVELS,
                    DISPERSION_TIGHT, DISPERSION_UNUSABLE)
import valuation_models as VM


# ----------------------------------------------------------------------
# 缓存：基本面按季度更新，没必要每次运行都拉
# ----------------------------------------------------------------------

def _load_cache(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        age_days = (time.time() - data.get("_fetched_at", 0)) / 86400
        if age_days > FUND_CACHE_DAYS:
            return {}
        # 去掉元数据键，让调用方拿到的永远是"ticker -> 数据"的干净字典，
        # 与首次抓取路径的返回结构一致
        return {k: v for k, v in data.items() if not k.startswith("_")}
    except (json.JSONDecodeError, OSError, TypeError):
        return {}


def _save_cache(path, payload):
    # 复制一份再写元数据：直接改 payload 会让"首次抓取"的返回值多出
    # _fetched_at 键，与"命中缓存"的返回结构不一致
    payload = dict(payload, _fetched_at=time.time())
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass          # 缓存写不了不该影响主流程


# ----------------------------------------------------------------------
# 取数
# ----------------------------------------------------------------------

def _fetch_one(ticker):
    """返回 (ttm_eps_series_as_dict, info_subset, error)。不抛异常。"""
    try:
        t = yf.Ticker(ticker)
        ed = t.get_earnings_dates(limit=60)
        ttm = {}
        if ed is not None and "Reported EPS" in ed:
            eps = ed["Reported EPS"].dropna().sort_index()
            if eps.index.tz is not None:
                eps.index = eps.index.tz_localize(None)
            if len(eps) >= 8:
                s = eps.rolling(4).sum().dropna()      # 滚动四季 = TTM EPS
                ttm = {d.strftime("%Y-%m-%d"): float(v) for d, v in s.items()}

        info = t.info or {}
        keep = ["trailingPE", "forwardPE", "priceToSalesTrailing12Months",
                "trailingPegRatio", "revenueGrowth", "earningsGrowth",
                "profitMargins", "operatingMargins", "returnOnEquity",
                "freeCashflow", "operatingCashflow", "marketCap", "shortName",
                "sharesOutstanding", "totalCash", "totalDebt", "beta",
                "trailingEps", "bookValue"]
        sub = {k: info.get(k) for k in keep}

        # 现金流量表：info 里的 freeCashflow 字段和报表对不上（MSFT 实测
        # 16.5B vs 报表 67.0B），且当期 FCF 会被资本开支周期严重扭曲。
        # 取报表原始项，交给估值层做 owner earnings 归一化。
        try:
            cf = t.cashflow
            if cf is not None and not cf.empty:
                def _row(*keys):
                    for idx in cf.index:
                        s = str(idx).lower()
                        if all(k in s for k in keys):
                            return [None if pd.isna(v) else float(v)
                                    for v in cf.loc[idx].tolist()[:4]]
                    return []
                sub["cf_ocf"] = _row("operating", "cash", "flow")
                sub["cf_capex"] = _row("capital", "expenditure")
                sub["cf_fcf"] = _row("free", "cash", "flow")
                sub["cf_dep"] = _row("depreciation")
        except Exception:
            pass          # 报表拿不到就退回 info 字段

        return ttm, sub, None
    except Exception as e:
        return {}, {}, f"{type(e).__name__}: {e}"


def fetch_fundamentals(console=None, cache_file=None):
    """并发抓取七姐妹的 EPS 历史与基本面，带缓存。"""
    cache_file = cache_file or FUND_CACHE_FILE
    cached = _load_cache(cache_file)
    if cached:
        if console:
            console.print("  [dim]七姐妹基本面: 使用缓存[/]")
        return cached, []

    if console:
        console.print(f"  [dim]七姐妹基本面: 拉取 {len(MAG7_TICKERS)} 家...[/]")

    out, errors = {}, []
    with ThreadPoolExecutor(max_workers=7) as pool:
        futures = {pool.submit(_fetch_one, tk): tk for tk in MAG7_TICKERS}
        for fut in as_completed(futures):
            tk = futures[fut]
            try:
                ttm, info, err = fut.result()
            except Exception as e:
                errors.append(f"基本面: {tk} 失败 ({e})")
                continue
            if err:
                errors.append(f"基本面: {tk} 失败 ({err})")
                continue
            out[tk] = {"ttm_eps": ttm, "info": info}

    if out:
        _save_cache(cache_file, out)
    return out, errors


# ----------------------------------------------------------------------
# 判断
# ----------------------------------------------------------------------

def _pe_history(ttm_eps, price_series):
    """还原历史 TTM PE 序列（历史价格 / 当时已公布的 TTM EPS）。"""
    if not ttm_eps or price_series is None or len(price_series) < 250:
        return None, None
    s = pd.Series({pd.Timestamp(k): v for k, v in ttm_eps.items()}).sort_index()
    px = price_series.tail(int(VAL_HISTORY_YEARS * 252))
    # 每个交易日用当时最近一次已公布的 TTM EPS
    aligned = s.reindex(px.index.union(s.index)).ffill().reindex(px.index)
    pe = (px / aligned).replace([np.inf, -np.inf], np.nan).dropna()
    pe = pe[pe > 0]
    if len(pe) < 250:
        return None, None
    return pe, float(aligned.iloc[-1])       # PE 序列 + 当前 TTM EPS


def _target_prices(pe_hist, ttm_eps_now):
    """把估值分位反推成价格。

    建议买入价不是拍脑袋定的，而是从**同一套分位框架**倒推：
        目标价 = 当前 TTM EPS × 该分位对应的 PE

    也就是"股价跌到多少，这只票的 PE 才会回到它自己历史上的便宜区间"。
    随每季财报更新 —— EPS 增长时目标价自动上移，这是特性不是 bug：
    一家还在成长的公司，它的合理买点本来就不该是三年前那个绝对价格。
    """
    if pe_hist is None or not ttm_eps_now or ttm_eps_now <= 0:
        return {}
    out = {}
    for label, q in (("deep", 0.10), ("buy", VAL_PCTILE_CHEAP),
                     ("watch", 0.40), ("rich", VAL_PCTILE_EXPENSIVE)):
        out[label] = float(pe_hist.quantile(q)) * ttm_eps_now
    return out


def _quality(info):
    """基本面质量：成长、盈利能力、现金流。返回 (评级, 得分, 说明)。"""
    notes, score = [], 0
    rev = info.get("revenueGrowth")
    eps = info.get("earningsGrowth")
    margin = info.get("profitMargins")
    roe = info.get("returnOnEquity")
    fcf = info.get("freeCashflow")

    if rev is not None:
        if rev >= QUALITY_LEVELS["REV_STRONG"]:
            score += 1; notes.append(f"营收+{rev*100:.0f}%")
        elif rev < 0:
            score -= 2; notes.append(f"营收{rev*100:.0f}% 负增长")
        elif rev < QUALITY_LEVELS["REV_WEAK"]:
            score -= 1; notes.append(f"营收仅+{rev*100:.0f}%")
    if eps is not None:
        if eps >= QUALITY_LEVELS["EPS_STRONG"]:
            score += 1; notes.append(f"盈利+{eps*100:.0f}%")
        elif eps < 0:
            score -= 2; notes.append(f"盈利{eps*100:.0f}% 下滑")
    if margin is not None:
        if margin >= QUALITY_LEVELS["MARGIN_STRONG"]:
            score += 1; notes.append(f"净利率{margin*100:.0f}%")
        elif margin < QUALITY_LEVELS["MARGIN_WEAK"]:
            score -= 1; notes.append(f"净利率仅{margin*100:.0f}%")
    if roe is not None and roe >= QUALITY_LEVELS["ROE_STRONG"]:
        score += 1; notes.append(f"ROE {roe*100:.0f}%")
    if fcf is not None and fcf <= 0:
        score -= 2; notes.append("自由现金流为负")

    rating = "strong" if score >= 3 else "weak" if score <= 0 else "ok"
    return rating, score, notes


def analyse(fund_data, price_lookup, risk_free=None):
    """把估值分位与基本面质量合成结论。

    price_lookup(ticker) -> 价格 Series（由 analyzer 传入，复用已抓好的数据）。
    """
    results = {}
    for tk in MAG7_TICKERS:
        entry = fund_data.get(tk)
        if not entry:
            results[tk] = {"ticker": tk, "verdict": "数据不足",
                           "valuation": None, "quality": None, "notes": []}
            continue

        info = entry.get("info") or {}
        px = price_lookup(tk)
        # 不假设调用方已清洗：yfinance 当天未收盘时会返回 NaN 行，
        # 一旦流入就会让现价和所有距离百分比变成 NaN
        if px is not None:
            px = px.dropna()
            if len(px) == 0:
                px = None
        pe_hist, eps_now = _pe_history(entry.get("ttm_eps"), px)
        price = float(px.iloc[-1]) if px is not None and len(px) else None

        if pe_hist is not None:
            pe = float(pe_hist.iloc[-1])
            pct = float((pe_hist <= pe).mean())
            med = float(pe_hist.median())
            targets = _target_prices(pe_hist, eps_now)
        else:
            pe = pct = med = None
            targets = {}

        q_rating, q_score, q_notes = _quality(info)

        # 绝对估值：四套经典模型交叉验证（DCF / PEG / FCF收益率 / 格雷厄姆）
        intrinsic = VM.evaluate(info, risk_free,
                                hist_pe_target=(med * eps_now if med and eps_now else None),
                                price=price)
        disp = intrinsic.get("dispersion")
        if disp is None:
            agreement = None
        elif disp <= DISPERSION_TIGHT:
            agreement = "tight"
        elif disp <= DISPERSION_UNUSABLE:
            agreement = "loose"
        else:
            agreement = "unusable"
        intrinsic["agreement"] = agreement

        if pct is None:
            valuation = None
        elif pct <= VAL_PCTILE_CHEAP:
            valuation = "cheap"
        elif pct >= VAL_PCTILE_EXPENSIVE:
            valuation = "expensive"
        else:
            valuation = "fair"

        # 合成结论。核心：便宜必须配得上基本面，否则是价值陷阱。
        if valuation == "cheap" and q_rating == "weak":
            verdict, level = "价值陷阱风险", "warn"
        elif valuation == "cheap" and q_rating in ("strong", "ok"):
            verdict, level = "估值偏低", "buy"
        elif valuation == "expensive" and q_rating == "weak":
            verdict, level = "估值偏高且基本面转弱", "sell"
        elif valuation == "expensive":
            verdict, level = "估值偏高", "trim"
        elif valuation == "fair":
            verdict, level = "估值中性", "hold"
        else:
            verdict, level = "估值数据不足", None

        buy_at = targets.get("buy")
        upside = ((buy_at / price - 1) * 100
                  if buy_at and price else None)   # 负数 = 还需下跌多少

        results[tk] = {
            "ticker": tk,
            "name": info.get("shortName") or tk,
            "price": price,
            "ttm_eps": eps_now,
            "target_deep": targets.get("deep"),
            "target_buy": buy_at,
            "target_watch": targets.get("watch"),
            "target_rich": targets.get("rich"),
            "to_buy_pct": upside,
            "intrinsic": intrinsic,
            "pe_ttm": pe,
            "pe_pctile": pct,
            "pe_median": med,
            "forward_pe": info.get("forwardPE"),
            "ps": info.get("priceToSalesTrailing12Months"),
            "peg": info.get("trailingPegRatio"),
            "rev_growth": info.get("revenueGrowth"),
            "eps_growth": info.get("earningsGrowth"),
            "margin": info.get("profitMargins"),
            "roe": info.get("returnOnEquity"),
            "valuation": valuation,
            "quality": q_rating,
            "quality_score": q_score,
            "verdict": verdict,
            "level": level,
            "notes": q_notes,
        }
    return results

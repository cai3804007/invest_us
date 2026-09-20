"""机构持仓（13F）与内部人交易（Form 4）监控。

数据全部来自 SEC EDGAR 官方接口，免费无需 key。

## 两类数据的时效性差异极大，用途完全不同

| 数据 | 申报时限 | 实际滞后 | 用途 |
|------|---------|---------|------|
| 13F  | 季末后 45 天 | **60~135 天** | 看巴菲特这类大师在买什么，参考性质 |
| Form 4 | 交易后 2 个工作日 | **1~5 天** | 内部人真金白银的买卖，时效性可用 |

**13F 的滞后必须反复强调**：你看到"巴菲特建仓 X"的时候，那笔交易可能是
四个月前做的，股价早已反映。学术上跟随 13F 的策略超额收益有限，主要
原因就是这个时滞。所以本模块把 13F 定位为**认知参考**而不是交易信号。

Form 4 不同：
  · 内部人**买入**（交易代码 P，公开市场买入）在学术研究中有一定预测力，
    多人同期买入（cluster buying）尤其如此 —— 内部人没有理由在预期
    下跌时自掏腰包买自家股票。
  · 内部人**卖出**信号弱得多。高管持股多来自股权激励，卖出常常只是
    分散化、缴税或行权后了结，与看空无关。本模块因此对买卖做**非对称
    处理**：P 类买入才提醒，卖出只在异常放量时提示。

交易代码：P=公开市场买入  S=卖出  A=授予  M=期权行权  F=缴税扣股  G=赠与
只有 P 和 S 是真正的市场交易，A/M/F/G 属于薪酬机制，本模块予以过滤。
"""

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta

import requests

from config import (SEC_USER_AGENT, SEC_CACHE_FILE, F13_INVESTORS,
                    INSIDER_TICKERS, INSIDER_LOOKBACK_DAYS,
                    INSIDER_MIN_VALUE, F13_MIN_CHANGE_PCT,
                    SEC_CACHE_MAX_FORM4)

_SEC_MIN_INTERVAL = 0.12          # SEC 限速 10 次/秒，留余量
_last_call = [0.0]
# 内部人交易用 3 个线程并发抓取，限速器必须加锁：无锁时三个线程会同时
# 读到相同的 _last_call、一起 sleep、再一起发请求，实测退化成 98 次/秒
# （SEC 上限 10 次/秒）。GitHub Actions 出口 IP 是共享的，被封会连累别人。
_rate_lock = threading.Lock()

_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")


def validate_user_agent(ua):
    """检查 UA 是否满足 SEC 要求。返回 (是否可用, 问题说明)。

    实测规则（对 www.sec.gov/Archives 端点，即真正拉文档的那个）：
      · 空 UA / 浏览器伪装 / 只有名字      -> 403
      · 必须包含形如 x@y.z 的邮箱          -> 200
      · a@b（无顶级域名）                  -> 403
      · GitHub noreply 邮箱                -> 403（想拿它规避暴露真实邮箱行不通）
      · 非 ASCII 字符                      -> requests 抛 UnicodeEncodeError

    注意 data.sec.gov 的 JSON 接口宽松得多（几乎什么都收），只有
    Archives 端点严格。所以本地只测 JSON 接口会产生"能用"的错觉。
    """
    if not ua or not ua.strip():
        return False, "未设置，SEC 会返回 403"
    try:
        ua.encode("latin-1")
    except UnicodeEncodeError:
        return False, "含非 ASCII 字符（HTTP 头不支持），请求会直接抛异常"
    if not _EMAIL_RE.search(ua):
        return False, "必须包含真实邮箱（格式 x@y.z），否则 Archives 端点返回 403"
    if "users.noreply.github.com" in ua:
        return False, "GitHub noreply 邮箱会被 SEC 拒绝，需用真实可达邮箱"
    if "example.com" in ua:
        return False, "还是占位邮箱，请换成你自己的"
    return True, None


def _get(url, timeout=20):
    """带限速的 SEC 请求。超限会被封 IP，这不是可以省的东西。

    sleep 必须在锁内：放到锁外会让多个线程同时醒来再一起发请求，
    等于没限速。
    """
    with _rate_lock:
        wait = _SEC_MIN_INTERVAL - (time.time() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.time()
    return requests.get(url, headers={"User-Agent": SEC_USER_AGENT}, timeout=timeout)


def _tag(block, tag):
    m = re.search(rf"<(?:\w+:)?{tag}>\s*(?:<value>)?(.*?)(?:</value>)?\s*</(?:\w+:)?{tag}>",
                  block, re.S)
    return m.group(1).strip() if m else None


# ----------------------------------------------------------------------
# 缓存
# ----------------------------------------------------------------------

def _load(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}


def _prune(cache):
    """限制缓存规模。

    Form 4 条目每天都会新增，不清理的话文件会无限增长（实测 78 条已 238KB）。
    13F / FIGI / CIK 映射是稳定数据，保留；只对 f4 做 LRU 式截断。
    """
    f4 = sorted(k for k in cache if k.startswith("f4:"))
    if len(f4) > SEC_CACHE_MAX_FORM4:
        for k in f4[:len(f4) - SEC_CACHE_MAX_FORM4]:
            cache.pop(k, None)
    return cache


def _save(path, data):
    data = _prune(data)
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass


# ----------------------------------------------------------------------
# 13F：机构季度持仓
# ----------------------------------------------------------------------

def _filing_list(cik, form, limit=4):
    r = _get(f"https://data.sec.gov/submissions/CIK{cik}.json")
    if r.status_code != 200:
        return [], f"HTTP {r.status_code}"
    rec = r.json().get("filings", {}).get("recent", {})
    out = []
    for i, f in enumerate(rec.get("form", [])):
        if f == form:
            out.append({"accession": rec["accessionNumber"][i],
                        "filed": rec["filingDate"][i],
                        "period": rec.get("reportDate", [None] * (i + 1))[i]})
            if len(out) >= limit:
                break
    return out, None


def _fetch_13f_holdings(cik, accession):
    """返回 {cusip: {"name","shares","value"}}，按 CUSIP 聚合。

    同一发行人可能出现多行（不同投资经理分别申报），必须合并，
    否则会把 Apple 的三行当成三个持仓。
    """
    acc = accession.replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}"
    r = _get(f"{base}/index.json")
    if r.status_code != 200:
        return {}, f"index HTTP {r.status_code}"
    names = [i["name"] for i in r.json()["directory"]["item"]
             if i["name"].endswith(".xml")]
    for name in names:
        rr = _get(f"{base}/{name}")
        if "infoTable" not in rr.text:
            continue
        holdings = {}
        for blk in re.findall(r"<infoTable>(.*?)</infoTable>", rr.text, re.S):
            cusip = _tag(blk, "cusip")
            if not cusip:
                continue
            try:
                val = float(_tag(blk, "value") or 0)
                sh = float(_tag(blk, "sshPrnamt") or 0)
            except ValueError:
                continue
            e = holdings.setdefault(cusip, {"name": _tag(blk, "nameOfIssuer") or cusip,
                                            "shares": 0.0, "value": 0.0})
            e["shares"] += sh
            e["value"] += val
        return holdings, None
    return {}, "未找到持仓表"


def compare_13f(cik, name, cache):
    """比较最近两期 13F，产出建仓/增持/减持/清仓。"""
    filings, err = _filing_list(cik, "13F-HR", limit=2)
    if err or len(filings) < 2:
        return None, err or "13F 期数不足"

    cur_f, prev_f = filings[0], filings[1]
    key_cur = f"13f:{cik}:{cur_f['accession']}"
    key_prev = f"13f:{cik}:{prev_f['accession']}"

    def _holdings(k, f):
        if k in cache:
            return cache[k]
        h, e = _fetch_13f_holdings(cik, f["accession"])
        if h:
            cache[k] = h
        return h

    cur, prev = _holdings(key_cur, cur_f), _holdings(key_prev, prev_f)
    if not cur or not prev:
        return None, "持仓表解析失败"

    # 同一公司的不同股份类别是独立 CUSIP（如 Alphabet 的 A 类/C 类），
    # 名称相同会造成"同一只票出现两次"的错觉，加尾号区分
    name_count = {}
    for h in list(cur.values()) + list(prev.values()):
        name_count[h["name"]] = name_count.get(h["name"], set())
    for cusip, h in list(cur.items()) + list(prev.items()):
        name_count[h["name"]].add(cusip)

    def label(cusip, h):
        if len(name_count.get(h["name"], ())) > 1:
            return f"{h['name']} ({cusip[-4:]})"
        return h["name"]

    new, added, trimmed, exited = [], [], [], []
    for cusip, c in cur.items():
        p = prev.get(cusip)
        if not p:
            new.append({"name": label(cusip, c), "cusip": cusip,
                        "shares": c["shares"], "value": c["value"]})
        elif p["shares"] > 0:
            pct = (c["shares"] / p["shares"] - 1) * 100
            if pct >= F13_MIN_CHANGE_PCT:
                added.append({"name": label(cusip, c), "cusip": cusip,
                                "pct": pct, "value": c["value"]})
            elif pct <= -F13_MIN_CHANGE_PCT:
                trimmed.append({"name": label(cusip, c), "cusip": cusip,
                                "pct": pct, "value": c["value"]})
    for cusip, p in prev.items():
        if cusip not in cur:
            exited.append({"name": label(cusip, p), "cusip": cusip,
                           "value": p["value"]})

    for lst, k in ((new, "value"), (added, "value"), (trimmed, "value"), (exited, "value")):
        lst.sort(key=lambda x: -x.get(k, 0))

    filed = date.fromisoformat(cur_f["filed"])
    period = date.fromisoformat(cur_f["period"]) if cur_f.get("period") else None
    return {
        "investor": name, "cik": cik,
        "period": cur_f.get("period"), "filed": cur_f["filed"],
        "stale_days": (date.today() - filed).days,
        "position_age_days": (date.today() - period).days if period else None,
        "new": new, "added": added, "trimmed": trimmed, "exited": exited,
        "total_value": sum(v["value"] for v in cur.values()),
        "positions": len(cur),
    }, None


# ----------------------------------------------------------------------
# 建仓成本估算
#
# **13F 不披露成交价、也不披露成交日期**，只报季末的持股数和市值。
# 所以"巴菲特的建仓价"这个数字在公开数据里根本不存在。
#
# 能推导的是：这笔建仓一定发生在该季度之内，因此该季度的价格区间就是
# 成本的上下界，成交量加权均价(VWAP)是一个合理的中心估计。下面所有
# "估算成本"都是这个意思，不是真实成交价。
# ----------------------------------------------------------------------

_figi_errors = []


def cusip_to_tickers(cusips, cache):
    """CUSIP -> 美股代码，走 OpenFIGI（免费，无 key 限速 25次/分钟）。"""
    _figi_errors.clear()
    out, todo = {}, []
    for c in cusips:
        key = f"figi:{c}"
        if key in cache:
            if cache[key]:
                out[c] = cache[key]
        else:
            todo.append(c)
    # OpenFIGI 无 API key 时每请求上限 10 条（超了返回 413），25次/分钟。
    # 之前写 20 一直 413，但错误被静默跳过，表现为 ticker 全是 None。
    batches = [todo[i:i + 10] for i in range(0, len(todo), 10)]
    for n, batch in enumerate(batches):
        if n:
            time.sleep(2.5)          # 仅批次之间等待，25次/分钟
        try:
            r = requests.post(
                "https://api.openfigi.com/v3/mapping",
                json=[{"idType": "ID_CUSIP", "idValue": c, "exchCode": "US"} for c in batch],
                headers={"Content-Type": "application/json"}, timeout=25)
            if r.status_code != 200:
                # 静默 continue 会让"代码映射失败"完全无声 —— 上次就是
                # 连续调用撞了 25次/分钟 限速，而我看到的只是 ticker 全是 None
                _figi_errors.append(
                    f"OpenFIGI HTTP {r.status_code}"
                    + ("（触发限速，25次/分钟）" if r.status_code == 429 else ""))
                continue
            for c, res in zip(batch, r.json()):
                d = res.get("data") or []
                tk = d[0].get("ticker") if d else None
                cache[f"figi:{c}"] = tk
                if tk:
                    out[c] = tk
        except Exception as e:
            # OpenFIGI 不可用只影响"新建仓成本估算"，不该拖垮整个 SEC 模块，
            # 但也不能完全没声音 —— 缺代码映射会让成本估算静默消失
            _figi_errors.append(f"OpenFIGI 映射失败 ({type(e).__name__}: {e})")
            continue
    return out


def quarter_cost_estimate(ticker, period_end):
    """建仓季度的价格区间与 VWAP。

    period_end 是 13F 报告期末（季末）。回看该季度的三个月。
    返回 (low, high, vwap, quarter_end_close)。
    """
    import yfinance as yf
    try:
        end = datetime.strptime(period_end, "%Y-%m-%d")
        start = end - timedelta(days=95)
        df = yf.Ticker(ticker).history(start=start.strftime("%Y-%m-%d"),
                                       end=(end + timedelta(days=2)).strftime("%Y-%m-%d"),
                                       auto_adjust=True)
        if df is None or df.empty or "Close" not in df:
            return None
        df = df.dropna(subset=["Close"])
        if df.empty:
            return None
        vol = df["Volume"].fillna(0)
        typical = (df["High"] + df["Low"] + df["Close"]) / 3
        vwap = float((typical * vol).sum() / vol.sum()) if vol.sum() > 0 else float(df["Close"].mean())
        return {
            "low": float(df["Low"].min()),
            "high": float(df["High"].max()),
            "vwap": vwap,
            "quarter_close": float(df["Close"].iloc[-1]),
            "days": len(df),
        }
    except Exception:
        return None


def enrich_new_positions(result, cache):
    """给所有变动补上股票代码，并给新建仓算估算成本区间。

    代码映射覆盖 new/added/trimmed/exited 四类 —— 摘要里显示 "KR" 比
    "KROGER CO" 短得多，手机上一行能放下更多信息。
    """
    buckets = [result.get(k) or [] for k in ("new", "added", "trimmed", "exited")]
    all_cusips = [x["cusip"] for b in buckets for x in b if x.get("cusip")]
    if not all_cusips:
        return result
    tmap = cusip_to_tickers(all_cusips, cache)
    for b in buckets:
        for item in b:
            if item.get("cusip"):
                item["ticker"] = tmap.get(item["cusip"])

    new = result.get("new") or []
    if not new:
        return result
    period = result.get("period")
    for item in new:
        tk = item.get("ticker")
        if not tk or not period:
            continue
        key = f"cost:{tk}:{period}"
        est = cache.get(key)
        if est is None:
            est = quarter_cost_estimate(tk, period)
            cache[key] = est or False
        if est:
            item["cost_est"] = est
            # 交叉校验：季末市值/股数 应约等于季末收盘价
            if item.get("shares"):
                implied = item["value"] / item["shares"]
                item["implied_close"] = implied
                qc = est.get("quarter_close")
                item["parse_ok"] = bool(qc and abs(implied / qc - 1) < 0.15)
    return result


# ----------------------------------------------------------------------
# Form 4：内部人交易
# ----------------------------------------------------------------------

def _parse_form4(cik, accession):
    acc = accession.replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}"
    r = _get(f"{base}/index.json")
    if r.status_code != 200:
        return []
    xmls = [i["name"] for i in r.json()["directory"]["item"]
            if i["name"].endswith(".xml")]
    for name in xmls:
        txt = _get(f"{base}/{name}").text
        if "<ownershipDocument" not in txt:
            continue
        owner = _tag(txt, "rptOwnerName") or "?"
        title = _tag(txt, "officerTitle") or (
            "董事" if _tag(txt, "isDirector") == "true" else
            "10%股东" if _tag(txt, "isTenPercentOwner") == "true" else "")
        symbol = _tag(txt, "issuerTradingSymbol")
        out = []
        for blk in re.findall(r"<nonDerivativeTransaction>(.*?)</nonDerivativeTransaction>",
                              txt, re.S):
            code = _tag(blk, "transactionCode")
            if code not in ("P", "S"):        # 只看真实市场交易
                continue
            try:
                shares = float(_tag(blk, "transactionShares") or 0)
                price = float(_tag(blk, "transactionPricePerShare") or 0)
            except ValueError:
                continue
            out.append({
                "symbol": symbol, "owner": owner, "title": title,
                "date": _tag(blk, "transactionDate"), "code": code,
                "shares": shares, "price": price, "value": shares * price,
            })
        return out
    return []


_map_lock = threading.Lock()


def _cik_for(ticker, cache):
    key = f"cik:{ticker}"
    if key in cache:
        return cache[key]
    if "ticker_map" not in cache:
        # 加锁：3 个线程并发时"检查后填充"会让每个线程各拉一次
        # 约 1MB 的全量映射表。双重检查避免拿到锁后重复拉取。
        with _map_lock:
            if "ticker_map" not in cache:
                r = _get("https://www.sec.gov/files/company_tickers.json")
                if r.status_code != 200:
                    return None
                cache["ticker_map"] = {v["ticker"]: str(v["cik_str"]).zfill(10)
                                       for v in r.json().values()}
    cik = cache["ticker_map"].get(ticker.upper())
    if cik:
        cache[key] = cik
    return cik


def insider_activity(ticker, cache):
    """近 INSIDER_LOOKBACK_DAYS 天的内部人真实买卖。"""
    cik = _cik_for(ticker, cache)
    if not cik:
        # 静默返回 None 会让"这只票的内部人监控已失效"完全不可见
        return {"ticker": ticker, "error": "无法解析 CIK（ticker 映射失败）",
                "buys": [], "sells": [], "buy_value": 0, "sell_value": 0,
                "buyers": 0, "sellers": 0}
    filings, err = _filing_list(cik, "4", limit=25)
    if err:
        return {"ticker": ticker, "error": f"申报列表获取失败: {err}",
                "buys": [], "sells": [], "buy_value": 0, "sell_value": 0,
                "buyers": 0, "sellers": 0}
    cutoff = date.today().toordinal() - INSIDER_LOOKBACK_DAYS
    txns = []
    for f in filings:
        try:
            if date.fromisoformat(f["filed"]).toordinal() < cutoff:
                break
        except ValueError:
            continue
        key = f"f4:{f['accession']}"
        if key in cache:
            txns.extend(cache[key])
            continue
        parsed = _parse_form4(cik, f["accession"])
        cache[key] = parsed
        txns.extend(parsed)

    buys = [t for t in txns if t["code"] == "P" and t["value"] >= INSIDER_MIN_VALUE]
    sells = [t for t in txns if t["code"] == "S" and t["value"] >= INSIDER_MIN_VALUE]
    return {
        "ticker": ticker,
        "buys": buys, "sells": sells,
        "buy_value": sum(t["value"] for t in buys),
        "sell_value": sum(t["value"] for t in sells),
        "buyers": len({t["owner"] for t in buys}),
        "sellers": len({t["owner"] for t in sells}),
    }


# ----------------------------------------------------------------------
# 对外入口
# ----------------------------------------------------------------------

def collect(console=None, cache_file=None, watch_tickers=None):
    cache_file = cache_file or SEC_CACHE_FILE
    cache = _load(cache_file)
    errors = []

    ok, why = validate_user_agent(SEC_USER_AGENT)
    if not ok:
        msg = f"SEC_USER_AGENT {why} —— 跳过 SEC 数据（13F/内部人）"
        if console:
            console.print(f"  [yellow]{msg}[/]")
        return {"f13": {}, "insiders": {}, "prices": {}}, [msg]

    if console:
        console.print(f"  [dim]SEC: 13F {len(F13_INVESTORS)} 家 / "
                      f"内部人 {len(INSIDER_TICKERS)} 只...[/]")

    f13 = {}
    for name, cik in F13_INVESTORS.items():
        try:
            res, err = compare_13f(cik, name, cache)
            if res:
                res = enrich_new_positions(res, cache)
                f13[name] = res
            elif err:
                errors.append(f"13F {name}: {err}")
        except Exception as e:
            errors.append(f"13F {name}: {type(e).__name__}: {e}")

    insiders = {}
    with ThreadPoolExecutor(max_workers=3) as pool:       # SEC 限速，别开太多
        futs = {pool.submit(insider_activity, tk, cache): tk for tk in INSIDER_TICKERS}
        for fut in as_completed(futs):
            tk = futs[fut]
            try:
                r = fut.result()
                if not r:
                    continue
                if r.get("error"):
                    errors.append(f"Form4 {tk}: {r['error']}")
                    continue
                if r["buys"] or r["sells"]:
                    insiders[tk] = r
            except Exception as e:
                errors.append(f"Form4 {tk}: {type(e).__name__}: {e}")

    # 观察名单（机构建仓成本）需要实时价，这些票通常不在主行情列表里
    prices = {}
    watch = set(watch_tickers or [])
    for r in f13.values():
        for it in (r.get("new") or []):
            if it.get("ticker"):
                watch.add(it["ticker"])
    if watch:
        try:
            import yfinance as yf
            hist = yf.download(list(watch), period="5d", progress=False,
                               auto_adjust=True)["Close"]
            if hasattr(hist, "columns"):
                for tk in watch:
                    if tk in hist.columns:
                        s = hist[tk].dropna()
                        if len(s):
                            prices[tk] = float(s.iloc[-1])
            else:                       # 单只票时是 Series
                s = hist.dropna()
                if len(s):
                    prices[list(watch)[0]] = float(s.iloc[-1])
        except Exception as e:
            errors.append(f"观察名单取价失败 ({type(e).__name__}: {e})")

    errors.extend(_figi_errors)
    _save(cache_file, cache)
    return {"f13": f13, "insiders": insiders, "prices": prices}, errors

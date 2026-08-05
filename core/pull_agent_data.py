#!/usr/bin/env python3
"""
core/pull_agent_data.py
- 拉 4 类数据（板块/微博/价格vs均价/量价），写到 mavis-portfolio/data/YYYY-MM-DD/
- 由 agent (我) 手动触发，触发 review.yml 前运行
- 失败不抛错，写 meta.json 标记 fallback=true
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
ROOT_DIR = SCRIPT_DIR.parent
DATA_DIR = ROOT_DIR / "data"

# 持仓（5 只）
HOLDINGS = [
    ("159516", "半导体设备ETF国泰"),
    ("588200", "科创芯片ETF嘉实"),
    ("516650", "有色金属ETF华夏"),
    ("159915", "创业板ETF易方达"),
    ("513260", "恒生科技ETF汇添富"),
]

CST = timezone(timedelta(hours=8))


def now_cst_str():
    return datetime.now(CST).strftime("%Y-%m-%d")


def write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _ak_call(fn, *args, retries=3, **kwargs):
    """akshare 调用加 retry（用户 8-2 决定 1 fail 不重试，但 K线容易被掐，给 3 次）"""
    import time
    last_err = None
    for i in range(retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_err = e
            if i < retries:
                wait = (i + 1) * 2  # 2s, 4s, 6s
                print(f"  ⚠️ retry {i+1}/{retries}: {type(e).__name__}, wait {wait}s")
                time.sleep(wait)
    raise last_err


def _tencent_kline(code: str, n: int = 240) -> list:
    """
    腾讯 K线（不靠 akshare，akshare 没了也能用）
    返回: list of [date, open, close, high, low, volume]
    """
    import urllib.request
    if code.startswith("6") or code.startswith("5"):
        market = "sh"
    else:
        market = "sz"
    full = f"{market}{code}"
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={full},day,,,{n},,qfq"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode("gbk", errors="ignore")
    import json
    data = json.loads(raw)
    return data.get("data", {}).get(full, {}).get("day", []) or data.get("data", {}).get(full, {}).get("qfqday", [])


def _tencent_quote(code: str) -> dict:
    """
    腾讯实时价 + 流通股本（算换手率要用）
    """
    import urllib.request
    import re
    if code.startswith("6") or code.startswith("5"):
        market = "sh"
    else:
        market = "sz"
    full = f"{market}{code}"
    url = f"https://qt.gtimg.cn/q={full}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = resp.read().decode("gbk", errors="ignore")
    m = re.search(r'="([^"]+)"', data)
    if not m:
        return {}
    parts = m.group(1).split("~")
    if len(parts) < 50:
        return {}
    return {
        "name": parts[1],
        "price": float(parts[3] or 0),
        "volume": float(parts[6] or 0),  # 成交量(手)
        "circulating_shares_yi": float(parts[44] or 0),  # 流通股本(亿股)
    }


def _calc_turnover(volume_shou: float, circulating_shares_yi: float) -> float:
    """
    算换手率 = 成交量(手) / 流通股本(亿股) × 100
    1手 = 100股, 1亿 = 1e8股
    """
    if circulating_shares_yi <= 0:
        return 0.0
    # 成交量(手) × 100 = 股数
    # 流通股本(亿股) × 1e8 = 股数
    shares_traded = volume_shou * 100
    total_shares = circulating_shares_yi * 1e8
    return round(shares_traded / total_shares * 100, 2)


def pull_price_vs_ma() -> dict:
    """
    每只持仓：当前价 vs MA20/MA60/MA120/年均价 + 换手率
    用腾讯 K线 + 实时价（不靠 akshare）
    """
    result = {}
    for code, name in HOLDINGS:
        try:
            klines = _tencent_kline(code, n=240)
            if not klines or len(klines) < 20:
                result[code] = {"name": name, "error": "K线数据不足"}
                continue
            close = [float(k[2]) for k in klines]
            current = close[-1]
            ma20 = sum(close[-20:]) / 20
            ma60 = sum(close[-60:]) / 60 if len(close) >= 60 else None
            ma120 = sum(close[-120:]) / 120 if len(close) >= 120 else None
            year_avg = sum(close) / len(close)
            year_max = max(close)
            year_min = min(close)
            year_pct = (current - year_min) / (year_max - year_min) if year_max > year_min else 0.5

            # 换手率 = 实时价拉
            quote = _tencent_quote(code)
            turnover = _calc_turnover(quote.get("volume", 0), quote.get("circulating_shares_yi", 0))

            result[code] = {
                "name": name,
                "current": round(current, 4),
                "ma20": round(ma20, 4),
                "ma60": round(ma60, 4) if ma60 else None,
                "ma120": round(ma120, 4) if ma120 else None,
                "year_avg": round(year_avg, 4),
                "year_max": round(year_max, 4),
                "year_min": round(year_min, 4),
                "year_pct": round(year_pct, 4),
                "turnover": turnover,  # 换手率%
                "above_ma20": current > ma20,
                "above_ma60": current > ma60 if ma60 else None,
                "above_ma120": current > ma120 if ma120 else None,
                "above_year_avg": current > year_avg,
            }
        except Exception as e:
            result[code] = {"name": name, "error": str(e)}
    return result


def pull_volume_price() -> dict:
    """
    量价配合：近 5 日量比 + 量价背离检测 + 换手率
    用腾讯 K线（不靠 akshare）
    """
    result = {}
    for code, name in HOLDINGS:
        try:
            klines = _tencent_kline(code, n=60)
            if not klines or len(klines) < 10:
                result[code] = {"name": name, "error": "K线数据不足"}
                continue
            closes = [float(k[2]) for k in klines]
            volumes = [float(k[5]) for k in klines]

            last_5_close = closes[-5:]
            last_5_vol = volumes[-5:]
            prev_20_vol = volumes[-20:-5] if len(volumes) >= 25 else volumes[:-5]
            avg_vol_20 = sum(prev_20_vol) / len(prev_20_vol) if prev_20_vol else 0

            recent_vol = sum(last_5_vol) / len(last_5_vol)
            vol_ratio = round(recent_vol / avg_vol_20, 2) if avg_vol_20 > 0 else 1.0

            price_change_5d = (last_5_close[-1] - last_5_close[0]) / last_5_close[0] * 100
            vol_change_5d = (last_5_vol[-1] - last_5_vol[0]) / max(last_5_vol[0], 1) * 100
            aligned = (price_change_5d > 0 and vol_change_5d > 0) or (price_change_5d < 0 and vol_change_5d < 0)
            divergent = abs(price_change_5d) > 3 and (price_change_5d * vol_change_5d < 0)

            # 换手率（用实时价拉）
            quote = _tencent_quote(code)
            turnover = _calc_turnover(quote.get("volume", 0), quote.get("circulating_shares_yi", 0))

            result[code] = {
                "name": name,
                "vol_ratio": vol_ratio,
                "price_change_5d": round(price_change_5d, 2),
                "vol_change_5d": round(vol_change_5d, 2),
                "turnover": turnover,
                "price_vol_aligned": aligned,
                "divergent": divergent,
                "signal": "看多" if (price_change_5d > 0 and vol_ratio > 1.2) else
                          "看空" if (price_change_5d < 0 and vol_ratio > 1.2) else
                          "震荡",
            }
        except Exception as e:
            result[code] = {"name": name, "error": str(e)}
    return result


def pull_sector_fundflow() -> dict:
    """
    板块资金流（行业 + 概念）
    东方财富 API（不靠 akshare）
    """
    import urllib.request
    import json

    result = {"industry": [], "concept": []}
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}

    # 行业资金流
    try:
        url = "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=10&po=1&np=1&fltt=2&invt=2&fid=f62&fs=m:90+t:2&fields=f12,f14,f3,f62,f184,f2,f20"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        for item in (data.get("data", {}).get("diff", []) or [])[:10]:
            result["industry"].append({
                "name": item.get("f14", ""),
                "change_pct": float(item.get("f3", 0)),
                "main_net_inflow": float(item.get("f62", 0)),
                "main_net_pct": float(item.get("f184", 0)),
            })
    except Exception as e:
        result["industry_error"] = str(e)

    # 概念资金流
    try:
        url = "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=10&po=1&np=1&fltt=2&invt=2&fid=f62&fs=m:90+t:3&fields=f12,f14,f3,f62,f184"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        for item in (data.get("data", {}).get("diff", []) or [])[:10]:
            result["concept"].append({
                "name": item.get("f14", ""),
                "change_pct": float(item.get("f3", 0)),
                "main_net_inflow": float(item.get("f62", 0)),
                "main_net_pct": float(item.get("f184", 0)),
            })
    except Exception as e:
        result["concept_error"] = str(e)

    return result


def pull_weibo() -> dict:
    """
    微博热搜 Top 30 + 关键词命中
    """
    import subprocess

    keywords = [
        "半导体", "芯片", "国产替代", "光模块", "大基金",
        "半导体设备", "黄金", "金饰", "金股", "有色金属",
        "港股", "恒生科技", "互联网",
        "创业板", "科创板",
        "AI", "算力", "寒武纪", "GPU",
        "韩国", "三星", "海力士", "SK",
    ]

    try:
        proc = subprocess.run(
            ["node", "/workspace/skills/weibo-hot-trend/scripts/weibo.js", "30"],
            capture_output=True, text=True, timeout=20
        )
        output = proc.stdout
    except Exception as e:
        return {"error": str(e), "matched": []}

    # 解析输出（提取标题行）
    import re
    titles = re.findall(r'^\s*\d+\.\s+(.+?)(?:\s+\[.*?\])?\s*$', output, re.MULTILINE)
    matched = []
    for t in titles[:30]:
        for kw in keywords:
            if kw in t:
                # 提取排名
                rank_match = re.search(r'^\s*(\d+)\.', output, re.MULTILINE)
                matched.append({"title": t.strip(), "keyword": kw})
                break

    return {
        "titles": [t.strip() for t in titles[:30]],
        "matched": matched,
        "matched_count": len(matched),
    }


def main():
    date_str = now_cst_str()
    out_dir = DATA_DIR / date_str
    out_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "date": date_str,
        "pulled_at": datetime.now(CST).isoformat(),
        "sources": {},
    }

    print(f"=== 拉数据 {date_str} ===")

    # 1. 价格 vs 均价
    try:
        data = pull_price_vs_ma()
        write_json(out_dir / "price_vs_ma.json", data)
        meta["sources"]["price_vs_ma"] = "ok"
        print(f"  ✅ 价格 vs 均价: {len(data)} 条")
    except Exception as e:
        meta["sources"]["price_vs_ma"] = f"error: {e}"
        print(f"  ❌ 价格 vs 均价: {e}")

    # 2. 量价配合
    try:
        data = pull_volume_price()
        write_json(out_dir / "volume_price.json", data)
        meta["sources"]["volume_price"] = "ok"
        print(f"  ✅ 量价配合: {len(data)} 条")
    except Exception as e:
        meta["sources"]["volume_price"] = f"error: {e}"
        print(f"  ❌ 量价配合: {e}")

    # 3. 板块资金 (8-5 删除:沙箱拉不到,数据源全被掐)

    # 4. 微博
    try:
        data = pull_weibo()
        write_json(out_dir / "weibo.json", data)
        meta["sources"]["weibo"] = "ok"
        meta["weibo_matched"] = data.get("matched_count", 0)
        print(f"  ✅ 微博: 命中 {data.get('matched_count', 0)} 条")
    except Exception as e:
        meta["sources"]["weibo"] = f"error: {e}"
        print(f"  ❌ 微博: {e}")

    # 5. meta
    all_ok = all(v == "ok" for v in meta["sources"].values())
    meta["fallback"] = not all_ok
    write_json(out_dir / "meta.json", meta)

    print(f"\n=== 完成 → {out_dir} ===")
    print(f"fallback = {meta['fallback']}")
    return 0 if not meta["fallback"] else 1


if __name__ == "__main__":
    sys.exit(main())

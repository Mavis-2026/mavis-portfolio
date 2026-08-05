"""
core/fetch.py - 数据拉取模块
- 新浪为主,腾讯为备
- 单只 ETF/指数,带超时和重试
- 失败抛异常(让上层决定怎么办)
"""
import json
import re
import time
import urllib.request
from typing import Dict, List, Optional

# 数据源
SINA_URL = "https://hq.sinajs.cn/list={codes}"
TENCENT_URL = "http://qt.gtimg.cn/q={codes}"

# 常用代码(持仓 + 指数)
HOLDING_CODES = ["sz159516", "sz159915", "sh588200", "sh516650", "sh513260"]
INDEX_CODES = ["sh000001", "sz399001", "sz399006"]  # 上证/深证/创业板


def _fetch_sina(codes: list, timeout: int = 5) -> Dict[str, Dict]:
    """
    新浪批量拉取
    返回 {code: {name, price, change_pct, ...}}
    """
    url = SINA_URL.format(codes=",".join(codes))
    req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read().decode("gbk")

    result = {}
    for line in data.strip().split("\n"):
        # 格式:var hq_str_sz159516="...";
        m = re.match(r'var hq_str_(\w+)="(.+)";', line)
        if not m:
            continue
        code = m.group(1)
        parts = m.group(2).split(",")
        if len(parts) < 32:
            continue
        try:
            result[code] = {
                "code": code,
                "name": parts[0],
                "price": float(parts[3]) if parts[3] else None,
                "prev_close": float(parts[2]) if parts[2] else None,
                "open": float(parts[1]) if parts[1] else None,
                "change_pct": None,  # 下面算
                "high": float(parts[4]) if parts[4] else None,
                "low": float(parts[5]) if parts[5] else None,
                "volume": float(parts[8]) if parts[8] else None,        # 成交量(手)
                "turnover": float(parts[9]) if parts[9] else None,      # 成交额(元)
            }
            if result[code]["price"] and result[code]["prev_close"]:
                result[code]["change_pct"] = round(
                    (result[code]["price"] - result[code]["prev_close"])
                    / result[code]["prev_close"] * 100, 2
                )
        except (ValueError, IndexError):
            continue
    return result


def _fetch_tencent(codes: list, timeout: int = 5) -> Dict[str, Dict]:
    """
    腾讯批量拉取(fallback)
    返回 {code: {name, price, change_pct, ...}}
    """
    url = TENCENT_URL.format(codes=",".join(codes))
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        data = resp.read().decode("gbk")

    result = {}
    for line in data.strip().split("\n"):
        # 格式:v_sz159516="1~..."
        m = re.match(r'v_(\w+)="(.+)";', line)
        if not m:
            continue
        code = m.group(1)
        parts = m.group(2).split("~")
        if len(parts) < 35:
            continue
        try:
            result[code] = {
                "code": code,
                "name": parts[1],
                "price": float(parts[3]) if parts[3] else None,
                "prev_close": float(parts[4]) if parts[4] else None,
                "open": float(parts[5]) if parts[5] else None,
                "change_pct": None,
                "high": float(parts[33]) if parts[33] else None,
                "low": float(parts[34]) if parts[34] else None,
            }
            if result[code]["price"] and result[code]["prev_close"]:
                result[code]["change_pct"] = round(
                    (result[code]["price"] - result[code]["prev_close"])
                    / result[code]["prev_close"] * 100, 2
                )
        except (ValueError, IndexError):
            continue
    return result


def fetch_quotes(codes: list, retries: int = 2) -> Dict[str, Dict]:
    """
    拉取行情(新浪优先,腾讯备胎)
    失败抛异常
    """
    last_err = None
    # 新浪
    for i in range(retries):
        try:
            data = _fetch_sina(codes)
            if data:
                return data
        except Exception as e:
            last_err = e
            if i < retries - 1:
                time.sleep(0.5)

    # 腾讯 fallback
    for i in range(retries):
        try:
            data = _fetch_tencent(codes)
            if data:
                return data
        except Exception as e:
            last_err = e
            if i < retries - 1:
                time.sleep(0.5)

    raise RuntimeError(f"数据拉取失败(新浪 + 腾讯):{last_err}")


def fetch_all() -> Dict[str, Dict]:
    """
    拉取所有需要的代码(持仓 + 指数)
    """
    all_codes = HOLDING_CODES + INDEX_CODES
    return fetch_quotes(all_codes)


if __name__ == "__main__":
    # 自测
    data = fetch_all()
    for code, info in data.items():
        print(f"{code} {info['name']}: ¥{info['price']} ({info['change_pct']:+.2f}%)")


def fetch_kline(code_with_ex: str, days: int = 365, timeout: int = 10) -> List[float]:
    """
    拉取 ETF 历史 K 线收盘价
    code_with_ex: "sz159516" / "sh588200"
    days: 取最近 N 天(默认 365 = 1 年估值分位)
    返回: [收盘价列表],按时间从早到晚
    """
    url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={code_with_ex}&scale=240&ma=no&datalen={days}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [float(d["close"]) for d in data]
    except Exception as e:
        print(f"⚠️ K线拉取失败 {code_with_ex}:{e}")
        return []


def fetch_valuation_percentile(code_with_ex: str, days: int = 365) -> Optional[float]:
    """
    拉取 K 线 + 算当前估值分位(**已做拆股复权**)
    days: 默认 365 = 1 年
    返回 0-1(0=历史最低,1=历史最高),失败返回 None

    **重要(2026-08-01):** 检测到拆股(单日 -15%)会反向调整历史价格
    避免"前复权陷阱"(未复权数据让分位失真)
    """
    from core.valuation import calc_percentile, adjust_for_splits
    raw = fetch_kline(code_with_ex, days)
    if not raw:
        return None

    # **拆股复权**(后复权)
    adjusted = adjust_for_splits(raw)

    current = adjusted[-1]  # 最新价(已复权)
    hist_excl_current = adjusted[:-1]  # 历史(已复权)
    return calc_percentile(current, hist_excl_current)


def fetch_valuation_drawdown(code_with_ex: str, days: int = 365) -> Optional[float]:
    """
    计算当前价距历史最高点的回撤(0-1,越大越深)
    已做拆股复权
    """
    from core.valuation import calc_drawdown, adjust_for_splits
    raw = fetch_kline(code_with_ex, days)
    if not raw:
        return None
    adjusted = adjust_for_splits(raw)
    current = adjusted[-1]
    hist = adjusted
    return calc_drawdown(current, hist)

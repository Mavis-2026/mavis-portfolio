"""
估值分位计算
- 简化:用近期 60 个交易日的相对位置估算
- 输入:当前价 + 历史价格序列
- 输出:0-1 的分位值(0=历史最低,1=历史最高)
- **重要(2026-08-01):加拆股复权** — 避免"前复权陷阱"
"""
from typing import List, Optional


def adjust_for_splits(prices: List[float], threshold: float = -0.15) -> List[float]:
    """
    检测拆股并反向调整(后复权)
    拆股:单日跌幅 > threshold(默认 -15%)
    处理:把拆股前的价格按 ratio 缩放,让序列连续
    返回:调整后的价格列表
    """
    n = len(prices)
    if n < 2:
        return prices.copy()

    adjusted = list(prices)

    # 从前往后找拆股点
    for i in range(1, n):
        change = (adjusted[i] - adjusted[i-1]) / adjusted[i-1]
        if change < threshold:  # 拆股
            ratio = adjusted[i] / adjusted[i-1]  # 后价/前价 (拆股比例)
            # 调整之前所有价格(乘以 ratio,让前段价格变低,变连续)
            for j in range(i):
                adjusted[j] *= ratio

    return adjusted


def calc_percentile(current: float, history: List[float]) -> float:
    """
    计算当前值在历史序列中的分位(0-1)
    history: 历史价格序列(不含当前)
    """
    if not history or current is None:
        return 0.5  # 无数据,默认中位

    sorted_h = sorted(history)
    n = len(sorted_h)

    # 当前值在排序序列中的位置
    pos = 0
    for i, v in enumerate(sorted_h):
        if current > v:
            pos = i + 1
        else:
            break

    return pos / n if n > 0 else 0.5


def adjust_add_line_by_valuation(percentile: float, base_line: float = 0.10) -> float:
    """
    根据估值分位调整加仓线
    - 估值分位 < 0.30:低估,加仓线 -8%(更早加仓)
    - 估值分位 0.30-0.70:正常,加仓线 -10%
    - 估值分位 > 0.70:高估,加仓线 -15%(更晚加仓)

    返回:加仓跌幅(0.08 / 0.10 / 0.15)
    """
    if percentile < 0.30:
        return 0.08
    elif percentile > 0.70:
        return 0.15
    else:
        return base_line


def get_valuation_label(percentile: float) -> str:
    """估值分位标签"""
    if percentile < 0.20:
        return "极度低估"
    elif percentile < 0.40:
        return "低估"
    elif percentile < 0.60:
        return "合理"
    elif percentile < 0.80:
        return "高估"
    else:
        return "极度高估"


def calc_drawdown(current: float, history: List[float]) -> float:
    """
    计算当前价距历史最高点的回撤(0-1)
    返回:0 表示现价 = 最高价,1 表示现价 = 最低点
    """
    if not history or current is None:
        return 0.0
    high = max(history)
    if high == 0:
        return 0.0
    return (high - current) / high


# ====== 景气 vs 周期 框架(2026-08-01 加入) ======

# 5 ETF 的赛道分类
ETF_CATEGORY = {
    "159516": "景气",  # 半导体设备
    "588200": "景气",  # 科创芯片
    "159915": "景气",  # 创业板
    "516650": "周期",  # 有色金属
    "513260": "周期",  # 恒生科技(价值修复)
}


def get_add_strategy(percentile: float, category: str, drawdown: float) -> dict:
    """
    基于估值分位 + 赛道类型 + 距高点回撤的加仓策略

    景气赛道(高估值容忍):70-95% 正常,>95% 暂停
    周期赛道(低估值容忍):30-70% 正常,>70% 警惕,<30% 重仓

    双确认:分位达标 + 距高点回撤 > 15%
    """
    # 分位档位
    if percentile >= 0.95:
        p_level = 5
    elif percentile >= 0.80:
        p_level = 4
    elif percentile >= 0.60:
        p_level = 3
    elif percentile >= 0.40:
        p_level = 2
    else:
        p_level = 1

    # 景气赛道
    if category == "景气":
        if p_level == 5:
            action, add_pct, note = "暂停", 0, "极高估值,暂停加仓"
        elif p_level == 4:
            action, add_pct, note = "正常", 5, "高估值但可接受,正常加仓"
        elif p_level == 3:
            action, add_pct, note = "正常", 8, "估值适中,积极加仓"
        elif p_level == 2:
            action, add_pct, note = "积极", 10, "估值偏低,加大仓位"
        else:
            action, add_pct, note = "重仓", 15, "极低估值,重仓买入"

    # 周期/价值赛道
    else:
        if p_level == 5:
            action, add_pct, note = "暂停", 0, "严重高估,停止加仓"
        elif p_level == 4:
            action, add_pct, note = "警惕", 2, "估值偏高,小幅试探"
        elif p_level == 3:
            action, add_pct, note = "正常", 5, "估值合理,正常加仓"
        elif p_level == 2:
            action, add_pct, note = "积极", 8, "估值偏低,积极加仓"
        else:
            action, add_pct, note = "重仓", 12, "严重低估,重仓机会"

    # 双确认
    if drawdown > 0.15:
        if (category == "景气" and percentile < 0.95) or (category == "周期" and percentile < 0.70):
            note += f" | 回撤{drawdown:.0%}满足双确认,执行"
            position_size = add_pct
        else:
            note += f" | 回撤{drawdown:.0%}但分位不达标,观察"
            position_size = 0
    else:
        note += f" | 回撤{drawdown:.0%}不足15%,等待"
        position_size = 0

    return {
        "action": action,
        "add_pct": add_pct,
        "position_size": position_size,
        "note": note,
        "category": category,
        "p_level": p_level,
    }

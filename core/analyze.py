"""
core/analyze.py - 全 ETF 平等的关键位判定 + 急杀检测
- 删主仓概念
- 所有 ETF 独立计算关键位
- 急杀 -7% 检测
- 简洁:只输出触发结果,不展示过程
- 估值分位动态调整加仓线(2026-08-01 体系 v2.0.1)
"""
from typing import Dict, List, Optional
from core.valuation import calc_percentile, adjust_add_line_by_valuation, get_valuation_label

# 关键位公式(以当前平均成本为基准,**动态**)
# 加仓后平均成本变,关键位跟着重算
def compute_key_levels(cost: float, valuation_percentile: float = None) -> Dict:
    """
    根据当前平均成本算关键位
    加仓线根据估值分位动态调整:
    - 估值 <30%: 加仓线 -8%(低估,更早加)
    - 估值 30-70%: 加仓线 -10%(标准)
    - 估值 >70%: 加仓线 -15%(高估,更晚加)
    返回: {
        "add": cost * (1 - add_pct),   # 估值调整后的加仓线
        "stop_loss": cost * 0.70,
        "trend_break": cost * 0.67,
        "add_pct": 加仓跌幅,
        "valuation_percentile": 估值分位,
        "valuation_label": 估值标签,
    }
    """
    if valuation_percentile is None:
        add_pct = 0.10
        label = "无数据"
    else:
        add_pct = adjust_add_line_by_valuation(valuation_percentile)
        label = get_valuation_label(valuation_percentile)
    
    return {
        "add": round(cost * (1 - add_pct), 3),
        "stop_loss": round(cost * 0.70, 3),
        "trend_break": round(cost * 0.67, 3),
        "add_pct": add_pct,
        "valuation_percentile": round(valuation_percentile, 2) if valuation_percentile is not None else None,
        "valuation_label": label,
    }


# 急杀阈值
CRASH_DROP_THRESHOLD = -0.07  # -7%


def calc_position_metrics(position: Dict, current_price: float, open_price: float = None,
                          valuation_percentile: float = None) -> Dict:
    """
    计算单只持仓的指标
    valuation_percentile: 估值分位 0-1(0=历史最低,1=历史最高)
    """
    cost = position["cost"]
    shares = position["shares"]
    market_value = current_price * shares
    cost_value = cost * shares
    profit = market_value - cost_value
    profit_pct = (profit / cost_value * 100) if cost_value > 0 else 0

    result = {
        "code": position["code"],
        "name": position["name"],
        "shares": shares,
        "cost": cost,
        "current_price": current_price,
        "market_value": round(market_value, 2),
        "cost_value": round(cost_value, 2),
        "profit": round(profit, 2),
        "profit_pct": round(profit_pct, 2),
        "key_levels": compute_key_levels(cost, valuation_percentile),
    }
    
    # 急杀检测(从开盘价算)
    if open_price and open_price > 0:
        day_drop = (current_price - open_price) / open_price
        result["open_price"] = open_price
        result["day_drop_pct"] = round(day_drop * 100, 2)
        result["is_crash_drop"] = day_drop <= CRASH_DROP_THRESHOLD
    else:
        result["open_price"] = None
        result["day_drop_pct"] = None
        result["is_crash_drop"] = False
    
    return result


def check_position_signals(position_metric: Dict) -> List[Dict]:
    """
    检查单只 ETF 的所有信号
    返回: [{"type": "加仓/止损/止盈/急杀", "triggered": bool, "message": "..."}]
    """
    signals = []
    price = position_metric["current_price"]
    cost = position_metric["cost"]
    levels = position_metric["key_levels"]
    name = position_metric["name"]
    
    # 1. 急杀 -7%(最先检查,优先级最高)
    if position_metric.get("is_crash_drop"):
        signals.append({
            "type": "急杀",
            "code": position_metric["code"],
            "name": name,
            "triggered": True,
            "current": price,
            "day_drop_pct": position_metric.get("day_drop_pct"),
            "message": f"🟢 {name} 急杀 {position_metric['day_drop_pct']:.2f}%,触发情绪下杀规则(行业逻辑未变才加仓)"
        })
    
    # 2. 加仓 -10%(只触发一次,后续 -20%/-25% 加仓位不重复)
    add_triggered = False
    if price <= levels["add"]:
        signals.append({
            "type": "加仓",
            "code": position_metric["code"],
            "name": name,
            "triggered": True,
            "current": price,
            "level": levels["add"],
            "message": f"🟢 {name} 跌至 {price:.3f},已低于加仓点 {levels['add']:.3f}"
        })
        add_triggered = True
    
    # 3. 止损 -30%(独立于加仓)
    if price <= levels["stop_loss"]:
        signals.append({
            "type": "止损",
            "code": position_metric["code"],
            "name": name,
            "triggered": True,
            "current": price,
            "level": levels["stop_loss"],
            "message": f"🔴 {name} 跌至 {price:.3f},触及止损位 {levels['stop_loss']:.3f},减仓 1/2"
        })
    
    # 4. 趋势走坏 -36%(最高级别)
    if price <= levels["trend_break"]:
        signals.append({
            "type": "趋势走坏",
            "code": position_metric["code"],
            "name": name,
            "triggered": True,
            "current": price,
            "level": levels["trend_break"],
            "message": f"🚨 {name} 跌至 {price:.3f},趋势走坏 {levels['trend_break']:.3f},强制清仓"
        })
    
    # 5. 止盈(只 +50% 提醒)
    if price >= cost * 1.50:
        signals.append({
            "type": "止盈+50%",
            "code": position_metric["code"],
            "name": name,
            "triggered": True,
            "current": price,
            "level": cost * 1.50,
            "message": f"🟡 {name} 涨 50% 至 {price:.3f},止盈提醒(行业逻辑未变则减 60%,变了则清仓评估)"
        })
    
    return signals


def check_market_signals(index_data: Dict) -> List[Dict]:
    """
    检查大盘级信号(3800 / AI 泡沫)
    """
    signals = []
    
    # 3800 政策底
    sh = index_data.get("上证", 9999)
    if sh < 3800:
        signals.append({
            "type": "3800政策底",
            "triggered": True,
            "level": sh,
            "message": f"🛡️ 上证 {sh:.0f} 跌破 3800 政策底,关注 3700"
        })
    
    return signals


def get_all_signals(positions: List[Dict], index_data: Dict) -> Dict:
    """
    总信号汇总(所有 ETF + 大盘)
    返回: {
        "position_signals": [{code, name, signals: [...]}],
        "market_signals": [...],
        "triggered_count": int,  # 总触发项数
    }
    """
    position_signals = []
    market_signals = check_market_signals(index_data)
    
    for pos in positions:
        pos_signals = check_position_signals(pos)
        if pos_signals:  # 只保留有触发的
            position_signals.append({
                "code": pos["code"],
                "name": pos["name"],
                "signals": pos_signals,
            })
    
    triggered_count = sum(len(p["signals"]) for p in position_signals) + len(market_signals)
    
    return {
        "position_signals": position_signals,
        "market_signals": market_signals,
        "triggered_count": triggered_count,
    }


def make_decision_summary(all_signals: Dict) -> str:
    """
    1 句话决策(不展示过程,只看结果)
    """
    if all_signals["triggered_count"] == 0:
        return "⏸️ 持有不动,无触发"
    
    # 优先级:趋势走坏 > 止损 > 急杀 > 加仓 > 止盈 > 3800
    all_msgs = []
    for p in all_signals["position_signals"]:
        for s in p["signals"]:
            all_msgs.append(s["message"])
    all_msgs.extend([s["message"] for s in all_signals["market_signals"]])
    
    # 找最严重的
    priority = ["趋势走坏", "止损", "急杀", "回本", "加仓", "止盈", "3800政策底"]
    for p_type in priority:
        for msg in all_msgs:
            if p_type in msg:
                return msg
    
    return "⏸️ 持有不动"


if __name__ == "__main__":
    # 自测
    pos = {
        "code": "159516", "name": "半导体设备ETF", "shares": 110000,
        "cost": 0.864, "current_price": 0.670, "open_price": 0.705,
    }
    pm = calc_position_metrics(pos, 0.670, 0.705)
    print(f"159516 关键位:{pm['key_levels']}")
    print(f"急杀:{pm['is_crash_drop']}({pm.get('day_drop_pct')}%)")
    
    sigs = check_position_signals(pm)
    print(f"触发 {len(sigs)} 项:")
    for s in sigs:
        print(f"  {s['message']}")
    
    idx = {"上证": 3832}
    all_s = get_all_signals([pm], idx)
    print(f"\n总信号: {all_s['triggered_count']} 项")
    print(f"决策: {make_decision_summary(all_s)}")

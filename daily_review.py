#!/usr/bin/env python3
"""
每日复盘报告生成器 - Mavis客户 (增强版 v2.0)
============================================
- 实时行情(新浪财经 API)
- 5只ETF + 半导体板块代理基准(科创芯片ETF 588200)
- 生成 HTML(网页可视化) + Markdown(手机看) 双版本
- 关键位提醒(0.65 加仓 / 0.90 减仓20%)
- 触发:每个交易日 16:00(A股收盘后)
"""
import json
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

# 自动 cd 到仓库根目录,保证相对路径正确
import os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
os.chdir(REPO_ROOT)

sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
from dingding_sender import send_markdown, send_text
from news_fetcher import get_relevant_news, format_news_for_dingding

WORKSPACE = Path(REPO_ROOT)
PORTFOLIO_FILE = WORKSPACE / "portfolio" / "holdings.json"
REPORTS_DIR = Path(REPO_ROOT) / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
    portfolio = json.load(f)

# 半导体板块代理基准(科创芯片ETF 588200,与159516走势高度相关)
SEMI_BENCHMARK = {"code": "588200", "exchange": "sh", "name": "科创芯片ETF(半导体板块代理)"}

# 主仓关键位(用于提醒)
MAIN_POSITION_ALERTS = {
    "加仓位": 0.65,   # 跌到这里考虑分批加仓
    "回本减仓": 0.864, # 回本时减仓20%
    "第一止盈": 0.90,  # 短期止盈位
    "强压力位": 1.00,  # 突破1元心理位
}


def fetch_etf_data(codes_with_exchange):
    """从新浪财经接口拉取ETF/指数数据"""
    full_codes = [f"{ex}{c}" for c, ex in codes_with_exchange]
    url = f"https://hq.sinajs.cn/list={','.join(full_codes)}"
    req = urllib.request.Request(url, headers={
        "Referer": "https://finance.sina.com.cn",
        "User-Agent": "Mozilla/5.0"
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("gbk", errors="ignore")

        result = {}
        for match in re.finditer(r'var hq_str_(\w+)="([^"]+)";', raw):
            full_code, data = match.groups()
            code = full_code[2:]
            fields = data.split(",")
            if len(fields) >= 32:
                result[code] = {
                    "name": fields[0],
                    "open": float(fields[1]),
                    "prev_close": float(fields[2]),
                    "price": float(fields[3]),
                    "high": float(fields[4]),
                    "low": float(fields[5]),
                    "change_pct": ((float(fields[3]) - float(fields[2])) / float(fields[2])) * 100,
                    "volume": fields[8],
                    "amount": fields[9],
                    "date": fields[30],
                    "time": fields[31]
                }
        return result
    except Exception as e:
        print(f"⚠️ 拉取失败: {e}")
        return None


def calculate_metrics(holding, current_price):
    market_value = current_price * holding["shares"]
    cost_value = holding["cost"] * holding["shares"]
    profit = market_value - cost_value
    profit_pct = (profit / cost_value) * 100
    return {
        "market_value": market_value,
        "cost_value": cost_value,
        "profit": profit,
        "profit_pct_rounded": round(profit_pct, 2)
    }


def check_alerts(positions, alerts):
    """检查主仓是否触发关键位提醒"""
    main_pos = next(p for p in positions if p["is_core"])
    current = main_pos["current_price"]
    triggered = []

    for name, price in alerts.items():
        # 加仓位:当前价 <= 触发价
        if name == "加仓位" and current <= price:
            triggered.append({
                "type": "加仓信号",
                "level": "🟢",
                "msg": f"主仓跌至 {current:.3f},已到加仓位 {price},建议分批加仓"
            })
        # 减仓位:当前价 >= 触发价
        elif name in ["回本减仓", "第一止盈", "强压力位"] and current >= price:
            triggered.append({
                "type": "止盈信号" if "止盈" in name or "减仓" in name else "突破信号",
                "level": "🔴" if "减仓" in name or "止盈" in name else "🟡",
                "msg": f"主仓涨至 {current:.3f},触发{name}({price})"
            })

    return triggered


def generate_html_report(positions, index_data, etf_live_data, semi_benchmark_data, alerts, target_date):
    """生成 HTML 网页版报告"""

    total_market_value = sum(p["market_value"] for p in positions)
    total_cost = sum(p["cost_value"] for p in positions)
    total_profit = total_market_value - total_cost
    total_profit_pct = (total_profit / total_cost) * 100

    semi_exposure = sum(
        p["market_value"] / total_market_value
        for p in positions if p["category"].startswith("半导体")
    )

    main_pos = next(p for p in positions if p["is_core"])
    dist_to_stop = ((main_pos["current_price"] - main_pos["stop_loss_price"]) / main_pos["current_price"]) * 100
    dist_to_breakeven = ((main_pos["current_price"] - main_pos["cost"]) / main_pos["current_price"]) * 100

    # 板块对比
    main_change = main_pos["change_pct"]
    bench_change = semi_benchmark_data.get("change_pct", 0) if semi_benchmark_data else 0
    alpha = main_change - bench_change

    # 阶梯止盈
    steps = [
        {"pct": 0, "price": main_pos["cost"], "label": "回本", "action": "减仓20%"},
        {"pct": 30, "price": main_pos["cost"] * 1.30, "label": "涨30%", "action": "减仓40%"},
        {"pct": 50, "price": main_pos["cost"] * 1.50, "label": "涨50%", "action": "减仓60%"},
    ]

    # 持仓表格HTML
    positions_html = ""
    for p in positions:
        profit_color = "#10b981" if p["profit"] > 0 else "#ef4444"
        change_color = "#10b981" if p["change_pct"] > 0 else "#ef4444"
        change_symbol = "+" if p["change_pct"] > 0 else ""
        weight = (p["market_value"] / total_market_value) * 100
        core_badge = '<span class="badge core">主仓</span>' if p["is_core"] else ""
        positions_html += f"""
        <tr>
            <td><div class="stock-name">{p['name']} {core_badge}</div><div class="stock-code">{p['exchange']}{p['code']}</div></td>
            <td class="num">{p['current_price']:.3f}</td>
            <td class="num" style="color: {change_color};">{change_symbol}{p['change_pct']:.2f}%</td>
            <td class="num">{p['shares']:,}</td>
            <td class="num">{p['market_value']:,.0f}</td>
            <td class="num">{weight:.1f}%</td>
            <td class="num" style="color: {profit_color};">{p['profit']:+,.0f}</td>
            <td class="num" style="color: {profit_color};">{p['profit_pct_rounded']:+.2f}%</td>
            <td class="num">{p['stop_loss_price']:.3f}</td>
        </tr>
        """

    # 提醒HTML
    alerts_html = ""
    if alerts:
        for a in alerts:
            alerts_html += f'<div class="alert-item"><span class="alert-level">{a["level"]}</span> <strong>{a["type"]}</strong>: {a["msg"]}</div>'
    else:
        alerts_html = '<div class="no-alert">✅ 当前无关键位提醒,继续持有观望</div>'

    # 阶梯止盈HTML
    steps_html = ""
    for s in steps:
        steps_html += f'<div class="step"><div class="step-pct">+{s["pct"]}%</div><div class="step-price">{s["price"]:.3f}</div><div class="step-label">{s["label"]}</div><div class="step-action">{s["action"]}</div></div>'

    # 板块对比HTML
    bench_block = ""
    if semi_benchmark_data:
        bench_block = f"""
        <div class="metric-card">
            <div class="metric-label">半导体板块代理(588200)</div>
            <div class="metric-value" style="color: {'#10b981' if bench_change > 0 else '#ef4444'};">{bench_change:+.2f}%</div>
            <div class="metric-sub">现价 {semi_benchmark_data['price']:.3f}</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">主仓超额(alpha)</div>
            <div class="metric-value" style="color: {'#10b981' if alpha > 0 else '#ef4444'};">{alpha:+.2f}%</div>
            <div class="metric-sub">主仓-板块基准</div>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>每日复盘 - {target_date}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
    background: #0a0e1a;
    color: #e5e7eb;
    padding: 16px;
    line-height: 1.6;
    max-width: 1200px;
    margin: 0 auto;
}}
.header {{
    background: linear-gradient(135deg, #1e3a8a 0%, #312e81 100%);
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 16px;
}}
.header h1 {{ font-size: 22px; margin-bottom: 4px; }}
.header .date {{ color: #93c5fd; font-size: 13px; }}
.data-source {{ font-size: 11px; color: #6ee7b7; margin-top: 4px; }}
.section {{
    background: #1f2937;
    border-radius: 12px;
    padding: 18px;
    margin-bottom: 14px;
    border: 1px solid #374151;
}}
.section h2 {{
    font-size: 16px;
    margin-bottom: 12px;
    color: #60a5fa;
    border-bottom: 1px solid #374151;
    padding-bottom: 8px;
}}
.summary-grid {{
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 10px;
}}
.metric-card {{
    background: #111827;
    border-radius: 8px;
    padding: 12px;
    border-left: 3px solid #3b82f6;
}}
.metric-label {{ font-size: 12px; color: #9ca3af; margin-bottom: 4px; }}
.metric-value {{ font-size: 18px; font-weight: 600; }}
.metric-sub {{ font-size: 11px; color: #9ca3af; margin-top: 2px; }}
.profit-positive {{ color: #10b981; }}
.profit-negative {{ color: #ef4444; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th {{ text-align: left; padding: 8px 6px; color: #9ca3af; font-weight: 500; font-size: 12px; border-bottom: 1px solid #374151; }}
td {{ padding: 10px 6px; border-bottom: 1px solid #1f2937; }}
.num {{ text-align: right; font-family: "SF Mono", Consolas, monospace; }}
.stock-name {{ font-weight: 600; font-size: 13px; }}
.stock-code {{ color: #9ca3af; font-size: 11px; }}
.badge {{ display: inline-block; background: #3b82f6; color: white; font-size: 10px; padding: 2px 6px; border-radius: 4px; margin-left: 4px; }}
.badge.core {{ background: #dc2626; }}
.alert-item {{
    background: linear-gradient(90deg, #7c2d12 0%, #991b1b 100%);
    border-left: 4px solid #f59e0b;
    padding: 12px;
    border-radius: 6px;
    margin-bottom: 8px;
    font-size: 13px;
}}
.alert-level {{ font-size: 16px; margin-right: 6px; }}
.no-alert {{
    background: #064e3b;
    color: #6ee7b7;
    padding: 12px;
    border-radius: 6px;
    text-align: center;
    font-size: 13px;
}}
.steps-container {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }}
.step {{ background: #111827; border-radius: 8px; padding: 12px; text-align: center; border-top: 3px solid #10b981; }}
.step-pct {{ font-size: 18px; font-weight: 700; color: #10b981; }}
.step-price {{ font-size: 14px; color: #e5e7eb; margin: 4px 0; }}
.step-label {{ font-size: 11px; color: #9ca3af; }}
.step-action {{ font-size: 12px; color: #fbbf24; margin-top: 6px; font-weight: 600; }}
.insight {{ background: #1e293b; border-left: 3px solid #8b5cf6; padding: 12px; border-radius: 6px; font-size: 13px; color: #c7d2fe; }}
.alert-box {{ background: linear-gradient(90deg, #1e3a8a 0%, #312e81 100%); border-left: 4px solid #3b82f6; padding: 12px; border-radius: 6px; font-size: 13px; margin-top: 10px; }}
.footer {{ text-align: center; color: #6b7280; font-size: 11px; margin-top: 20px; padding: 10px; }}
@media (max-width: 600px) {{
    .summary-grid {{ grid-template-columns: 1fr; }}
    .steps-container {{ grid-template-columns: 1fr; }}
    body {{ padding: 8px; }}
}}
</style>
</head>
<body>

<div class="header">
    <h1>📊 每日复盘报告</h1>
    <div class="date">{target_date} | 策略:中线趋势持有至年底 | 主仓:半导体设备ETF</div>
    <div class="data-source">📡 数据源:新浪财经 API(实时) | 板块代理:科创芯片ETF 588200</div>
</div>

<div class="section">
    <h2>🚨 关键位提醒</h2>
    {alerts_html}
</div>

<div class="section">
    <h2>💰 持仓全景</h2>
    <div class="summary-grid">
        <div class="metric-card">
            <div class="metric-label">总市值</div>
            <div class="metric-value">¥{total_market_value:,.0f}</div>
            <div class="metric-sub">成本 ¥{total_cost:,.0f}</div>
        </div>
        <div class="metric-card" style="border-left-color: {'#10b981' if total_profit > 0 else '#ef4444'};">
            <div class="metric-label">总盈亏</div>
            <div class="metric-value {'profit-positive' if total_profit > 0 else 'profit-negative'}">{total_profit:+,.0f} ({total_profit_pct:+.2f}%)</div>
            <div class="metric-sub">含未实现浮动盈亏</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">半导体暴露度</div>
            <div class="metric-value">{semi_exposure*100:.1f}%</div>
            <div class="metric-sub">主战略: 半导体设备Q4主升</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">主仓距止损</div>
            <div class="metric-value" style="color: #fbbf24;">{dist_to_stop:.1f}%</div>
            <div class="metric-sub">止损 {main_pos['stop_loss_price']:.3f} | 距回本 {dist_to_breakeven:.1f}%</div>
        </div>
    </div>
</div>

<div class="section">
    <h2>🔬 半导体板块对比(主仓 vs 板块代理)</h2>
    <div class="summary-grid">
        <div class="metric-card">
            <div class="metric-label">主仓(159516 半导体设备)</div>
            <div class="metric-value" style="color: {'#10b981' if main_change > 0 else '#ef4444'};">{main_change:+.2f}%</div>
            <div class="metric-sub">现价 {main_pos['current_price']:.3f}</div>
        </div>
        {bench_block}
    </div>
    <div class="alert-box" style="margin-top: 12px;">
        <strong>💡 解读:</strong> 主仓跑赢/跑输板块 {abs(alpha):.2f} 个百分点。
        {'✨ 主仓表现强于板块,说明你选的ETF不错' if alpha > 0.5 else '⚠️ 主仓弱于板块,留意是否需要换更大规模ETF' if alpha < -0.5 else '➖ 主仓与板块同步,正常'}
    </div>
</div>

<div class="section">
    <h2>📈 大盘指数</h2>
    <div class="summary-grid">
        <div class="metric-card"><div class="metric-label">上证指数</div><div class="metric-value">{index_data.get('shanghai', 0):.2f}</div></div>
        <div class="metric-card"><div class="metric-label">深证成指</div><div class="metric-value">{index_data.get('shenzhen', 0):.2f}</div></div>
        <div class="metric-card"><div class="metric-label">创业板指</div><div class="metric-value">{index_data.get('chinext', 0):.2f}</div></div>
        <div class="metric-card"><div class="metric-label">科创50</div><div class="metric-value">{index_data.get('star50', 0):.2f}</div></div>
    </div>
</div>

<div class="section">
    <h2>📈 持仓明细</h2>
    <table>
        <thead><tr>
            <th>名称</th><th class="num">现价</th><th class="num">当日</th><th class="num">份额</th>
            <th class="num">市值</th><th class="num">占比</th><th class="num">盈亏</th><th class="num">盈亏%</th><th class="num">止损价</th>
        </tr></thead>
        <tbody>{positions_html}</tbody>
    </table>
</div>

<div class="section">
    <h2>🎯 主仓阶梯式止盈计划</h2>
    <div class="steps-container">{steps_html}</div>
    <div class="alert-box">
        ⚠️ 当前价 {main_pos['current_price']:.3f} | 距回本还差 {dist_to_breakeven:.1f}% | 阶梯式止盈只在突破关键位时执行
    </div>
</div>

<div class="section">
    <h2>🧭 主仓操作建议</h2>
    <div class="insight">
        <strong>核心逻辑:</strong> 半导体设备8月震荡,9月向上,拿到年底等Q4主升。<br>
        <strong>当前状态:</strong> 主仓套牢中,但逻辑未破,继续持有。<br>
        <strong>操作建议:</strong> 8月中报季前不动;急跌到 0.65-0.68 区间可分批加仓;中报兑现后再评估。<br>
        <strong>心理建设:</strong> 别看成本,看当前价做决策;每天最多看1次,周末再看。
    </div>
</div>

<div class="footer">
    报告生成时间: {target_date} 16:00 | 数据源:新浪财经 API | 下次生成: 明日16:00 | 仅供个人复盘参考,不构成投资建议
</div>

</body>
</html>
"""
    return html


def generate_markdown_report(positions, index_data, etf_live_data, semi_benchmark_data, alerts, target_date):
    """生成 Markdown 移动版报告(手机看友好)"""

    total_market_value = sum(p["market_value"] for p in positions)
    total_cost = sum(p["cost_value"] for p in positions)
    total_profit = total_market_value - total_cost
    total_profit_pct = (total_profit / total_cost) * 100

    main_pos = next(p for p in positions if p["is_core"])
    dist_to_stop = ((main_pos["current_price"] - main_pos["stop_loss_price"]) / main_pos["current_price"]) * 100
    dist_to_breakeven = ((main_pos["current_price"] - main_pos["cost"]) / main_pos["current_price"]) * 100

    main_change = main_pos["change_pct"]
    bench_change = semi_benchmark_data.get("change_pct", 0) if semi_benchmark_data else 0
    alpha = main_change - bench_change

    md = f"""# 📊 每日复盘 · {target_date}

> 中线趋势 · 持有至年底 · 主仓:半导体设备ETF
> 数据源:新浪财经 API(实时)

---

## 🚨 关键位提醒

"""
    if alerts:
        for a in alerts:
            md += f"- {a['level']} **{a['type']}**:{a['msg']}\n"
    else:
        md += "✅ 当前无关键位提醒,继续持有观望\n"

    md += f"""
---

## 💰 持仓全景

| 指标 | 数值 |
|------|------|
| **总市值** | ¥{total_market_value:,.0f} |
| **总成本** | ¥{total_cost:,.0f} |
| **总盈亏** | **{total_profit:+,.0f} ({total_profit_pct:+.2f}%)** |
| **主仓距止损** | {dist_to_stop:.1f}% |
| **主仓距回本** | {dist_to_breakeven:.1f}% |

---

## 🔬 主仓 vs 板块

| 标的 | 当日 | 现价 |
|------|------|------|
| **主仓(159516 半导体设备)** | {main_change:+.2f}% | {main_pos['current_price']:.3f} |
| 板块代理(588200 科创芯片) | {bench_change:+.2f}% | {semi_benchmark_data.get('price', 0):.3f} |
| **主仓超额(alpha)** | **{alpha:+.2f}%** | - |

💡 {'✨ 跑赢板块' if alpha > 0.5 else '⚠️ 跑输板块' if alpha < -0.5 else '➖ 与板块同步'}

---

## 📈 大盘指数

| 指数 | 收盘 |
|------|------|
| 上证指数 | {index_data.get('shanghai', 0):.2f} |
| 深证成指 | {index_data.get('shenzhen', 0):.2f} |
| 创业板指 | {index_data.get('chinext', 0):.2f} |
| 科创50 | {index_data.get('star50', 0):.2f} |

---

## 📊 持仓明细

| 名称 | 现价 | 当日 | 市值 | 占比 | 盈亏% |
|------|------|------|------|------|-------|
"""
    for p in positions:
        weight = (p["market_value"] / total_market_value) * 100
        marker = "🎯" if p["is_core"] else ""
        md += f"| {marker}{p['name']} | {p['current_price']:.3f} | {p['change_pct']:+.2f}% | ¥{p['market_value']:,.0f} | {weight:.1f}% | {p['profit_pct_rounded']:+.2f}% |\n"

    md += f"""
---

## 🎯 主仓阶梯止盈

| 涨幅 | 价格 | 操作 |
|------|------|------|
| 0%(回本) | {main_pos['cost']:.3f} | 减仓 20% |
| +30% | {main_pos['cost']*1.30:.3f} | 减仓 40% |
| +50% | {main_pos['cost']*1.50:.3f} | 减仓 60% |

---

## 🧭 操作建议

- **核心逻辑**:8月震荡,9月向上,拿到年底等Q4主升
- **当前状态**:主仓套牢,但逻辑未破
- **操作**:8月中报季前不动;**急跌到 0.65-0.68 区间可分批加仓**
- **心理**:别看成本,看当前价决策;每天最多看1次

---

*报告生成: {target_date} 16:00 | 仅供个人复盘,非投资建议*
"""
    return md


def main():
    target_date = datetime.now().strftime("%Y-%m-%d")
    weekday = datetime.now().weekday()

    if weekday >= 5:
        print(f"[{target_date}] 周末,不生成报告")
        return

    print(f"[{target_date}] 开始生成复盘报告(增强版 v2.0)...")

    # 1. 拉取所有数据
    codes_to_fetch = [(h["code"], h["exchange"]) for h in portfolio["holdings"]]
    codes_to_fetch.append((SEMI_BENCHMARK["code"], SEMI_BENCHMARK["exchange"]))
    codes_to_fetch.extend([("000001", "sh"), ("399001", "sz"), ("399006", "sz"), ("000688", "sh")])

    etf_live_data = fetch_etf_data(codes_to_fetch)
    if not etf_live_data:
        print("❌ 数据拉取失败,使用持仓档 fallback")
        etf_live_data = {}

    # 2. 计算每个持仓的指标
    positions = []
    for h in portfolio["holdings"]:
        if h["code"] in etf_live_data:
            current_price = etf_live_data[h["code"]]["price"]
            change_pct = etf_live_data[h["code"]]["change_pct"]
        else:
            current_price = h["current_price"]
            change_pct = 0

        metrics = calculate_metrics(h, current_price)
        positions.append({**h, "current_price": current_price, "change_pct": change_pct, **metrics})

    # 3. 大盘指数
    index_data = {
        "shanghai": etf_live_data.get("000001", {}).get("price", 0),
        "shenzhen": etf_live_data.get("399001", {}).get("price", 0),
        "chinext": etf_live_data.get("399006", {}).get("price", 0),
        "star50": etf_live_data.get("000688", {}).get("price", 0),
    }

    # 4. 板块代理
    semi_benchmark_data = etf_live_data.get(SEMI_BENCHMARK["code"])

    # 5. 检查提醒
    alerts = check_alerts(positions, MAIN_POSITION_ALERTS)

    # 6. 生成 HTML
    html = generate_html_report(positions, index_data, etf_live_data, semi_benchmark_data, alerts, target_date)
    html_path = REPORTS_DIR / f"daily-review-{target_date}.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  ✅ HTML报告: {html_path}")

    # 7. 生成 Markdown
    md = generate_markdown_report(positions, index_data, etf_live_data, semi_benchmark_data, alerts, target_date)
    md_path = REPORTS_DIR / f"daily-review-{target_date}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"  ✅ Markdown报告: {md_path}")

    # 8. 输出汇总
    total_mv = sum(p["market_value"] for p in positions)
    main_pos = next(p for p in positions if p["is_core"])
    print(f"\n📊 总市值: ¥{total_mv:,.0f}")
    print(f"🎯 主仓: {main_pos['name']} {main_pos['exchange']}{main_pos['code']} @ {main_pos['current_price']}")
    if alerts:
        print(f"🚨 触发 {len(alerts)} 个提醒!")
    else:
        print("✅ 无关键位提醒")

    # 9. 推送到钉钉
    try:
        push_daily_report_to_dingding(positions, index_data, semi_benchmark_data, alerts, total_mv, target_date)
    except Exception as e:
        print(f"⚠️ 钉钉推送失败: {e}")

    return html_path, md_path


def push_daily_report_to_dingding(positions, index_data, semi_benchmark_data, alerts, total_mv, target_date):
    """推送收盘报告到钉钉"""
    total_cost = sum(p["cost_value"] for p in positions)
    total_profit = total_mv - total_cost
    total_profit_pct = (total_profit / total_cost) * 100 if total_cost > 0 else 0

    main_pos = next(p for p in positions if p["is_core"])
    bench_change = semi_benchmark_data.get("change_pct", 0) if semi_benchmark_data else 0
    main_change = main_pos["change_pct"]
    alpha = main_change - bench_change

    title = f"📊 每日复盘 · {target_date}"
    md = f"# 📊 每日复盘 · {target_date}\n\n"
    md += f"> 中线趋势 · 拿到年底 · 主仓:半导体设备ETF\n\n"
    md += "---\n\n"

    # 关键位提醒
    md += "## 🚨 关键位提醒\n\n"
    if alerts:
        for a in alerts:
            md += f"- {a['level']} **{a['type']}**:{a['msg']}\n"
    else:
        md += "✅ 当前无关键位触发\n"
    md += "\n---\n\n"

    # 持仓全景
    profit_emoji = "🟢" if total_profit > 0 else "🔴"
    md += "## 💰 持仓全景\n\n"
    md += f"| 指标 | 数值 |\n|------|------|\n"
    md += f"| **总市值** | ¥{total_mv:,.0f} |\n"
    md += f"| **总成本** | ¥{total_cost:,.0f} |\n"
    md += f"| **总盈亏** | {profit_emoji} **{total_profit:+,.0f} ({total_profit_pct:+.2f}%)** |\n"
    md += f"| **主仓价** | `{main_pos['current_price']:.3f}` ({main_change:+.2f}%) |\n\n"
    md += "---\n\n"

    # 主仓 vs 板块
    md += "## 🔬 主仓 vs 板块\n\n"
    md += f"| 标的 | 当日 | 现价 |\n|------|------|------|\n"
    md += f"| **主仓(159516)** | {main_change:+.2f}% | `{main_pos['current_price']:.3f}` |\n"
    if semi_benchmark_data:
        md += f"| 板块代理(588200) | {bench_change:+.2f}% | `{semi_benchmark_data.get('price', 0):.3f}` |\n"
    md += f"| **主仓超额** | **{alpha:+.2f}%** | - |\n\n"
    md += "---\n\n"

    # 持仓明细
    md += "## 📊 持仓明细\n\n"
    md += f"| 名称 | 现价 | 当日 | 盈亏% |\n|------|------|------|------|\n"
    for p in positions:
        emoji = "🎯" if p["is_core"] else ""
        weight = (p["market_value"] / total_mv) * 100
        md += f"| {emoji}{p['name']}({weight:.0f}%) | `{p['current_price']:.3f}` | {p['change_pct']:+.2f}% | **{p['profit_pct_rounded']:+.2f}%** |\n"
    md += "\n---\n\n"

    # 板块要闻
    try:
        news = get_relevant_news(5)
        if news:
            md += "## 📰 板块要闻(与持仓相关)\n\n"
            for n in news:
                emoji = {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}.get(n["sentiment"], "⚪")
                title = n["title"]
                if len(title) > 55:
                    title = title[:52] + "..."
                md += f"{emoji} **{title}**\n"
                if n.get("content"):
                    c = n["content"]
                    if len(c) > 80:
                        c = c[:77] + "..."
                    md += f"  > {c}\n"
                meta = []
                if n.get("time_str"):
                    meta.append(n["time_str"])
                if n.get("keywords"):
                    meta.append(", ".join(n["keywords"][:2]))
                if meta:
                    md += f"  <font color='gray' size='1'>{' | '.join(meta)}</font>\n\n"
    except Exception as e:
        pass

    # 操作建议
    md += "## 🧭 操作建议\n\n"
    md += "- **核心逻辑**:8月震荡,9月向上,拿到年底等Q4主升\n"
    md += "- **当前状态**:主仓套牢,但逻辑未破,继续持有\n"
    md += "- **操作**:急跌到 0.65-0.68 区间可分批加仓\n"
    md += "- **心理**:别看成本,看当前价决策\n\n"
    md += "---\n\n"
    md += f"*报告生成:{target_date} 16:00 | 数据:新浪财经 | Mavis 投资助理*"

    result = send_markdown(title, md)
    if result and result.get("success"):
        print("  ✅ 收盘报告已推送到钉钉")
    else:
        print(f"  ❌ 推送失败: {result}")


if __name__ == "__main__":
    main()

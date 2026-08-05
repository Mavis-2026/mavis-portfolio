"""
core/report.py - 报告生成(HTML + MD)
- 1000-1500 字
- 5 件事触发才写
- 阶段 2:AI 分析段
- HTML 用深色主题(参考 7-27 模板)
"""
import os
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List


# ====== 旧模板 CSS(7-27 报告) ======


# 时区工具(沙箱是 UTC,转 Asia/Shanghai = UTC+8 给用户看)
def now_cst():
    """获取当前 Asia/Shanghai 时间"""
    utc_now = datetime.now(timezone.utc)
    cst = utc_now.astimezone(timezone(timedelta(hours=8)))
    return cst
HTML_CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
    background: #0a0e1a;
    color: #e5e7eb;
    padding: 16px;
    line-height: 1.6;
    max-width: 1200px;
    margin: 0 auto;
}
.header {
    background: linear-gradient(135deg, #1e3a8a 0%, #312e81 100%);
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 16px;
}
.header h1 { font-size: 22px; margin-bottom: 4px; }
.header .date { color: #93c5fd; font-size: 13px; }
.data-source { font-size: 11px; color: #6ee7b7; margin-top: 4px; }
.section {
    background: #1f2937;
    border-radius: 12px;
    padding: 18px;
    margin-bottom: 14px;
    border: 1px solid #374151;
}
.section h2 {
    font-size: 16px;
    margin-bottom: 12px;
    color: #60a5fa;
    border-bottom: 1px solid #374151;
    padding-bottom: 8px;
}
.summary-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 10px;
}
.metric-card {
    background: #111827;
    border-radius: 8px;
    padding: 12px;
    border-left: 3px solid #3b82f6;
}
.metric-label { font-size: 12px; color: #9ca3af; margin-bottom: 4px; }
.metric-value { font-size: 18px; font-weight: 600; }
.metric-sub { font-size: 11px; color: #9ca3af; margin-top: 2px; }
/* A 股惯例:涨红跌绿 */
.profit-positive { color: #ef4444; }
.profit-negative { color: #10b981; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; padding: 8px 6px; color: #9ca3af; font-weight: 500; font-size: 12px; border-bottom: 1px solid #374151; }
td { padding: 10px 6px; border-bottom: 1px solid #1f2937; }
.num { text-align: right; font-family: "SF Mono", Consolas, monospace; }
.stock-name { font-weight: 600; font-size: 13px; }
.stock-code { color: #9ca3af; font-size: 11px; }
.badge { display: inline-block; background: #3b82f6; color: white; font-size: 10px; padding: 2px 6px; border-radius: 4px; margin-left: 4px; }
.badge.core { background: #dc2626; }
.alert-item {
    background: linear-gradient(90deg, #7c2d12 0%, #991b1b 100%);
    border-left: 4px solid #f59e0b;
    padding: 12px;
    border-radius: 6px;
    margin-bottom: 8px;
    font-size: 13px;
}
.alert-level { font-size: 16px; margin-right: 6px; }
.no-alert {
    background: #064e3b;
    color: #6ee7b7;
    padding: 12px;
    border-radius: 6px;
    text-align: center;
    font-size: 13px;
}
.decision-box {
    background: linear-gradient(90deg, #1e3a8a 0%, #312e81 100%);
    border-left: 4px solid #3b82f6;
    padding: 16px;
    border-radius: 6px;
    font-size: 15px;
    margin-bottom: 12px;
}
.things-item {
    background: #111827;
    border-left: 4px solid #6ee7b7;
    padding: 12px;
    border-radius: 6px;
    margin-bottom: 8px;
    font-size: 14px;
}
.things-item.warning { border-left-color: #fbbf24; }
.things-item.danger { border-left-color: #ef4444; }
.things-item.info { border-left-color: #60a5fa; }
.insight { background: #1e293b; border-left: 3px solid #8b5cf6; padding: 14px; border-radius: 6px; font-size: 13px; color: #c7d2fe; line-height: 1.8; }
.insight p { margin: 6px 0; }
.insight strong { color: #fbbf24; }
.footer { text-align: center; color: #6b7280; font-size: 11px; margin-top: 20px; padding: 10px; }
@media (max-width: 600px) {
    .summary-grid { grid-template-columns: 1fr; }
    body { padding: 8px; }
}
"""


# ====== MD 部分(用于 .md 文件) ======


def render_data_table(positions: List[Dict]) -> str:
    """持仓数据表 MD"""
    lines = [
        "## 📊 持仓数据",
        "",
        "| 代码 | 名称 | 股数 | 成本 | 现价 | 市值 | 浮盈% |",
        "|------|------|------|------|------|------|--------|",
    ]
    total_mv = 0
    total_cost = 0
    for p in positions:
        lines.append(
            f"| {p['code']} | {p['name']} | {p['shares']:,} | {p['cost']:.3f} | "
            f"{p['current_price']:.3f} | ¥{p['market_value']:,.0f} | {p['profit_pct']:+.2f}% |"
        )
        total_mv += p["market_value"]
        total_cost += p["cost_value"]
    total_profit = total_mv - total_cost
    total_pct = (total_profit / total_cost * 100) if total_cost > 0 else 0
    lines.append(f"| **合计** | | | | | **¥{total_mv:,.0f}** | **{total_profit:+,.0f}({total_pct:+.2f}%)** |")
    return "\n".join(lines) + "\n"


def render_index(index_data: Dict) -> str:
    """大盘指数 MD"""
    return (
        f"## 🌡️ 大盘指数\n\n"
        f"- 上证指数:**{index_data.get('上证', 0):.2f}**\n"
        f"- 深证成指:**{index_data.get('深证', 0):.2f}**\n"
        f"- 创业板指:**{index_data.get('创业板', 0):.2f}**\n"
    )


def render_signals_md(all_signals: Dict, ai_verified_signals: str = None) -> str:
    """
    操作信号段(只写触发的)
    优先用 DeepSeek 验证后的版本(ai_verified_signals)
    """
    if ai_verified_signals:
        # 用 DeepSeek 验证版
        return "\n\n" + ai_verified_signals
    
    # Fallback:Mavis 计算版
    triggered = all_signals.get("position_signals", [])
    market = all_signals.get("market_signals", [])
    
    if not triggered and not market:
        return ""  # 无触发,完全不写
    
    lines = ["", "## 🎯 操作信号(Mavis 机械计算,待 DeepSeek 验证)", ""]
    
    for sig in market:
        lines.append(sig["message"])
        lines.append("")
    
    type_priority = ["急杀", "趋势走坏", "止损", "加仓", "止盈+50%"]
    
    for p in triggered:
        lines.append(f"**{p['name']}({p['code']})**:")
        sorted_sigs = sorted(p["signals"], key=lambda s: type_priority.index(s["type"]) if s["type"] in type_priority else 99)
        for sig in sorted_sigs:
            lines.append(f"- {sig['message']}")
        lines.append("")
    
    return "\n".join(lines)


def extract_ai_verified_signals(ai_section: str) -> str:
    """
    从 DeepSeek 输出的"持仓诊断"段里提取明确操作意见
    只提取 4 种:🟢 加仓 / 🔴 止损 / 🟡 止盈 / 💣 减仓
    其他(不动/继续持有/暂缓)不提取
    没有就返回空(显示"无")
    """
    if not ai_section:
        return ""
    import re
    
    lines = ai_section.split('\n')
    actions = []
    
    # 模式 1: - 🟢 加仓 XXX:...
    pattern_with_emoji = re.compile(
        r'^[\-\s]*(🟢|🔴|🟡|💣)\s*\**\s*(加仓|止损|止盈|减仓)\s*\**',
        re.MULTILINE
    )
    
    # 模式 2: **加仓 XXX** 或 **2. XXX — 加仓 X%**
    # 抓 "(加仓|止损|止盈|减仓) X%" 模式
    pattern_pct = re.compile(
        r'\*\*[^*]{0,40}?(加仓|止损|止盈|减仓)\s*(\d+%|1/2|1/3|60%|30%?|50%)',
        re.MULTILINE
    )
    # 抓 "XXX(代码) — 加仓 X%" 或 "XXX — 加仓 X%"(无加粗)
    pattern_dash = re.compile(
        r'(\d{6})?\s*[—\-]\s*(加仓|止损|止盈|减仓)\s*(\d+%|1/2|1/3|60%|30%?|50%)',
        re.MULTILINE
    )
    
    # 模式 3: 标题里的 "**2. XXX — 分批加仓 15%**" 或 "**2. XXX — 加仓 15%**"
    # 抓 ETF 名字:xxxETF(code),支持中文破折号(—)和 ASCII 横线(-)
    # 操作词前可有"分批/建议/立即"等修饰
    pattern_title = re.compile(
        r'\*\*[^*\n]*?'
        r'([一-龥a-zA-Z]+(?:ETF|etf))'
        r'\s*[（\(]?\s*(\d{6})?\s*[）\)]?'
        r'\s*[—\-－:]\s*'
        r'(?:分批|建议|立即|今日)?\s*'
        r'(加仓|止损|止盈|减仓)\s*(\d+%|1/2|1/3|60%|30%?|50%)',
        re.MULTILINE
    )
    
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue
        # 模式 1
        m = pattern_with_emoji.match(line_stripped)
        if m:
            actions.append(line_stripped.lstrip('-').strip())
            continue
        # 模式 3: 标题行(包含 ETF + 操作 + 百分比)
        # groups: (etf, code, op, pct)
        m3 = pattern_title.search(line_stripped)
        if m3 and m3.group(3) and m3.group(4):
            etf = m3.group(1).strip()
            code = m3.group(2) or ""
            op = m3.group(3)
            pct = m3.group(4)
            if '加仓' in op:
                emoji = '🟢'
            elif '止损' in op:
                emoji = '🔴'
            elif '止盈' in op:
                emoji = '🟡'
            else:
                emoji = '💣'
            full_etf = f"{etf} {code}".strip()
            actions.append(f"{emoji} **{full_etf}** {op} {pct}")
            continue
        # 模式 2/3 兜底
        if '加仓' in line_stripped or '止损' in line_stripped or '止盈' in line_stripped or '减仓' in line_stripped:
            m2 = pattern_pct.search(line_stripped)
            if m2:
                op = m2.group(1)
                pct = m2.group(2)
                if '加仓' in op:
                    emoji = '🟢'
                elif '止损' in op:
                    emoji = '🔴'
                elif '止盈' in op:
                    emoji = '🟡'
                else:
                    emoji = '💣'
                # 找 ETF 名称
                etf_match = re.search(r'\*\*([^*\n]{2,30}?(?:ETF|etf|半导体|恒生|创业板|有色|科创)[^*\n]{0,10}?)\*\*', line_stripped)
                if not etf_match:
                    etf_match = re.search(r'(\d{6}\s*[^\n—:]{0,15})', line_stripped)
                etf = etf_match.group(1).strip() if etf_match else "相关持仓"
                actions.append(f"{emoji} **{etf}** {op} {pct}")
    
    return '\n'.join(actions)


def render_signals_html(all_signals: Dict, ai_verified_signals: str = None) -> str:
    """
    操作信号 HTML(只写触发的,按优先级排序,急杀优先)
    """
    triggered = all_signals.get("position_signals", [])
    market = all_signals.get("market_signals", [])
    
    if not triggered and not market:
        return ""  # 无触发,完全不渲染
    
    items = []
    
    if ai_verified_signals:
        # DeepSeek 操作意见(纯文本,加深色样式,处理 **加粗** 标记)
        for line in ai_verified_signals.split('\n'):
            line = line.strip()
            if not line:
                continue
            # 处理 **加粗** 和 emoji
            content = process_inline(line)
            # 操作类型用对应颜色
            cls = "things-item"
            if line.startswith('🟢'):
                cls = "things-item"  # 加仓绿色
            elif line.startswith('🔴'):
                cls = "things-item danger"  # 止损红色
            elif line.startswith('🟡'):
                cls = "things-item warning"  # 止盈黄色
            elif line.startswith('💣'):
                cls = "things-item danger"  # 减仓红色
            items.append(f'<div class="{cls}">{content}</div>')
        return "\n".join(items)
    
    # Fallback:无 DeepSeek 操作意见,显示"无"
    return '<div class="things-item info">无</div>'
    
    # 市场信号
    for sig in market:
        items.append(f'<div class="things-item info">{sig["message"]}</div>')
    
    # 个股信号(按优先级排)
    type_priority = ["急杀", "趋势走坏", "止损", "加仓", "止盈+50%"]
    
    for p in triggered:
        sorted_sigs = sorted(p["signals"], key=lambda s: type_priority.index(s["type"]) if s["type"] in type_priority else 99)
        for sig in sorted_sigs:
            if "急杀" in sig["type"]:
                items.append(f'<div class="things-item">{sig["message"]}</div>')
            elif "止损" in sig["type"] or "趋势走坏" in sig["type"]:
                items.append(f'<div class="things-item danger">{sig["message"]}</div>')
            elif "止盈" in sig["type"] or "回本" in sig["type"]:
                items.append(f'<div class="things-item warning">{sig["message"]}</div>')
            else:  # 加仓
                items.append(f'<div class="things-item">{sig["message"]}</div>')
    
    return "\n".join(items)


def render_report_md(
    account_name: str,
    positions: List[Dict],
    all_signals: Dict,
    index_data: Dict,
    decision: str,
    ai_section: str = None,
    date: str = None,
    turnover: Dict = None,
    ai_verified_signals: str = None,
    agent_data: Dict = None,
) -> str:
    """生成完整 MD 报告"""
    if not date:
        date = now_cst().strftime("%Y-%m-%d")

    sections = [
        f"# Mavis 复盘 · {account_name} · {date}",
        "",
        render_data_table(positions),
        "",
        render_index(index_data),
    ]

    # agent 预拉数据（4 段）
    if agent_data is not None:
        try:
            from core.agent_data import render_agent_data_sections
            holdings_codes = [p.get("code") for p in positions] if positions else None
            sections.append(render_agent_data_sections(agent_data, fmt="md", holdings=holdings_codes))
        except Exception as e:
            sections.append(f"\n\n> ⚠️ agent 数据渲染失败: {e}\n")

    # 操作信号段已删除(用户要求:直接看 DeepSeek 分析)

    if ai_section:
        sections.extend(["", "## 🤖 AI 分析", "", ai_section, ""])

    # 报告生成时间(精确到秒,实时生成时刻)
    timestamp = now_cst().strftime("%Y.%m.%d %H:%M:%S")
    sections.extend([
        "",
        "---",
        f"📅 报告生成时间:**{timestamp}** | 数据源:新浪财经 API | 仅供个人复盘参考,不构成投资建议",
    ])

    return "\n".join(sections)


# ====== HTML 部分(深色主题) ======



def render_data_table_html(positions: List[Dict]) -> str:
    """持仓数据表 HTML(不区分主仓)"""
    rows = []
    total_mv = 0
    total_cost = 0
    for p in positions:
        # 不再区分主仓
        profit_class = "profit-positive" if p["profit_pct"] >= 0 else "profit-negative"
        rows.append(f"""
        <tr>
            <td><div class="stock-name">{p['name']}</div><div class="stock-code">{p['code']}</div></td>
            <td class="num">{p['shares']:,}</td>
            <td class="num">{p['cost']:.3f}</td>
            <td class="num">{p['current_price']:.3f}</td>
            <td class="num">¥{p['market_value']:,.0f}</td>
            <td class="num {profit_class}">{p['profit_pct']:+.2f}%</td>
        </tr>""")
        total_mv += p["market_value"]
        total_cost += p["cost_value"]
    total_profit = total_mv - total_cost
    total_pct = (total_profit / total_cost * 100) if total_cost > 0 else 0
    total_class = "profit-positive" if total_profit >= 0 else "profit-negative"
    rows.append(f"""
        <tr style="border-top: 2px solid #374151; font-weight: 600;">
            <td>合计</td>
            <td class="num"></td>
            <td class="num"></td>
            <td class="num"></td>
            <td class="num">¥{total_mv:,.0f}</td>
            <td class="num {total_class}">{total_profit:+,.0f} ({total_pct:+.2f}%)</td>
        </tr>""")
    
    return f"""<table>
        <thead>
            <tr>
                <th>名称</th>
                <th class="num">股数</th>
                <th class="num">成本</th>
                <th class="num">现价</th>
                <th class="num">市值</th>
                <th class="num">浮盈</th>
            </tr>
        </thead>
        <tbody>
            {''.join(rows)}
        </tbody>
    </table>"""


def render_index_html(index_data: Dict) -> str:
    """大盘指数 HTML(带实时涨跌幅)"""
    cards = []
    for name, color in [("上证", "#3b82f6"), ("深证", "#8b5cf6"), ("创业板", "#10b981")]:
        val = index_data.get(name, 0)
        change_pct = index_data.get(f"{name}_change_pct", 0)
        change_class = "profit-positive" if change_pct >= 0 else "profit-negative"
        change_sign = "+" if change_pct >= 0 else ""
        cards.append(f"""
        <div class="metric-card" style="border-left-color: {color};">
            <div class="metric-label">{name}指数</div>
            <div class="metric-value">{val:.2f}</div>
            <div class="metric-sub {change_class}">{change_sign}{change_pct:.2f}%</div>
        </div>""")
    return f'<div class="summary-grid">{"".join(cards)}</div>'


def render_turnover_html(turnover: Dict) -> str:
    """A 股总成交额 HTML(带放缩量,显示具体数值)"""
    today = turnover.get("today_yuan", 0)
    today_yi = today / 1e8  # 亿
    has = turnover.get("has_comparison", False)

    if has:
        prev_yuan = turnover.get("yesterday_yuan", turnover.get("prev_yuan", 0))
        prev_yi = prev_yuan / 1e8  # 亿
        diff_yuan = today - prev_yuan
        diff_yi = diff_yuan / 1e8  # 亿
        change_pct = turnover.get("change_pct", 0)
        # A 股惯例:放量红字,缩量绿字
        is_fang = change_pct >= 0
        color_class = "profit-positive" if is_fang else "profit-negative"
        label = "放量" if is_fang else "缩量"
        sign = "+" if diff_yi >= 0 else ""
        change_text = f"{label}{sign}{diff_yi:.0f} 亿({sign}{change_pct:.2f}%) | 昨日 ¥{prev_yi:,.0f} 亿"
    else:
        color_class = ""
        change_text = "首日运行,无对照"
    
    return f"""<div class="metric-card" style="border-left-color: #f59e0b; max-width: 400px; margin: 0 auto;">
        <div class="metric-label">A 股成交额总计</div>
        <div class="metric-value">¥{today_yi:,.0f} 亿</div>
        <div class="metric-sub {color_class}" style="font-size: 13px; font-weight: 600;">较上一日 {change_text}</div>
    </div>"""


def render_overview_html(positions: List[Dict], account_data: Dict) -> str:
    """持仓全景(同花顺风格):总资产 / 总市值(仓位%)/ 总盈亏 / 可用资金"""
    total_mv = sum(p["market_value"] for p in positions)
    total_cost = sum(p["cost_value"] for p in positions)
    total_profit = total_mv - total_cost
    total_pct = (total_profit / total_cost * 100) if total_cost > 0 else 0
    profit_class = "profit-positive" if total_profit >= 0 else "profit-negative"
    
    available_cash = account_data.get("available_cash", 0)
    # 总资产 = 实时计算的市值 + 可用资金(不用持仓档固定值,跟随每日市值变动)
    total_assets = total_mv + available_cash
    position_pct = (total_mv / total_assets * 100) if total_assets > 0 else 0
    cash_pct = (available_cash / total_assets * 100) if total_assets > 0 else 0
    
    return f"""<div class="summary-grid">
        <div class="metric-card" style="border-left-color: #3b82f6;">
            <div class="metric-label">总资产</div>
            <div class="metric-value">¥{total_assets:,.0f}</div>
        </div>
        <div class="metric-card" style="border-left-color: #8b5cf6;">
            <div class="metric-label">总市值</div>
            <div class="metric-value">¥{total_mv:,.0f}</div>
            <div class="metric-sub">仓位 {position_pct:.1f}%</div>
        </div>
        <div class="metric-card" style="border-left-color: #10b981;">
            <div class="metric-label">总盈亏</div>
            <div class="metric-value {profit_class}">{total_profit:+,.0f}</div>
            <div class="metric-sub {profit_class}">{total_pct:+.2f}%</div>
        </div>
        <div class="metric-card" style="border-left-color: #f59e0b;">
            <div class="metric-label">可用资金</div>
            <div class="metric-value">¥{available_cash:,.0f}</div>
            <div class="metric-sub">占总资产 {cash_pct:.1f}%</div>
        </div>
    </div>"""


def render_ai_html(ai_section: str) -> str:
    """AI 分析段 HTML(保留换行,粗体)"""
    if not ai_section:
        return ""
    # MD → HTML 简化:换行变 <p>,**粗体**变 <strong>
    lines = ai_section.split("\n")
    parts = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("## "):
            parts.append(f"<h3>{process_inline(line[3:])}</h3>")
        elif line.startswith("### "):
            parts.append(f"<h4>{process_inline(line[4:])}</h4>")
        else:
            parts.append(f"<p>{process_inline(line)}</p>")
    return f'<div class="insight">{"".join(parts)}</div>'


def process_inline(text: str) -> str:
    """处理行内 **粗体**"""
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    return text


def render_report_html(
    account_name: str,
    positions: List[Dict],
    all_signals: Dict,
    index_data: Dict,
    decision: str,
    ai_section: str = None,
    date: str = None,
    account_data: Dict = None,
    turnover: Dict = None,
    ai_verified_signals: str = None,
    agent_data: Dict = None,
) -> str:
    """生成 HTML 报告(深色主题)"""
    if not date:
        date = now_cst().strftime("%Y-%m-%d")

    overview_html = render_overview_html(positions, account_data or {})
    table_html = render_data_table_html(positions)
    index_html = render_index_html(index_data)
    turnover_html = render_turnover_html(turnover or {})
    signals_html = render_signals_html(all_signals, ai_verified_signals)
    ai_html = render_ai_html(ai_section) if ai_section else ""

    # agent 预拉数据
    agent_html = ""
    if agent_data is not None:
        try:
            from core.agent_data import render_agent_data_sections
            holdings_codes = [p.get("code") for p in positions] if positions else None
            agent_html = render_agent_data_sections(agent_data, fmt="html", holdings=holdings_codes)
        except Exception as e:
            agent_html = f'<div class="section"><h2>⚠️ agent 数据渲染失败</h2><p>{e}</p></div>'
    
    # 操作信号 section 已删除(用户要求:直接看 DeepSeek 分析)
    
    ai_section_html = f"""
    <div class="section">
        <h2>🤖 AI 分析</h2>
        {ai_html}
    </div>""" if ai_html else ""

    # 数据来源标记（agent 预拉 vs GitHub fallback）
    if agent_data and agent_data.get("available"):
        data_source_tag = "📡 数据源: agent 预拉（增强）+ 新浪财经"
    else:
        data_source_tag = "📡 数据源: 新浪财经 API（fallback 模式）"
    
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>复盘报告 - {account_name} - {date}</title>
<style>{HTML_CSS}</style>
</head>
<body>
<div class="header">
    <h1>📊 Mavis 复盘报告</h1>
    <div class="date">{date} | {account_name} | 策略:中线趋势持有至年底</div>
    <div class="data-source">📅 报告生成时间:{now_cst().strftime("%Y.%m.%d %H:%M:%S")} | {data_source_tag}</div>
</div>

<div class="section">
    <h2>💰 持仓全景</h2>
    {overview_html}
</div>

<div class="section">
    <h2>📋 持仓明细</h2>
    {table_html}
</div>

<div class="section">
    <h2>🌡️ 大盘指数</h2>
    {index_html}
    <div style="margin-top: 16px;">
        {turnover_html}
    </div>
</div>
{agent_html}
{ai_section_html}

<div class="footer">
    报告生成时间:{now_cst().strftime("%Y.%m.%d %H:%M:%S")} | 数据源:新浪财经 API | 仅供个人复盘参考,不构成投资建议
</div>

</body>
</html>"""


def save_report(
    content: str,
    output_dir: Path,
    filename: str,
    format: str = "md",
) -> Path:
    """保存报告到 output_dir"""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{filename}.{format}"
    path.write_text(content, encoding="utf-8")
    return path


if __name__ == "__main__":
    # 自测
    positions = [
        {"code": "159516", "name": "半导体设备ETF国泰", "shares": 110000, "cost": 0.864,
         "current_price": 0.670, "market_value": 73700, "cost_value": 95040, "profit_pct": -22.45, "is_core": True},
    ]
    from analyze import check_five_things, make_decision
    main_pos = positions[0]
    index_data = {"上证": 3832, "深证": 13578, "创业板": 3343}
    five = check_five_things(main_pos, index_data, bubble_signs=0)
    decision = make_decision(five, {})
    
    html = render_report_html("主账户", positions, five, index_data, decision, "AI 测试段。", "2026-07-31")
    with open("/tmp/test.html", "w") as f:
        f.write(html)
    print("✅ 写 /tmp/test.html")
    print(f"大小: {len(html)} 字符")

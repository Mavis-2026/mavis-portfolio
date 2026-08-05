"""
core/agent_data.py
- 加载我（agent）预拉的数据：data/YYYY-MM-DD/{price_vs_ma,volume_price,weibo,meta}.json
- 提供报告渲染用的 4 段内容
- 如果 data 缺失，has_agent_data() 返回 False，渲染时显示"—"
"""
import json
import sys
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).parent
ROOT_DIR = SCRIPT_DIR.parent
DATA_DIR = ROOT_DIR / "data"


def load_agent_data(date: str) -> dict:
    """加载某天的预拉数据"""
    out = {
        "date": date,
        "available": False,
        "fallback": True,
        "meta_exists": False,
        "price_vs_ma": {},
        "volume_price": {},
        "weibo": {},
        "meta": {},
    }
    date_dir = DATA_DIR / date
    if not date_dir.exists():
        return out

    for name in ["price_vs_ma", "volume_price", "weibo", "meta"]:
        path = date_dir / f"{name}.json"
        if path.exists():
            try:
                out[name] = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
    # 至少 price_vs_ma 或 volume_price 有数据 = available
    pvm = out["price_vs_ma"]
    vp = out["volume_price"]
    if any(isinstance(v, dict) and "error" not in v and "current" in v for v in pvm.values()):
        out["available"] = True
    elif any(isinstance(v, dict) and "error" not in v and "vol_ratio" in v for v in vp.values()):
        out["available"] = True

    meta = out["meta"]
    if meta and "fallback" in meta:
        out["fallback"] = bool(meta["fallback"])

    # meta 存在 = agent 跑过（即使部分 fail 也算）
    if meta and meta.get("date") == date:
        out["meta_exists"] = True
    else:
        out["meta_exists"] = False

    return out


def has_agent_data(agent_data: dict) -> bool:
    # meta 存在 = agent 跑过（即使部分 fail）
    if agent_data and agent_data.get("meta_exists"):
        return True
    return bool(agent_data and agent_data.get("available"))


def _row(value, fmt="{:.3f}", default="—"):
    if value is None:
        return default
    if isinstance(value, bool):
        return "✅" if value else "❌"
    if isinstance(value, (int, float)):
        try:
            return fmt.format(value)
        except (ValueError, TypeError):
            return str(value)
    return str(value)


def render_price_vs_ma_md(agent_data: dict) -> str:
    data = agent_data.get("price_vs_ma", {})
    if not data:
        return ""
    lines = ["", "## 📊 价格 vs 均价（agent 预拉）", ""]
    lines.append("| 代码 | 名称 | 当前 | MA20 | MA60 | MA120 | 年内位置 | 看多信号 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for code, row in data.items():
        if "error" in row:
            lines.append(f"| {code} | {row.get('name','')} | ⚠️ 拉取失败 | — | — | — | — | — |")
            continue
        signals = []
        if row.get("above_ma20"): signals.append(">MA20")
        if row.get("above_ma60"): signals.append(">MA60")
        if row.get("above_ma120"): signals.append(">MA120")
        if row.get("above_year_avg"): signals.append(">年均")
        lines.append(f"| {code} | {row.get('name','')} | {_row(row.get('current'))} | {_row(row.get('ma20'))} | {_row(row.get('ma60'))} | {_row(row.get('ma120'))} | {_row(row.get('year_pct'), '{:.1%}')} | {','.join(signals) or '—'} |")
    return "\n".join(lines)


def render_price_vs_ma_html(agent_data: dict) -> str:
    data = agent_data.get("price_vs_ma", {})
    if not data:
        return ""
    rows = []
    for code, row in data.items():
        if "error" in row:
            rows.append(f"<tr><td>{code}</td><td>{row.get('name','')}</td><td colspan='6' style='color:#f59e0b'>⚠️ 拉取失败</td></tr>")
            continue
        signals = []
        if row.get("above_ma20"): signals.append(">MA20")
        if row.get("above_ma60"): signals.append(">MA60")
        if row.get("above_ma120"): signals.append(">MA120")
        if row.get("above_year_avg"): signals.append(">年均")
        rows.append(f"""
        <tr>
            <td>{code}</td>
            <td>{row.get('name','')}</td>
            <td>{_row(row.get('current'))}</td>
            <td>{_row(row.get('ma20'))}</td>
            <td>{_row(row.get('ma60'))}</td>
            <td>{_row(row.get('ma120'))}</td>
            <td>{_row(row.get('year_pct'), '{:.1%}')}</td>
            <td>{','.join(signals) or '—'}</td>
        </tr>""")
    return f"""
    <div class="section">
        <h2>📊 价格 vs 均价（agent 预拉）</h2>
        <table class="data-table">
            <thead>
                <tr><th>代码</th><th>名称</th><th>当前</th><th>MA20</th><th>MA60</th><th>MA120</th><th>年内位置</th><th>看多信号</th></tr>
            </thead>
            <tbody>{''.join(rows)}</tbody>
        </table>
    </div>"""


def render_volume_price_md(agent_data: dict) -> str:
    data = agent_data.get("volume_price", {})
    if not data:
        return ""
    lines = ["", "## 📈 量价配合（agent 预拉）", ""]
    lines.append("| 代码 | 名称 | 量比 | 5日价变% | 5日量变% | 5日均换手% | 量价配合 | 信号 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for code, row in data.items():
        if "error" in row:
            lines.append(f"| {code} | {row.get('name','')} | ⚠️ 失败 | — | — | — | — | — |")
            continue
        aligned = "✅" if row.get("price_vol_aligned") else "❌"
        signal = row.get("signal", "—")
        signal_color = "🟢" if signal == "看多" else "🔴" if signal == "看空" else "🟡"
        lines.append(f"| {code} | {row.get('name','')} | {_row(row.get('vol_ratio'))} | {_row(row.get('price_change_5d'), '{:+.2f}')}% | {_row(row.get('vol_change_5d'), '{:+.1f}')}% | {_row(row.get('avg_turnover_5d'))}% | {aligned} | {signal_color} {signal} |")
    return "\n".join(lines)


def render_volume_price_html(agent_data: dict) -> str:
    data = agent_data.get("volume_price", {})
    if not data:
        return ""
    rows = []
    for code, row in data.items():
        if "error" in row:
            rows.append(f"<tr><td>{code}</td><td>{row.get('name','')}</td><td colspan='6' style='color:#f59e0b'>⚠️ 拉取失败</td></tr>")
            continue
        aligned = "✅" if row.get("price_vol_aligned") else "❌"
        signal = row.get("signal", "—")
        signal_color = "#10b981" if signal == "看多" else "#ef4444" if signal == "看空" else "#f59e0b"
        rows.append(f"""
        <tr>
            <td>{code}</td>
            <td>{row.get('name','')}</td>
            <td>{_row(row.get('vol_ratio'))}</td>
            <td>{_row(row.get('price_change_5d'), '{:+.2f}')}%</td>
            <td>{_row(row.get('vol_change_5d'), '{:+.1f}')}%</td>
            <td>{_row(row.get('avg_turnover_5d'))}%</td>
            <td>{aligned}</td>
            <td style="color:{signal_color}">{signal}</td>
        </tr>""")
    return f"""
    <div class="section">
        <h2>📈 量价配合（agent 预拉）</h2>
        <table class="data-table">
            <thead>
                <tr><th>代码</th><th>名称</th><th>量比</th><th>5日价变%</th><th>5日量变%</th><th>5日均换手%</th><th>配合</th><th>信号</th></tr>
            </thead>
            <tbody>{''.join(rows)}</tbody>
        </table>
    </div>"""




def render_weibo_md(agent_data: dict) -> str:
    data = agent_data.get("weibo", {})
    if not data:
        return ""
    matched = data.get("matched", [])
    titles = data.get("titles", [])
    lines = ["", "## 📱 微博舆情（agent 预拉）", ""]
    if matched:
        lines.append(f"**命中关键词：{len(matched)} 条**")
        lines.append("")
        for m in matched:
            lines.append(f"- [{m.get('keyword','')}] {m.get('title','')}")
    elif titles:
        lines.append(f"未命中关键词（Top {len(titles)} 无半导体/科技相关）")
    else:
        lines.append("⚠️ 微博数据未拉到")
    return "\n".join(lines)


def render_weibo_html(agent_data: dict) -> str:
    data = agent_data.get("weibo", {})
    if not data:
        return ""
    matched = data.get("matched", [])
    titles = data.get("titles", [])
    body = ""
    if matched:
        items = "".join(f"<li><b>[{m.get('keyword','')}]</b> {m.get('title','')}</li>" for m in matched)
        body = f'<p><b>命中关键词：{len(matched)} 条</b></p><ul>{items}</ul>'
    elif titles:
        body = f'<p style="color:#94a3b8">未命中关键词（Top {len(titles)} 无半导体/科技相关）</p>'
    else:
        body = '<p style="color:#f59e0b">⚠️ 微博数据未拉到</p>'
    return f'<div class="section"><h2>📱 微博舆情（agent 预拉）</h2>{body}</div>'


def render_agent_data_sections(agent_data: dict, fmt="md") -> str:
    """聚合 4 段，返回字符串"""
    if not has_agent_data(agent_data):
        if fmt == "md":
            return "\n\n> ⚠️ agent 预拉数据缺失，使用 GitHub 脚本拉（fallback 模式）\n"
        return '<div class="section"><h2>⚠️ agent 预拉数据缺失</h2><p>使用 GitHub 脚本拉（fallback 模式）</p></div>'

    if fmt == "md":
        parts = ["", "## 🆕 agent 预拉数据（增强）", ""]
        parts.append(render_price_vs_ma_md(agent_data))
        parts.append(render_volume_price_md(agent_data))
        parts.append(render_weibo_md(agent_data))
        return "\n".join(parts)
    else:
        parts = []
        parts.append(render_price_vs_ma_html(agent_data))
        parts.append(render_volume_price_html(agent_data))
        parts.append(render_weibo_html(agent_data))
        return "\n".join(parts)

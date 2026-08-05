"""
周复盘报告
- 复用 daily_review 的数据 + AI 5 维
- 标题用"周复盘报告"
- 5 维 = 本周持仓回顾 / 大盘周度走势 / 板块周度轮动 / 本周风险与下周机会 / 心理与下周计划
"""
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.fetch import fetch_all
from core.analyze import calc_position_metrics, get_all_signals
from core.turnover import get_a_share_turnover
from core.llm import call_deepseek, build_user_prompt, SYSTEM_PROMPT
from core.report import render_report_md, render_report_html
import json

# 路径(动态,本地 + GitHub 都能跑)
SCRIPT_DIR = Path(__file__).parent
ROOT_DIR = SCRIPT_DIR.parent
PORTFOLIO_DIR = ROOT_DIR / "portfolio"
REPORTS_DIR = ROOT_DIR / "docs" / "reports"


def load_holdings():
    path = PORTFOLIO_DIR / "holdings.json"
    if not path.exists():
        raise FileNotFoundError(f"持仓档不存在:{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def run_account(account_id: str, account_data: dict, quotes: dict, date: str, week_range: str):
    """复盘单个账户"""
    account_name = account_data.get("name", account_id)
    print(f"  📊 周复盘 {account_id}({account_name})...")

    # 1. 计算每只持仓的指标
    positions = []
    for pos in account_data["holdings"]:
        code_with_ex = pos["exchange"] + pos["code"]
        quote = quotes.get(code_with_ex)
        if not quote or not quote.get("price"):
            print(f"  ⚠️ 持仓 {pos['code']} 数据缺失,跳过")
            continue
        current_price = quote["price"]
        open_price = quote.get("open")

        # 估值分位(60 天 K 线)
        from core.fetch import fetch_valuation_percentile
        valuation_pct = fetch_valuation_percentile(code_with_ex, days=365)

        positions.append(calc_position_metrics(pos, current_price, open_price, valuation_pct))

    # 2. 指数数据
    index_data = {
        "上证": quotes.get("sh000001", {}).get("price", 0),
        "深证": quotes.get("sz399001", {}).get("price", 0),
        "创业板": quotes.get("sz399006", {}).get("price", 0),
        "上证_change_pct": quotes.get("sh000001", {}).get("change_pct", 0),
        "深证_change_pct": quotes.get("sz399001", {}).get("change_pct", 0),
        "创业板_change_pct": quotes.get("sz399006", {}).get("change_pct", 0),
    }

    # 3. A 股成交额
    turnover = get_a_share_turnover()

    # 4. 信号
    all_signals = get_all_signals(positions, index_data)

    # 5. 决策
    decision = "周复盘"

    # 6. AI 5 维(周复盘模式)
    user_prompt = build_user_prompt(
        account_name, positions, all_signals, index_data,
        decision, turnover, report_type="周复盘"
    )
    print(f"  🤖 调 DeepSeek({account_id})[周复盘模式,5维]...")
    ai_result = call_deepseek(SYSTEM_PROMPT, user_prompt)
    ai_section = ai_result["content"]
    usage = ai_result.get("usage", {})
    print(f"  ✅ AI 段 {len(ai_section)} 字 | tokens: 输入 {usage.get('prompt_tokens', 0)} / 输出 {usage.get('completion_tokens', 0)} / 合计 {usage.get('total_tokens', 0)}")

    # 7. 生成报告
    md_content = render_report_md(account_name, positions, all_signals, index_data, decision, ai_section, date, turnover)
    html_content = render_report_html(account_name, positions, all_signals, index_data, decision, ai_section, date, account_data, turnover)

    # 8. 改标题为周复盘
    md_content = md_content.replace("Mavis 复盘", f"Mavis 周复盘(本周 {week_range})")
    html_content = html_content.replace("Mavis 复盘报告", f"Mavis 周复盘报告(本周 {week_range})")
    html_content = html_content.replace("策略:中线趋势持有至年底", f"策略:中线趋势持有至年底 | 报告类型:周复盘")

    # 9. 保存
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"weekly-review-{date}-{account_id}"
    md_path = REPORTS_DIR / f"{filename}.md"
    html_path = REPORTS_DIR / f"{filename}.html"
    md_path.write_text(md_content, encoding="utf-8")
    html_path.write_text(html_content, encoding="utf-8")
    print(f"  ✅ {account_id} 周报:{html_path}")
    return html_path


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--account", default="both", choices=["main", "sub2", "both"])
    args = p.parse_args()

    holdings = load_holdings()
    accounts = holdings["accounts"]
    if args.account == "both":
        target = [("main", accounts["main"]), ("sub2", accounts["sub2"])]
    else:
        target = [(args.account, accounts[args.account])]

    # 周范围(本周一到今天) - 用 Asia/Shanghai 时区
    from core.report import now_cst
    today = now_cst().replace(tzinfo=None)  # naive datetime 用于 weekday
    monday = today - timedelta(days=today.weekday())
    week_range = f"{monday.strftime('%m.%d')}-{today.strftime('%m.%d')}"
    date = today.strftime("%Y-%m-%d")

    print(f"[{date}] 开始周复盘(本周 {week_range})...")

    # 1. 拉数据
    print("  📡 拉取实时行情...")
    quotes = fetch_all()
    print(f"  ✅ 拉到 {len(quotes)} 个代码数据")

    # 2. 逐个周复盘
    paths = []
    for acc_id, acc_data in target:
        try:
            p = run_account(acc_id, acc_data, quotes, date, week_range)
            paths.append(p)
        except Exception as e:
            print(f"  ❌ {acc_id} 失败:{e}")

    print(f"\n✅ 周复盘完成,{len(paths)} 个报告")
    for p in paths:
        print(f"  - {p}")


if __name__ == "__main__":
    main()

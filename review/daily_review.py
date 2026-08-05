#!/usr/bin/env python3
"""
review/daily_review.py - 复盘主脚本(阶段 2:数据 + 5 件事 + AI)
- 100% 手动触发
- 2 账户独立分析
- 5 件事触发才写
- AI 失败 → sys.exit(1),不出报告
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# 优先从 .env 读 DEEPSEEK_API_KEY (覆盖网关 export 的旧 key)
ENV_FILE = Path("/root/.openclaw/.env")
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k] = v

# 路径
SCRIPT_DIR = Path(__file__).parent
ROOT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT_DIR))

from core.fetch import fetch_all
from core.analyze import calc_position_metrics, get_all_signals, make_decision_summary
from core.report import render_report_md, render_report_html, save_report, now_cst
from core.llm import call_deepseek, build_user_prompt, SYSTEM_PROMPT
from core.turnover import get_a_share_turnover
from core.agent_data import load_agent_data, has_agent_data, render_agent_data_sections


def load_holdings() -> dict:
    """加载持仓档"""
    path = ROOT_DIR / "portfolio" / "holdings.json"
    if not path.exists():
        raise FileNotFoundError(f"持仓档不存在:{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def review_account(account_id: str, account_data: dict, quotes: dict, output_dir: Path, date: str) -> Path:
    """
    复盘单个账户
    返回报告路径
    """
    # 1. 计算每只持仓的指标
    positions = []
    for pos in account_data["holdings"]:
        code_with_ex = pos["exchange"] + pos["code"]
        quote = quotes.get(code_with_ex)
        if not quote or not quote.get("price"):
            raise RuntimeError(f"账户 {account_id} 持仓 {pos['code']} 数据缺失")
        current_price = quote["price"]
        open_price = quote.get("open")  # 今开价(急杀检测用)

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
    
    # 3. A 股成交额 + 放缩量
    turnover = get_a_share_turnover()
    
    # 4. 所有 ETF 信号汇总(全平等 + 急杀 + 大盘)
    all_signals = get_all_signals(positions, index_data)
    
    # 5. 决策(1 句话)
    decision = make_decision_summary(all_signals)
    
    # 6. AI 分析(必须成功,失败抛异常)
    account_name = account_data.get("name", account_id)
    user_prompt = build_user_prompt(account_name, positions, all_signals, index_data, decision, turnover, report_type="复盘")
    print(f"  🤖 调 DeepSeek({account_id})[复盘模式,5维]...")
    ai_result = call_deepseek(SYSTEM_PROMPT, user_prompt)
    ai_section = ai_result["content"]
    usage = ai_result.get("usage", {})
    print(f"  ✅ AI 段 {len(ai_section)} 字 | tokens: 输入 {usage.get('prompt_tokens', 0)} / 输出 {usage.get('completion_tokens', 0)} / 合计 {usage.get('total_tokens', 0)}")

    # 6.5 操作信号段已删除,直接跳到生成报告

    # 7. 生成报告
    agent_data = load_agent_data(date)
    agent_data_used = has_agent_data(agent_data)
    md_content = render_report_md(account_name, positions, all_signals, index_data, decision, ai_section, date, turnover, agent_data=agent_data)
    html_content = render_report_html(account_name, positions, all_signals, index_data, decision, ai_section, date, account_data, turnover, agent_data=agent_data)
    
    # 8. 保存
    filename = f"daily-review-{date}-{account_id}"
    md_path = save_report(md_content, output_dir, filename, "md")
    html_path = save_report(html_content, output_dir, filename, "html")
    
    return html_path


def main():
    parser = argparse.ArgumentParser(description="Mavis 复盘 v2.0(阶段 2)")
    parser.add_argument("--account", choices=["main", "sub2", "both"], default="both",
                        help="账户:main / sub2 / both")
    parser.add_argument("--output-dir", type=Path, default=ROOT_DIR / "docs" / "reports",
                        help="输出目录(默认 docs/reports,适配 GitHub Pages)")
    args = parser.parse_args()
    
    date = now_cst().strftime("%Y-%m-%d")
    
    print(f"[{date}] 开始复盘(账户:{args.account})...")
    
    # 1. 加载持仓
    try:
        holdings = load_holdings()
    except Exception as e:
        print(f"❌ 持仓档加载失败:{e}")
        sys.exit(1)
    
    # 2. 拉数据
    try:
        print(f"  📡 拉取实时行情...")
        quotes = fetch_all()
        print(f"  ✅ 拉到 {len(quotes)} 个代码数据")
    except Exception as e:
        print(f"❌ 数据拉取失败:{e}")
        sys.exit(1)
    
    # 3. 选账户
    accounts = holdings["accounts"]
    if args.account == "both":
        target = [("main", accounts["main"]), ("sub2", accounts["sub2"])]
    else:
        target = [(args.account, accounts[args.account])]
    
    # 4. 逐个复盘
    paths = []
    for acc_id, acc_data in target:
        try:
            print(f"  📊 复盘 {acc_id}({acc_data['name']})...")
            path = review_account(acc_id, acc_data, quotes, args.output_dir, date)
            paths.append(path)
            print(f"  ✅ {acc_id} 报告:{path.name}")
        except Exception as e:
            print(f"❌ 账户 {acc_id} 复盘失败:{e}")
            sys.exit(1)
    
    print(f"\n✅ 复盘完成,{len(paths)} 个报告")
    for p in paths:
        print(f"  - {p}")


if __name__ == "__main__":
    main()

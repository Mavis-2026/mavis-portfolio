"""
core/turnover.py - A 股成交额放缩量对比
- 方案 B:本地存每日成交额
- 今天跑时存今日数据到 data/turnover-YYYY-MM-DD.json
- 明天跑时读昨日文件 → 对比
- 第一天:无对照数据
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

DATA_DIR = Path(__file__).parent.parent / "data"


def save_today_turnover(total_yuan: float, sh: float, sz: float) -> Path:
    """
    保存今日成交额
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    data = {
        "date": today,
        "total_yuan": total_yuan,
        "sh_yuan": sh,
        "sz_yuan": sz,
    }
    path = DATA_DIR / f"turnover-{today}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def get_yesterday_turnover() -> Optional[Dict]:
    """
    读昨日成交额
    返回 None = 没数据(首日)
    """
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    # 周末处理:周五 → 周一,取周五数据
    for i in range(1, 5):  # 最多往前 4 天(覆盖周末)
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        path = DATA_DIR / f"turnover-{date}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    return None


def calc_change_pct(today: float, yesterday: float) -> float:
    """
    算放缩量百分比
    """
    if yesterday <= 0:
        return 0
    return (today - yesterday) / yesterday * 100


def get_a_share_turnover() -> Dict:
    """
    从 fetch.py 拿 A 股总成交额(无 deps,直接 fetch 一次)
    返回 {today_yuan, sh_yuan, sz_yuan, yesterday_yuan, change_pct}
    """
    # 动态 import 避免循环
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from fetch import fetch_quotes
    
    data = fetch_quotes(["sh000001", "sz399001"])
    sh = float(data.get("sh000001", {}).get("turnover", 0) or 0)
    sz = float(data.get("sz399001", {}).get("turnover", 0) or 0)
    today = sh + sz
    
    result = {
        "today_yuan": today,
        "sh_yuan": sh,
        "sz_yuan": sz,
    }
    
    # 拿昨日对比
    yesterday_data = get_yesterday_turnover()
    if yesterday_data:
        yesterday = yesterday_data.get("total_yuan", 0)
        result["yesterday_yuan"] = yesterday
        result["change_pct"] = calc_change_pct(today, yesterday)
        result["has_comparison"] = True
    else:
        result["yesterday_yuan"] = 0
        result["change_pct"] = 0
        result["has_comparison"] = False
    
    # 保存今日
    save_today_turnover(today, sh, sz)
    
    return result


if __name__ == "__main__":
    r = get_a_share_turnover()
    today_yi = r["today_yuan"] / 1e8
    print(f"A 股今日成交额:¥{today_yi:,.2f} 亿")
    if r["has_comparison"]:
        yes_yi = r["yesterday_yuan"] / 1e8
        print(f"A 股昨日成交额:¥{yes_yi:,.2f} 亿")
        print(f"放缩量:{r['change_pct']:+.2f}%")
    else:
        print("首日运行,无对照数据")

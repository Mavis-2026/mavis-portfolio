#!/usr/bin/env python3
"""
盘中实时监控脚本 - Mavis客户
================================
- 每 30 分钟拉一次主仓价格
- 智能判断关键位,只在临界/突破时提醒
- 同一价格区间每天最多推 1 次,避免骚扰
- 写入告警文件,供收盘报告合并
- 9:25-11:30 / 13:00-15:00 交易时段
"""
import json
import re
import sys
import urllib.request
from datetime import datetime, time as dt_time
from pathlib import Path

# 自动 cd 到仓库根目录
import os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
os.chdir(REPO_ROOT)

sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
from dingding_sender import send_markdown, send_text
from news_fetcher import get_relevant_news, format_news_for_dingding

WORKSPACE = Path(REPO_ROOT)
PORTFOLIO_FILE = WORKSPACE / "portfolio" / "holdings.json"
ALERTS_DIR = WORKSPACE / "alerts"
ALERTS_DIR.mkdir(parents=True, exist_ok=True)

with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
    portfolio = json.load(f)

# 关键位定义
KEY_LEVELS = {
    "加仓位": {"price": 0.65, "type": "buy", "label": "🟢 加仓信号", "warn_pct": 2.0},
    "止损位": {"price": 0.648, "type": "stop", "label": "🛑 止损警告", "warn_pct": 1.5},
    "回本减仓": {"price": 0.864, "type": "sell", "label": "🔴 回本减仓", "warn_pct": 2.0},
    "第一止盈": {"price": 0.90, "type": "sell", "label": "🔴 第一止盈", "warn_pct": 2.0},
    "强压力位": {"price": 1.00, "type": "milestone", "label": "🟡 突破1元心理位", "warn_pct": 1.5},
}

# 主仓代码
MAIN_CODE = "159516"
MAIN_EXCHANGE = "sz"

# 告警状态文件(记录今天已经推送过的告警,避免重复)
ALERT_STATE_FILE = ALERTS_DIR / "alert_state.json"


def load_alert_state():
    """加载告警状态(今天已推送过的)"""
    if ALERT_STATE_FILE.exists():
        with open(ALERT_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"date": "", "triggered": []}


def save_alert_state(state):
    with open(ALERT_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def is_trading_time():
    """判断当前是否交易时段"""
    now = datetime.now().time()
    morning_start = dt_time(9, 25)
    morning_end = dt_time(11, 35)
    afternoon_start = dt_time(13, 0)
    afternoon_end = dt_time(15, 5)  # 收盘后5分钟内也监控

    return (morning_start <= now <= morning_end) or (afternoon_start <= now <= afternoon_end)


def fetch_main_position():
    """拉取主仓实时价"""
    url = f"https://hq.sinajs.cn/list={MAIN_EXCHANGE}{MAIN_CODE}"
    req = urllib.request.Request(url, headers={
        "Referer": "https://finance.sina.com.cn",
        "User-Agent": "Mozilla/5.0"
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read().decode("gbk", errors="ignore")
        m = re.search(rf'var hq_str_{MAIN_EXCHANGE}{MAIN_CODE}="([^"]+)"', data)
        if m:
            fields = m.group(1).split(",")
            return {
                "name": fields[0],
                "open": float(fields[1]),
                "prev_close": float(fields[2]),
                "price": float(fields[3]),
                "high": float(fields[4]),
                "low": float(fields[5]),
                "change_pct": ((float(fields[3]) - float(fields[2])) / float(fields[2])) * 100,
                "time": fields[31]
            }
    except Exception as e:
        print(f"⚠️ 拉取失败: {e}")
    return None


def check_levels(current_price, triggered_today):
    """检查是否触发关键位"""
    triggered = []

    for name, info in KEY_LEVELS.items():
        target = info["price"]
        warn_pct = info["warn_pct"]

        # 已触发
        if info["type"] in ["buy", "stop"] and current_price <= target:
            level = "强触发" if current_price <= target * 0.998 else "触发"
            triggered.append({
                "name": name,
                "label": info["label"],
                "level": level,
                "target": target,
                "current": current_price,
                "distance": (current_price - target) / target * 100,
                "msg": f"主仓价 {current_price:.3f} {'已到' if current_price <= target else '接近'} {name}({target})",
                "action": "考虑分批加仓" if info["type"] == "buy" else "准备止损评估"
            })
        elif info["type"] in ["sell", "milestone"] and current_price >= target:
            level = "强触发" if current_price >= target * 1.002 else "触发"
            triggered.append({
                "name": name,
                "label": info["label"],
                "level": level,
                "target": target,
                "current": current_price,
                "distance": (current_price - target) / target * 100,
                "msg": f"主仓价 {current_price:.3f} {'已到' if current_price >= target else '接近'} {name}({target})",
                "action": "考虑分批止盈" if info["type"] == "sell" else "突破关键位,关注能否站稳"
            })
        # 预警(距离关键位 < warn_pct%)
        else:
            if info["type"] in ["buy", "stop"]:
                distance_pct = (current_price - target) / current_price * 100
                if 0 < distance_pct <= warn_pct:
                    triggered.append({
                        "name": name,
                        "label": "⚠️ 预警",
                        "level": "预警",
                        "target": target,
                        "current": current_price,
                        "distance": distance_pct,
                        "msg": f"主仓价 {current_price:.3f} 距 {name}({target}) 仅 {distance_pct:.1f}%",
                        "action": "关注后续走势"
                    })
            else:
                distance_pct = (target - current_price) / current_price * 100
                if 0 < distance_pct <= warn_pct:
                    triggered.append({
                        "name": name,
                        "label": "⚠️ 预警",
                        "level": "预警",
                        "target": target,
                        "current": current_price,
                        "distance": distance_pct,
                        "msg": f"主仓价 {current_price:.3f} 距 {name}({target}) 仅 {distance_pct:.1f}%",
                        "action": "关注后续走势"
                    })

    # 过滤掉今天已推送过的
    new_triggered = [t for t in triggered if t["name"] not in triggered_today]
    return new_triggered


def write_alert_file(alerts, current_price, change_pct):
    """写入告警文件"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    content = f"""# 🚨 关键位提醒

**时间**:{timestamp}
**主仓价**:{current_price:.3f} ({change_pct:+.2f}%)

"""
    if alerts:
        for a in alerts:
            content += f"""
## {a['label']} {a['level']}

- **{a['name']}**:{a['msg']}
- 关键位:{a['target']:.3f}
- 当前价:{a['current']:.3f}
- 距离:{a['distance']:+.2f}%
- **建议操作**:{a['action']}

"""
    else:
        content += "\n✅ 当前无关键位触发,继续持有观望。\n"

    content += f"\n---\n*此告警由盘中监控系统自动生成,30分钟轮询一次*\n"

    alert_file = ALERTS_DIR / "latest.txt"
    with open(alert_file, "w", encoding="utf-8") as f:
        f.write(content)

    # 同时追加到历史告警
    history_file = ALERTS_DIR / "history.log"
    with open(history_file, "a", encoding="utf-8") as f:
        f.write(f"\n[{timestamp}] 主仓 {current_price:.3f} ({change_pct:+.2f}%)\n")
        if alerts:
            for a in alerts:
                f.write(f"  {a['label']} {a['level']} - {a['name']} {a['msg']}\n")
        else:
            f.write(f"  无触发\n")

    return content


def push_to_dingding(alerts, current_price, change_pct):
    """推送到钉钉"""
    if not alerts:
        return
    try:
        title = "🚨 关键位提醒"
        md = f"## 🚨 关键位提醒\n\n"
        md += f"**时间**:{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n"
        md += f"**主仓价**:`{current_price:.3f}` ({change_pct:+.2f}%)\n\n"
        md += "---\n\n"

        for a in alerts:
            md += f"### {a['label']} {a['level']}\n\n"
            md += f"- **{a['name']}**:{a['msg']}\n"
            md += f"- 关键位:`{a['target']:.3f}`\n"
            md += f"- 当前价:`{a['current']:.3f}`\n"
            md += f"- 距离:{a['distance']:+.2f}%\n"
            md += f"- **建议操作**:{a['action']}\n\n"

        md += "\n---\n*由 Mavis 投资助理自动推送*"
        result = send_markdown(title, md)
        return result
    except Exception as e:
        print(f"⚠️ 钉钉推送失败: {e}")
        return None


def main():
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    # 非交易日检查(周末)
    if now.weekday() >= 5:
        print(f"[{now.strftime('%H:%M')}] 周末,不监控")
        return

    # 交易时段检查
    if not is_trading_time():
        print(f"[{now.strftime('%H:%M')}] 非交易时段,跳过")
        return

    # 加载告警状态
    state = load_alert_state()
    if state["date"] != today_str:
        # 新的一天,重置
        state = {"date": today_str, "triggered": []}

    # 拉取主仓
    pos = fetch_main_position()
    if not pos:
        print(f"[{now.strftime('%H:%M')}] ❌ 拉取失败")
        return

    # 检查关键位
    alerts = check_levels(pos["price"], state["triggered"])

    # 写入告警文件
    content = write_alert_file(alerts, pos["price"], pos["change_pct"])

    # 更新告警状态
    if alerts:
        state["triggered"].extend([a["name"] for a in alerts])
        save_alert_state(state)
        print(f"[{now.strftime('%H:%M')}] 🚨 触发 {len(alerts)} 个告警")
        for a in alerts:
            print(f"  - {a['label']} {a['name']} ({a['msg']})")
        # 推送到钉钉
        result = push_to_dingding(alerts, pos["price"], pos["change_pct"])
        if result and result.get("success"):
            print(f"  ✅ 已推送到钉钉")
        else:
            print(f"  ❌ 钉钉推送失败: {result}")
    else:
        print(f"[{now.strftime('%H:%M')}] ✅ 主仓 {pos['price']:.3f} ({pos['change_pct']:+.2f}%),无触发")


if __name__ == "__main__":
    main()

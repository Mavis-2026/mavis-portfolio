#!/usr/bin/env python3
"""
新闻抓取模块 - 抓取并过滤半导体/设备相关快讯
- 数据源:新浪财经快讯
- 关键词过滤:半导体、设备、芯片、刻蚀、薄膜、晶圆、中芯、长鑫、台积电等
- 影响判定:利好/利空/中性
"""
import json
import re
import urllib.request
from datetime import datetime
from pathlib import Path

# 半导体/设备相关关键词
KEYWORDS_POSITIVE = [
    "半导体", "芯片", "设备", "刻蚀", "薄膜", "沉积", "CMP", "光刻",
    "晶圆", "封测", "测试设备", "量检测", "北方华创", "中微", "拓荆",
    "华海清科", "长川", "华峰测控", "中科飞测", "盛美", "国产",
    "AI", "算力", "存储", "DRAM", "NAND", "HBM", "中芯国际", "长鑫",
    "长江存储", "台积电", "美光", "SK海力士", "订单", "扩产", "上调"
]

KEYWORDS_NEGATIVE = [
    "出口管制", "制裁", "禁令", "脱钩", "打压", "卡脖子", "断供",
    "下行", "下滑", "暴跌", "砍单", "降价", "价格战", "减产"
]


def fetch_news():
    """从新浪财经拉取快讯"""
    url = "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2516&num=30&versionNumber=1.2.4&page=1"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://finance.sina.com.cn/",
        "Origin": "https://finance.sina.com.cn"
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        items = data.get('result', {}).get('data', [])
        return items
    except Exception as e:
        print(f"⚠️ 新闻拉取失败: {e}")
        return []


def classify_news(title, content):
    """分类新闻的相关性和情绪"""
    text = (title + " " + content).lower()

    # 正面关键词
    pos_count = sum(1 for kw in KEYWORDS_POSITIVE if kw.lower() in text)
    # 负面关键词
    neg_count = sum(1 for kw in KEYWORDS_NEGATIVE if kw.lower() in text)
    # 匹配的关键词
    matched = [kw for kw in KEYWORDS_POSITIVE if kw.lower() in text][:3]

    is_relevant = pos_count >= 1

    # 情绪判断
    if neg_count > 0 and pos_count == 0:
        sentiment = "negative"
    elif pos_count > 0 and neg_count == 0:
        sentiment = "positive"
    elif pos_count > neg_count:
        sentiment = "positive"
    elif neg_count > pos_count:
        sentiment = "negative"
    else:
        sentiment = "neutral"

    return {
        "is_relevant": is_relevant,
        "relevance_score": pos_count,
        "sentiment": sentiment,
        "matched_keywords": matched
    }


def get_relevant_news(max_count=5):
    """获取与持仓相关的新闻"""
    items = fetch_news()
    if not items:
        return []

    relevant = []
    for item in items:
        title = (item.get('title') or '').strip()
        content = (item.get('intro') or item.get('content') or '').strip()
        ctime = item.get('ctime', 0)

        if not title or len(title) < 5:
            continue

        c = classify_news(title, content)
        if c["is_relevant"]:
            try:
                time_str = datetime.fromtimestamp(int(ctime)).strftime("%H:%M")
            except:
                time_str = ""

            relevant.append({
                "title": title,
                "content": content[:100] if content else "",
                "time_str": time_str,
                "url": item.get('url', ''),
                "sentiment": c["sentiment"],
                "relevance_score": c["relevance_score"],
                "keywords": c["matched_keywords"]
            })

    relevant.sort(key=lambda x: (x["relevance_score"]), reverse=True)
    return relevant[:max_count]


def format_news_for_dingding(news_list, max_items=5):
    """格式化为钉钉 Markdown"""
    if not news_list:
        return "📰 今日暂无与持仓直接相关的板块新闻"

    md = "## 📰 板块要闻(与持仓相关)\\n\\n"
    emoji_map = {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}

    for n in news_list[:max_items]:
        emoji = emoji_map.get(n["sentiment"], "⚪")
        title = n["title"]
        if len(title) > 55:
            title = title[:52] + "..."
        md += f"{emoji} **{title}**\\n"
        if n.get("content"):
            c = n["content"]
            if len(c) > 80:
                c = c[:77] + "..."
            md += f"  > {c}\\n"
        meta = []
        if n.get("time_str"):
            meta.append(n["time_str"])
        if n.get("keywords"):
            meta.append(", ".join(n["keywords"][:2]))
        if meta:
            md += f"  <font color='gray' size='1'>{' | '.join(meta)}</font>\\n\\n"

    return md


if __name__ == "__main__":
    print("=== 抓取半导体相关新闻 ===\\n")
    news = get_relevant_news(8)
    print(f"📰 拿到 {len(news)} 条相关新闻:\\n")
    for n in news:
        emoji = {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}.get(n["sentiment"], "⚪")
        print(f"{emoji} [{n['time_str']}] {n['title']}")
        if n.get("keywords"):
            print(f"   关键词: {', '.join(n['keywords'])}")
        print()

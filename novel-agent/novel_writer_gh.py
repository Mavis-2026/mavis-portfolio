#!/usr/bin/env python3
"""
网文写作脚本 · GitHub Actions 版
- 流程: 剧情要点 → 初稿 → 检查 → 保存 chapters/chapter_N.txt
- 5 次 API 上限，失败不重试

用法（命令行参数）:
  python3 novel_writer.py --chapter 1 --plot "主角林凡是个普通大学生，意外获得金手指"
  python3 novel_writer.py --chapter 1 --plot "..." --out-dir ./chapters
"""
import os
import sys
import json
import argparse
import urllib.request
import urllib.error

# ========== 配置 ==========
MAX_API_CALLS = 5
CALL_COUNT = 0


def check_limit():
    global CALL_COUNT
    CALL_COUNT += 1
    if CALL_COUNT > MAX_API_CALLS:
        raise Exception(f"🛑 API 调用已达 {MAX_API_CALLS} 次上限，停止，等用户确认")


def call_moonshot(system_prompt, user_prompt, model="kimi-k3", max_tokens=8000):
    """调 Moonshot K3（4 层防跑飞）"""
    check_limit()
    url = "https://api.moonshot.cn/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 1.0,
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {os.environ.get('MOONSHOT_API_KEY', '')}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            msg = data["choices"][0]["message"]
            content = msg.get("content") or msg.get("reasoning_content") or ""
            usage = data.get("usage", {})

            # === 防跑飞 4 层 ===
            if not content:
                return "[Moonshot 空] 模型没返回内容（reasoning 跑飞）"
            output_tokens = usage.get("completion_tokens", len(content) // 2)
            if output_tokens > 6000:
                return f"[Moonshot 跑飞] 输出 {output_tokens} tokens > 6000 上限"
            meta_keywords = ["用户要求", "作为AI", "我来写", "思考", "我需要", "让我"]
            head = content[:200]
            meta_count = sum(1 for k in meta_keywords if k in head)
            if meta_count >= 2:
                return f"[Moonshot 自言自语] 前 200 字含 {meta_count} 个元话语"
            char_count = len(content)
            if char_count < 1500:
                return f"[Moonshot 太短] 仅 {char_count} 字 < 1500 下限"
            return content
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        return f"[Moonshot 错误] HTTP {e.code}: {body}"
    except Exception as e:
        return f"[Moonshot 错误] {e}"


def call_deepseek(system_prompt, user_prompt, max_tokens=2000):
    """调 DeepSeek chat（非 reasoning）"""
    check_limit()
    url = "https://api.deepseek.com/v1/chat/completions"
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {os.environ.get('DEEPSEEK_API_KEY', '')}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        return f"[DeepSeek 错误] HTTP {e.code}: {body}"
    except Exception as e:
        return f"[DeepSeek 错误] {e}"


# ========== Prompt 模板 ==========
WRITE_SYS = """你是起点中文网资深网文作家，正在扩写一章都市学霸文。

【输入】
下方会提供：
1. 【设定文档】—— 全书主角人设、女主、世界观、力量体系
2. 【本章剧情要点】—— 用户手写的 200-300 字剧情摘要

【你的任务】
严格按照以上两份输入，扩写本章正文为 3000-3500 字网文。
**不要自由发挥**：不要加新角色、不要改剧情走向、不要改人设。
**不要省略**：所有剧情要点中提到的情节必须出现。

【写作规范】
- 视角：第三人称（读者视角），不用第一人称"我"
- 主角称呼：使用【设定文档】中的姓名（如"林凡"）
- 风格：都市学霸爽文（节奏快、爽点足、有钩子）
- 字数：3000-3500 字
- 句式：短句为主，动作>心理>环境
- 对话：自然口语化，符合人物性格
- 章末钩子：留 1-2 个悬念（基于本章剧情自然延伸，不要引入新设定）

【输出格式】（强制）
===正文开始===
（3000-3500 字正文）
===正文结束===

【绝对禁止】
- 复述任何指令/设定/剧情要点
- 元话语（"用户要求..."、"我来写..."、"作为AI..."、"思考..."）
- 思考过程、分析、复盘
- 进入"思考模式"或"分析模式"——直接动笔写
- 用第一人称"我"叙述
- 改剧情走向或加新角色
- 输出任何正文外的内容（如评分、解释、备注）

【下章预告】（可选，章末 100 字内）
基于本章自然延伸，不要引入新设定。
"""
【要求】
- 第一句必须是动作或场景
- 字数 3000-3500
- 网文风：爽点+对话+章末钩子
- 用"我"，纯中文
"""

CHECK_SYS = """你是网文编辑。直接输出检查结果。

【字数】实际 X 字
【逻辑】通过/问题
【风格】通过/问题
【建议】50-150 字

不要复述指令，直接给结果。
"""


def write_chapter(chapter_num, plot_point, out_dir="chapters"):
    """写一章: 剧情要点 → 正文 → 检查 → 保存"""
    os.makedirs(out_dir, exist_ok=True)

    print(f"\n=== 第 {chapter_num} 章 ===")
    print(f"  📊 剩余 API 次数: {MAX_API_CALLS - CALL_COUNT}/{MAX_API_CALLS}")

    # 加载设定文档（如有）
    setting_path = "outlines/设定.md"
    setting_text = ""
    if os.path.exists(setting_path):
        with open(setting_path, encoding="utf-8") as f:
            setting_text = f.read()
        print(f"  📖 已加载设定文档 ({len(setting_text)} 字)")
    else:
        print(f"  ⚠️ 设定文档未找到: {setting_path}")

    # 拼装 user prompt
    user_prompt = ""
    if setting_text:
        user_prompt += f"【设定文档】\n{setting_text}\n\n"
    user_prompt += f"【本章剧情要点】\n{plot_point}\n\n"
    user_prompt += "请根据以上设定和剧情要点，扩写本章正文。"

    # 1. 写正文
    print("[1/2] 写正文 (kimi-k3)...")
    novel = call_moonshot(
        WRITE_SYS,
        user_prompt,
        model="kimi-k3",
    )
    # 降级
    if "错误" in novel or "空" in novel or len(novel) < 500:
        print(f"  ⚠️ K3 失败，降级到 v1-128k...")
        novel = call_moonshot(
            WRITE_SYS,
            user_prompt,
            model="moonshot-v1-128k",
        )
    if "错误" in novel or len(novel) < 500:
        print(f"  ❌ 写正文失败: {novel[:200]}")
        return None
    print(f"  ✅ 正文 {len(novel)} 字")

    # 2. 检查
    print("[2/2] DeepSeek 检查...")
    review = call_deepseek(
        CHECK_SYS,
        f"【正文】\n{novel}",
    )
    if "错误" in review or len(review) < 30:
        print(f"  ⚠️ 检查失败: {review[:100]}")
        review = "[检查失败，已跳过]"
    else:
        print(f"  ✅ 检查 {len(review)} 字")

    # 保存 (TXT + JSON)
    txt_path = f"{out_dir}/chapter_{chapter_num:02d}.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"=== 第 {chapter_num} 章 ===\n\n")
        f.write(novel)
        f.write(f"\n\n=== 检查报告 ===\n\n{review}\n")
    print(f"  💾 正文: {txt_path}")

    json_path = f"{out_dir}/chapter_{chapter_num:02d}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "chapter": chapter_num,
            "plot_point": plot_point,
            "novel": novel,
            "review": review,
            "char_count": len(novel),
            "api_calls_used": CALL_COUNT,
        }, f, ensure_ascii=False, indent=2)
    print(f"  💾 数据: {json_path}")

    print(f"  📊 用了 {CALL_COUNT}/{MAX_API_CALLS} 次 API")
    return {"novel": novel, "review": review}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="网文写作（GitHub Actions 版）")
    parser.add_argument("--chapter", type=int, required=True, help="章节号")
    parser.add_argument("--plot", type=str, required=True, help="剧情要点")
    parser.add_argument("--out-dir", type=str, default="chapters", help="输出目录")
    args = parser.parse_args()

    try:
        write_chapter(args.chapter, args.plot, args.out_dir)
    except Exception as e:
        print(f"\n🛑 {e}")
        sys.exit(1)

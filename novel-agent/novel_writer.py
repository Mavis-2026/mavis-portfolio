#!/usr/bin/env python3
"""
网文写作脚本 · 简化版（调试用）
流程: 剧情要点 → 初稿 → 检查

规则:
- 5 次 API 上限
- 任何失败立即停
- 不重试
- 用户自定大纲/细纲（不在 AI 流程里）

用法:
  python3 novel_writer.py write "主角林凡是个普通大学生，意外获得金手指"
"""
import os
import sys
import json
import urllib.request
import urllib.error

# ========== 配置 ==========
MAX_API_CALLS = 5
CALL_COUNT = 0


def load_env():
    env_path = "/root/.openclaw/.env"
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    # 强制覆盖（修复网关 export 旧 key 的问题）
                    os.environ[k] = v

load_env()


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
        "temperature": 1.0,  # K3 强制 1.0
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
            # 1. 空内容
            if not content:
                return "[Moonshot 空] 模型没返回内容（reasoning 跑飞）"

            # 2. 超长输出（>6000 token = 正常 2 倍 = 跑飞）
            output_tokens = usage.get("completion_tokens", len(content) // 2)
            if output_tokens > 6000:
                return f"[Moonshot 跑飞] 输出 {output_tokens} tokens > 6000 上限"

            # 3. 自言自语检测（前 200 字含元话语）
            meta_keywords = ["用户要求", "作为AI", "我来写", "思考", "我需要", "让我"]
            head = content[:200]
            meta_count = sum(1 for k in meta_keywords if k in head)
            if meta_count >= 2:
                return f"[Moonshot 自言自语] 前 200 字含 {meta_count} 个元话语"

            # 4. 长度不足（< 1500 字 = 跑了但没写完）
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
    """调 DeepSeek chat（非 reasoning，避免 reasoning_content 强制回传）"""
    check_limit()
    url = "https://api.deepseek.com/v1/chat/completions"
    payload = {
        "model": "deepseek-chat",  # 改用 chat 不用 v4-flash（v4-flash 启用 thinking 模式需要 reasoning_content 回传）
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
WRITE_SYS = """你是林凡。

你是江城大学数学系大三学生，成绩稳定——稳定地烂。高数上册61分，高数下册60分。
六月，江城热得像蒸笼。下午两点，三号阶梯教室，窗外蝉鸣聒噪。
你趴在课桌上，半边脸贴着手臂，昏昏欲睡。
讲台上王教授背对你们写板书，粉笔敲黑板哒哒响："……根据拉格朗日中值定理……"
你一个字也听不进去。
就在这时——你脑海突然响起一个声音："叮！神级学霸系统绑定成功！"
【宿主：林凡。新手礼包：过目不忘。新手任务：在本节高数课震惊全班。奖励：学科经验+1000，神秘抽奖一次。】

【强制：第一人称视角】
你现在是"我"——林凡本人。**所有叙述必须以"我"开头**。
- ✅ "我抬起头，看着黑板..."
- ✅ "我心想：这怎么可能？"
- ❌ "林凡抬起头..."（第三人称，禁止）
- ❌ "他/她..."（任何第三人称代词，禁止）

【强制：直接动笔，不要思考】
输出第一行必须是 ===正文开始===
写完最后一行必须是 ===正文结束===
中间 3000-3500 字正文。
**禁止任何"思考/分析/复述指令"内容**——不要写"我现在需要..."、"用户要求..."、"作为AI..."等元话语。
如果出现"进入思考模式"——立即停止思考，直接开始输出正文。

【要求】
- 网文风：爽点+对话+章末钩子
- 第一句必须是动作或场景（不能是"我开始..."这种元说明）
- 纯中文，无注释

【章末钩子】
给读者留下悬念：更大的金手指、神秘女生、校霸注意、神秘传音、隐藏任务等。
"""

CHECK_SYS = """你是网文编辑。直接输出检查结果。

【字数】实际 X 字
【逻辑】通过/问题
【风格】通过/问题
【建议】50-150 字

不要复述指令，直接给结果。
"""


def write_chapter_simple(plot_point, out_dir="/workspace/novel-agent/output", setting_path=None):
    """简化版: 剧情要点 → 直接写正文 → 检查"""
    os.makedirs(out_dir, exist_ok=True)

    print(f"\n=== 写 1 章（简化流程）===\n")
    print(f"  📊 剩余 API 次数: {MAX_API_CALLS - CALL_COUNT}/{MAX_API_CALLS}\n")

    # 加载设定文档
    setting_text = ""
    if setting_path and os.path.exists(setting_path):
        with open(setting_path, encoding="utf-8") as f:
            setting_text = f.read()
        print(f"  📖 已加载设定文档 ({len(setting_text)} 字): {setting_path}")
    else:
        print(f"  ⚠️ 未提供设定文档")

    # 拼装 user prompt
    user_prompt = ""
    if setting_text:
        user_prompt += f"【设定文档】\n{setting_text}\n\n"
    user_prompt += f"【本章剧情要点】\n{plot_point}\n\n"
    user_prompt += "请根据以上设定和剧情要点，扩写本章正文。"

    # 1. 写正文（用 K3，prompt 是"角色绑定+场景当下"）
    print("[1/2] 写正文 (kimi-k3)...")
    novel = call_moonshot(
        WRITE_SYS,
        user_prompt,
        model="kimi-k3",
    )
    # K3 失败时降级到 moonshot-v1-128k（非 reasoning）
    if "错误" in novel or "空" in novel or len(novel) < 500:
        print(f"  ⚠️ K3 失败 ({novel[:30] if novel else '空'}...)，降级到 v1-128k...")
        novel = call_moonshot(
            WRITE_SYS,
            user_prompt,
            model="moonshot-v1-128k",
        )
    if "错误" in novel or len(novel) < 500:
        print(f"  ❌ 写正文失败: {novel[:200]}")
        print("  🛑 停止，问用户")
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

    # 保存
    out = {
        "plot_point": plot_point,
        "novel": novel,
        "review": review,
        "char_count": len(novel),
        "api_calls_used": CALL_COUNT,
        "ts": "2026-08-07",
    }
    fp = f"{out_dir}/chapter_simple.json"
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n  💾 已存: {fp}")
    print(f"  📊 用了 {CALL_COUNT}/{MAX_API_CALLS} 次 API")
    print(f"\n=== 完成 ===")
    return out


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python3 novel_writer.py write '<plot_point>' [--setting <path>]")
        sys.exit(1)
    if sys.argv[1] != "write":
        print(f"未知命令: {sys.argv[1]}")
        sys.exit(1)
    plot = sys.argv[2]
    setting_path = None
    if "--setting" in sys.argv:
        idx = sys.argv.index("--setting")
        if idx + 1 < len(sys.argv):
            setting_path = sys.argv[idx + 1]
    try:
        write_chapter_simple(plot, setting_path=setting_path)
    except Exception as e:
        print(f"\n🛑 {e}")
        print("   停下，等你确认再继续")

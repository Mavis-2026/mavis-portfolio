#!/usr/bin/env python3
"""
Dify 网文写作助手 · 沙箱调用脚本

用法:
  python3 core/dify_writer.py "第1章 觉醒，主角..." [user_id]
"""
import os
import sys
import json
import urllib.request
import urllib.parse
import re

# 1. 优先从 .env 读（沙箱 /workspace/.env），覆盖 shell env
def load_env():
    env_path = "/root/.openclaw/.env"
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    if k not in os.environ:
                        os.environ[k] = v

load_env()

DIFY_KEY = os.environ["DIFY_API_KEY"]
DIFY_BASE = os.environ.get("DIFY_BASE_URL", "https://api.dify.ai/v1")


def write_chapter(query, user="default", timeout=180):
    """调用 Dify 工作流写 1 章"""
    url = f"{DIFY_BASE}/chat-messages"
    payload = {
        "inputs": {},
        "query": query,
        "user": user,
        "response_mode": "blocking",  # 工作流用 blocking 拿完整结果
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {DIFY_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"error": True, "status": e.code, "body": body}
    except Exception as e:
        return {"error": True, "exception": str(e)}


def main():
    if len(sys.argv) < 2:
        print("用法: python3 dify_writer.py '<query>' [user_id]")
        sys.exit(1)
    query = sys.argv[1]
    user = sys.argv[2] if len(sys.argv) > 2 else "default"

    print(f"[Dify] 调用: {query[:50]}...")
    result = write_chapter(query, user)

    if result.get("error"):
        print(f"[Dify] ❌ 错误: {result}")
        sys.exit(1)

    # 提取 answer
    answer = result.get("answer", "")
    print(f"\n=== 生成结果 ({len(answer)} 字) ===\n")
    print(answer)

    # 字数统计
    char_count = len(answer)
    print(f"\n=== 字数: {char_count} ===")

    # 写到文件
    chapter_match = re.search(r"第\s*(\d+)\s*章", query)
    if chapter_match:
        ch = chapter_match.group(1)
        out = f"/tmp/chapter_{ch}.md"
        with open(out, "w", encoding="utf-8") as f:
            f.write(f"# {query.split(',')[0]}\n\n{answer}\n")
        print(f"=== 写到: {out} ===")


if __name__ == "__main__":
    main()

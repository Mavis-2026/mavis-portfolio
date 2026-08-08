"""
钉钉推送工具（GitHub Actions 友好）
- 类型: weekly(周报) / review(日报)
- 模式: success(成功) / fail(失败)
- 日期用 now_cst() 动态算
- webhook 从环境变量 DINGDING_WEBHOOK 读
- secret 从环境变量 DINGDING_SECRET 读（可选）
"""
import os
import sys
import json
import time
import hmac
import hashlib
import base64
import urllib.request
import urllib.parse
import argparse
from datetime import datetime, timezone, timedelta


def now_cst() -> datetime:
    """Asia/Shanghai 当前时间"""
    cst = timezone(timedelta(hours=8))
    return datetime.now(cst)


def get_sign(secret: str) -> tuple:
    """加签模式计算 sign"""
    timestamp = str(round(time.time() * 1000))
    secret_enc = secret.encode("utf-8")
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    hmac_code = hmac.new(secret_enc, string_to_sign, digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    return timestamp, sign


def _is_github_robot(webhook: str) -> bool:
    """识别 GitHub 机器人（钉钉 GitHub 机器人 token 长度 64）"""
    if "access_token=" in webhook:
        token = webhook.split("access_token=")[1].split("&")[0]
        # GitHub 机器人 token 长度 64，普通机器人 32
        return len(token) > 50
    return False


def send_text(webhook: str, secret: str | None, content: str) -> dict:
    """发送消息到钉钉（自动识别 GitHub 机器人 vs 普通机器人）"""
    if secret:
        timestamp, sign = get_sign(secret)
        url = f"{webhook}&timestamp={timestamp}&sign={sign}"
    else:
        url = webhook

    # GitHub 机器人不支持 text msgtype，用 markdown
    if _is_github_robot(webhook):
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": content.split("\n")[0][:20],
                "text": content,
            },
        }
    else:
        payload = {
            "msgtype": "text",
            "text": {"content": content},
            "at": {"atMobiles": [], "isAtAll": False},
        }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def build_text(report_type: str, mode: str, reason: str = "") -> str:
    """构造消息文本（GitHub 机器人专用，消息带仓库路径）"""
    today = now_cst().strftime("%Y-%m-%d")
    repo = os.environ.get("GITHUB_REPOSITORY", "Mavis-2026/mavis-portfolio")

    if mode == "fail":
        label = "周复盘" if report_type == "weekly" else "日复盘"
        return (
            f"❌ {label}失败 {today}\n"
            f"仓库: {repo}\n"
            f"原因: {reason or '未知'}"
        )

    # success 模式（GitHub 机器人必须带仓库路径才会推送）
    base = f"https://{repo.split('/')[0]}.github.io/{repo.split('/')[1]}/reports"
    if report_type == "weekly":
        main_url = f"{base}/weekly-review-{today}-main.html"
        sub_url = f"{base}/weekly-review-{today}-sub2.html"
        return (
            f"✅ 周复盘 {today}\n\n"
            f"仓库: {repo}\n"
            f"主账户: {main_url}\n"
            f"副账户: {sub_url}"
        )
    else:
        main_url = f"{base}/review-{today}-main.html"
        sub_url = f"{base}/review-{today}-sub2.html"
        return (
            f"✅ 日复盘 {today}\n\n"
            f"仓库: {repo}\n"
            f"主账户: {main_url}\n"
            f"副账户: {sub_url}"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", default="weekly", choices=["weekly", "review"])
    parser.add_argument("--mode", default="success", choices=["success", "fail"])
    parser.add_argument("--reason", default="")
    args = parser.parse_args()

    webhook = os.environ.get("DINGDING_WEBHOOK")
    secret = os.environ.get("DINGDING_SECRET", "")

    if not webhook:
        print("❌ DINGDING_WEBHOOK 环境变量未设置")
        return 1

    # 如果 WORKFLOW_STATUS 是 failure，自动切到 fail 模式
    workflow_status = os.environ.get("WORKFLOW_STATUS", "success")
    if workflow_status != "success" and args.mode == "success":
        args.mode = "fail"
        if not args.reason:
            args.reason = f"workflow status: {workflow_status}"

    text = build_text(args.type, args.mode, args.reason)

    try:
        result = send_text(webhook, secret or None, text)
        if result.get("errcode") == 0:
            print(f"✅ 钉钉发送成功 ({args.type}/{args.mode})")
            return 0
        else:
            print(f"❌ 钉钉发送失败: {result}")
            return 1
    except Exception as e:
        print(f"❌ 钉钉发送异常: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

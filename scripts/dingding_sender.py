#!/usr/bin/env python3
"""
钉钉消息推送模块
- 支持加签验证
- 支持文本/markdown/链接卡片消息
- 统一接口,被其他脚本调用
"""
import json
import time
import hmac
import hashlib
import base64
import urllib.parse
import urllib.request
from pathlib import Path

# 自动检测配置文件路径(支持本地和 GitHub Actions)
def _find_config_file():
    candidates = [
        Path("/workspace/config/dingding.json"),  # Mavis 环境
        Path(__file__).parent.parent / "config" / "dingding.json",  # 仓库根目录
        Path.cwd() / "config" / "dingding.json",  # 当前工作目录
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]  # fallback

CONFIG_FILE = _find_config_file()


def load_config():
    """
    加载配置,优先级:
    1. 环境变量(用于 GitHub Actions / 容器环境)
    2. 本地配置文件(用于开发环境)
    """
    # 优先从环境变量读
    env_webhook = os.environ.get("DINGDING_WEBHOOK_URL")
    env_secret = os.environ.get("DINGDING_SECRET")
    
    if env_webhook and env_secret:
        return {
            "platform": "dingding",
            "webhook_url": env_webhook,
            "secret": env_secret,
            "security_mode": "sign",
            "enabled": True
        }
    
    # fallback 到本地文件
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    
    raise RuntimeError("未找到钉钉配置:既无环境变量,也无本地配置文件")


def calc_sign(secret):
    """计算加签"""
    timestamp = str(round(time.time() * 1000))
    secret_enc = secret.encode('utf-8')
    string_to_sign = f'{timestamp}\n{secret}'
    string_to_sign_enc = string_to_sign.encode('utf-8')
    hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    return timestamp, sign


def send_text(content, at_mobiles=None, at_all=False):
    """发送纯文本消息"""
    cfg = load_config()
    url = cfg["webhook_url"]

    if cfg.get("security_mode") == "sign":
        ts, sign = calc_sign(cfg["secret"])
        url = f"{url}&timestamp={ts}&sign={sign}"

    payload = {
        "msgtype": "text",
        "text": {"content": content}
    }
    if at_mobiles:
        payload["text"]["at"] = {"atMobiles": at_mobiles}
    if at_all:
        payload["text"]["at"] = {"isAtAll": True}

    return _post(url, payload)


def send_markdown(title, content, at_mobiles=None):
    """发送 Markdown 消息(支持表格、彩色文字)"""
    cfg = load_config()
    url = cfg["webhook_url"]

    if cfg.get("security_mode") == "sign":
        ts, sign = calc_sign(cfg["secret"])
        url = f"{url}&timestamp={ts}&sign={sign}"

    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": content
        }
    }
    if at_mobiles:
        payload["markdown"]["at"] = {"atMobiles": at_mobiles}

    return _post(url, payload)


def send_link(title, content, message_url, pic_url=""):
    """发送链接卡片"""
    cfg = load_config()
    url = cfg["webhook_url"]

    if cfg.get("security_mode") == "sign":
        ts, sign = calc_sign(cfg["secret"])
        url = f"{url}&timestamp={ts}&sign={sign}"

    payload = {
        "msgtype": "link",
        "link": {
            "title": title,
            "text": content,
            "messageUrl": message_url,
            "picUrl": pic_url
        }
    }
    return _post(url, payload)


def _post(url, payload):
    """执行 POST 请求"""
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "Mavis-Monitor/1.0"
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            if result.get("errcode") == 0:
                return {"success": True, "result": result}
            else:
                return {"success": False, "error": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


def test_connection():
    """测试连接"""
    return send_text("✅ Mavis 投资助理已上线!这是测试消息,如果你看到了,说明推送功能正常工作~")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        result = test_connection()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("用法:python dingding_sender.py test")

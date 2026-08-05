# Mavis 投资助理 · 系统架构与工作流

## 终极架构(2026-07-31 18:30 定型)

```
[你] 跟 Mavis 说"看下盘" / "复盘" / "看新闻"
        ↓
[Mavis] 收到指令,调 GitHub API 触发 Actions
        ↓
[GitHub Actions] 跑 workflow:
  1. checkout 代码
  2. 装 Python
  3. 读 Secrets(DeepSeek Key + 钉钉)
  4. 跑脚本(daily_review / weekly_review / news)
  5. 调 DeepSeek(用 v4-pro)
  6. 生成 HTML + MD 报告
  7. 推钉钉(报告链接)
  8. commit + push 回 GitHub
        ↓
[你] 收到钉钉消息,看报告
```

## 3 角色分工

**Mavis(我)**:调度员
- ✅ 接收你指令
- ✅ 触发 GitHub Actions(API / 网页)
- ✅ 改代码/文档/推 GitHub
- ❌ 不跑报告(避免沙箱跑飞)
- ❌ 不存数据(交给 GitHub)

**GitHub Actions**:执行者
- ✅ 跑报告(沙箱 0 调用,稳定)
- ✅ 存报告 + 公开访问
- ✅ 调 DeepSeek + 钉钉
- ✅ Secrets 安全
- ❌ 不主动跑(等你触发)

**DeepSeek**:推理 AI
- ✅ 写投资逻辑
- ✅ 决策建议
- ❌ 不主动(被调用才动)

## GitHub 仓库
- 仓库:https://github.com/Mavis-2026/mavis-portfolio
- Pages:https://Mavis-2026.github.io/mavis-portfolio/
- 报告路径:reports/ 目录

## 触发 GitHub Actions(API)
```bash
curl -X POST \
  -H "Authorization: token <GITHUB_PAT>" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/Mavis-2026/mavis-portfolio/actions/workflows/task.yml/dispatches \
  -d '{"ref":"main","inputs":{"task":"review","account":"main","push_dingding":"true"}}'
```

## 任务类型
| task | 说明 |
|------|------|
| `news` | 财经新闻推送 |
| `position` | 盘中监测(3 段式) |
| `review` | 每日复盘(5 维) |
| `weekly` | 周复盘(5 维宏观) |

## 账户参数
| account | 说明 |
|---------|------|
| `main` | 主账户 8337(5 ETF) |
| `sub2` | 副账户 7661(2 ETF) |
| `both` | 双账户 |

## 4 个 GitHub Secrets
- `DEEPSEEK_API_KEY`
- `DINGDING_WEBHOOK`
- `DINGDING_SECRET`
- `DINGDING_WEBHOOK_URL`(备用)

## 防跑飞 3 道保险
1. ✅ 0 个 cron(全部手动触发)
2. ✅ GitHub Secrets 沙箱不知道
3. ✅ 失败只重试 3 次(DeepSeek 调用)

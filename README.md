# Mavis 投资助理 v2.0

> **100% 手动触发的智能投顾助理** · 阶段 1:数据 + 5 件事必出

## 触发词

| 触发 | 行为 |
|------|------|
| `Mavis,复盘` | 日/周复盘 + 推钉钉 |
| `Mavis,看一下盘` | 实时抓数 + 盘中分析 |

## 文件结构

```
core/
  fetch.py          # 数据拉取(新浪/腾讯)
  analyze.py        # 5 件事必出逻辑
  report.py         # 报告生成(MD/HTML)
review/
  daily_review.py   # 复盘主脚本
portfolio/
  holdings.json     # 持仓档
docs/
  加仓纪律-v2.md
  产业逻辑共识-v1.2.md
.github/workflows/
  review.yml        # 唯一 GitHub Actions
```

## 跑法

```bash
# 沙箱跑
python3 review/daily_review.py --account both

# GitHub Actions 跑
# https://github.com/Mavis-2026/mavis-portfolio/actions
# → Review → Run workflow → 选 main/sub2/both
```

## 阶段路线

- ✅ 阶段 1:数据 + 5 件事(当前)
- ⏳ 阶段 2:加 DeepSeek AI 分析
- ⏳ 阶段 3:用户验收
- ⏳ 阶段 4:接钉钉推送

# 网文写作助手 (mavis-novel)

> 本地存数据 + 云端调 API = 网文和投资复盘物理隔离

## 架构

```
[你] 浏览器手动触发 GitHub Actions
    ↓
[GitHub 私有仓] mavis-novel
    ├── novel_writer_gh.py  (主脚本)
    ├── chapters/           (章节正文 + 检查报告)
    ├── outlines/           (大纲、细纲)
    └── .github/workflows/write-chapter.yml
    ↓
[GitHub Actions]
    ├── python novel_writer_gh.py --chapter N --plot "..."
    ├── 调 Moonshot K3 (写正文)
    ├── 调 DeepSeek  (检查)
    ├── 提交回仓
    └── 完成
```

## 部署步骤（一次性）

### 1. 在 GitHub 建私有仓
- 仓库名：`mavis-novel`
- 可见性：**Private**（私有）
- 不要初始化任何文件

### 2. 推送代码到 GitHub

沙箱内执行：
```bash
cd /workspace/novel-agent
git init
git remote add origin https://github.com/Mavis-2026/mavis-novel.git
git add .
git commit -m "init: 网文写作助手"
git branch -M main
git push -u origin main
```

> **沙箱可代执行推送**，但需要新 GITHUB_PAT（之前的 `ghp_6NlB3eAR...` 可能够用，试一下）

### 3. 配 GitHub Secrets

浏览器 → 仓 Settings → Secrets and variables → Actions → New repository secret

| Name | Value |
|---|---|
| `MOONSHOT_API_KEY` | `sk-jdh5UZykfxCloP3zPKfOU5d22VTMEqOTx67jSMpTQw00CN4B` |
| `DEEPSEEK_API_KEY` | `sk-e70d50437b6e40a5a3bd22cd596d0ee8` |

> **沙箱不能改 Secrets**（libsodium 缺失），要你手动配

### 4. 启用 Workflow
- 浏览器 → 仓 Actions → 选 "写网文章节" → Enable workflow
- 然后 Run workflow → 输入 chapter=1, plot="..."

## 日常用法

### 写新章节
1. 浏览器 → 仓 → Actions → 写网文章节
2. 点 Run workflow
3. 输入：
   - `chapter`: 章节号（如 1, 2, 3）
   - `plot`: 剧情要点（如 "主角在图书馆偶遇神秘女生"）
4. 等 2-3 分钟
5. 仓里 `chapters/chapter_N.txt` 自动更新

### 编辑大纲/细纲
- 改 `outlines/第N章.md`
- push → Actions 自动跑（已配 push 触发）

## 文件说明

| 文件 | 作用 |
|---|---|
| `novel_writer_gh.py` | 主脚本（命令行参数版）|
| `novel_writer.py` | 沙箱版（旧，调试用）|
| `dify_writer.py` | Dify API 版（备用）|
| `chapters/chapter_N.txt` | 章节正文（自动生成）|
| `chapters/chapter_N.json` | 章节数据（自动生成）|
| `.github/workflows/write-chapter.yml` | GitHub Actions 配置 |
| `outlines/第N章.md` | 大纲/细纲（你写）|

## 与 mavis-portfolio 隔离

| 仓 | 用途 | 工作流 |
|---|---|---|
| `mavis-portfolio` | 投资复盘 | Plan 2 (agent 拉 + GitHub 写) |
| `mavis-novel` | 网文写作 | GitHub Actions 跑 |

两仓互不依赖，**网文跑飞不影响复盘**。

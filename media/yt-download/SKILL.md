---
name: yt-download
description: >
  使用 yt-dlp 下载 YouTube 视频，同时下载英文字幕（含原始自动字幕），存储元信息。
  视频存放在 ~/youtube_videos/{清理后标题}/ 独立目录，幂等设计（已存在则跳过）。
  支持断点续传（-c）和自动重试（--retry-sleep + bash 重试循环）。
  代理：必须设置 ALL_PROXY=http://127.0.0.1:7890。
  字幕策略：下载 en（翻译字幕）和 en-orig（原始自动字幕），无手写字幕时自动字幕兜底。
triggers:
  - 下载视频
  - 下载油管视频
  - youtube 下载
  - yt-download
author: ray
version: 1.4.1
---

# yt-download — YouTube 视频下载

## 执行模型

```bash
# 完整模式：下载视频 + 原生字幕
bash ~/.hermes/skills/media/yt-download/scripts/download.sh "<YOUTUBE_URL>" [MAX_RETRIES] [SLEEP_RETRY]

# 纯字幕模式：只下载字幕，不下载视频
bash ~/.hermes/skills/media/yt-download/scripts/download.sh --sub-only "<YOUTUBE_URL>" [MAX_RETRIES] [SLEEP_RETRY]
```

参数：
- `MAX_RETRIES`：最大重试次数（默认 5）
- `SLEEP_RETRY`：重试前等待秒数（默认 10，支持指数退避）

## 字幕策略（重要）

**默认只使用 `--write-subs`（原生字幕），不使用 `--write-auto-subs`。**

这意味着：
- 只下载人工/原生字幕（上传者手写的）
- 如果没有原生字幕，则什么也不会下载（不会退回到自动字幕）
- 如果需要自动字幕兜底，使用 `--sub-only` 时传入 `AUTO_SUBS=1` 环境变量

若视频没有原生字幕，`yt-dlp` 会输出：
```
There are no subtitles for the requested languages
```

## 工作流

```
YouTube URL
    │
    ▼
Step 1 ─── 解析 URL，提取 video_id
    │
    ▼
Step 2 ─── 幂等检查
    │  视频模式：video_id 目录已存在视频则跳过
    │  字幕模式：字幕文件已存在则跳过
    │
    ▼
Step 3 ─── 创建临时目录 ~/youtube_videos/{video_id}_tmp/
    │
    ▼
Step 4 ─── yt-dlp 下载
    │
    │  ┌─────────────── 字幕下载参数 ─────────────────┐
    │  │  --write-subs                    ← 下载原生字幕   │
    │  │  --sub-langs "en"              ← 只下载英文字幕  │
    │  │  --sub-format vtt                ← 指定 vtt 格式  │
    │  │  --write-auto-subs (仅AUTO_SUBS=1) ← 自动字幕兜底 │
    │  └──────────────────────────────────────────────┘
    │
    │  ┌────────────── retry loop ──────────────┐
    │  │ 失败 → 等待 → 指数退避 → 重试 (MAX_RETRIES 次)  │
    │  └─────────────────────────────────────────┘
    │
    ▼
Step 5 ─── 从 info.json 提取标题
    ▼
Step 6 ─── 重命名目录为 {sanitized-title}/
    ▼
Step 7 ─── 输出文件列表
```

## 输出结构

```
~/youtube_videos/{sanitized-title}/
├── {sanitized-title}.mp4          ← 视频（视频模式）
├── {sanitized-title}.en.vtt       ← 英文字幕（原生 vtt）
├── {sanitized-title}.info.json    ← 元信息
└── download.log                    ← 下载日志
```

> **字幕说明**：
> - 使用 `--sub-format vtt` 统一输出 vtt 格式
> - `--sub-langs "en"` 只下载英文原生字幕（上传者手写，非自动生成）
> - **没有 `--write-auto-subs`**，不会自动退回到自动字幕
> - 如需自动字幕兜底：运行 `AUTO_SUBS=1 bash download.sh ...`
> - 中文字幕由下游 `video-obsidian-save` 技能通过 LLM 翻译生成

> **命名规则**：标题 sanitize 顺序：
> 1. em dash `—` / en dash `–` → `-`
> 2. 逗号 `,` 和冒号 `:` → **直接删除**（不是变下划线！）
> 3. 其他特殊字符 → `_`
> 4. 空格 → `-`（连字符）
> 5. 连续横线 collapse → 单一横线
> 6. 去两头横线，截断 100 字符
>
> 示例：`Harness Engineering: How to Build, When Humans Steer — Ryan` → `Harness-Engineering-How-to-Build-When-Humans-Steer-Ryan`

## 核心参数说明

| 参数 | 作用 |
|------|------|
| `--skip-download` | 纯字幕模式：不下载视频，只下载字幕 |
| `--write-subs` | 下载原生字幕（上传者手写，非自动生成） |
| `--write-auto-subs` | 下载自动字幕（YouTube ASR）；**默认不启用** |
| `--sub-langs "en"` | 下载英文原生字幕（上传者手写） |
| `--sub-format vtt` | 统一输出 vtt 格式 |
| `-c` | 断点续传，kill 后重启自动继续 |
| `--retry-sleep 3` | yt-dlp 内部自动重试间隔（秒） |
| `--js-runtimes node` | 解密 YouTube 签名（需要 Node.js） |
| `--cookies-from-browser chrome` | 读取已登录态 cookie |
| `--no-overwrites` | 幂等：已有完整文件不重复下载 |

## 已知陷阱

1. **必须用 `--js-runtimes node`** — 不然签名解密失败（No JavaScript runtime found）。Node.js 在 `/usr/local/bin/node`
2. **必须设置 `ALL_PROXY=http://127.0.0.1:7890`** — 代理直连 YouTube。yt-dlp 只认 `ALL_PROXY`
3. **字幕下载默认只使用原生字幕** — 没有 `--write-auto-subs`，英文技术演讲基本没有手写字幕，如果没有原生字幕则不会下载任何字幕
4. **纯字幕模式** — 用 `--skip-download` 即可只下载字幕，不下载视频
5. **字幕下到临时目录** — 下载过程中字幕在 `{video_id}_tmp/` 目录，合并后才到主目录
6. **视频已存在时字幕不丢失** — 脚本已修复：主目录存在时会把新字幕合并进去再删临时目录
7. **字幕格式统一为 vtt** — 下游 video-obsidian-save 技能依赖 VTT 格式进行解析
8. **代理速度慢** — 229MB 视频约需 10-15 分钟，属于正常
9. **Whisper VTT 格式不兼容下游 parser** — Whisper 输出的 VTT 时间戳格式为 `0.000 --> 4.960`（仅秒.毫秒），而下游 `vtt_parser.py` 期望 `00:00:00.000 --> 00:00:04.960` 格式（含时分秒）。需用脚本转换：

   ```bash
   python3 -c "
   import re
   with open('input.vtt') as f:
       content = f.read()
   def fix_ts(m):
       s, e = float(m.group(1)), float(m.group(2))
       def hms(sec):
           h=int(sec)//3600; m=(int(sec)%3600)//60; s=sec%60
           return f'{h:02d}:{m:02d}:{s:06.3f}'
       return f'{hms(s)} --> {hms(e)}'
   fixed = re.sub(r'(\d+\.?\d*)\s*-->\s*(\d+\.?\d*)', fix_ts, content)
   with open('output.vtt', 'w') as f:
       f.write('WEBVTT\\n\\n' + fixed)
   "
   ```
   
10. **`~/.hermes/.env` 变量不自动导出** — 脚本使用 `MINIMAX_API_KEY`，但该变量定义在 `.env` 文件中未自动 export。运行下游 pipeline 前需执行：

    ```bash
    set -a; source ~/.hermes/.env; set +a
    ```

## 幂等性保证

- 目录存在 + 有视频文件 → 跳过
- `--no-overwrites` → 不重复下载已有文件
- `-c` → kill 后重启自动续传 `.part` 文件
- bash retry loop → 网络抖动自动恢复

## 依赖

| 工具 | 路径/版本 |
|------|-----------|
| yt-dlp | `/opt/anaconda3/bin/yt-dlp` 2026.03.17 |
| Node.js | `/usr/local/bin/node` |
| Clash 代理 | `127.0.0.1:7890` |
| Chrome cookie | 已登录 YouTube 的 Chrome 实例 |

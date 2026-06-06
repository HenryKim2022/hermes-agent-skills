---
name: youtube-to-obsidian
description: YouTube视频 → Obsidian双语笔记端到端流程。串联 yt-download、vtt_parser、paragraph_weaver、translator（video-translate-to-table 三步）以及 video-obsidian-save，自动化完成下载、翻译（含frontmatter）、保存。
category: workflow
triggers:
  - 下载YouTube视频并保存到Obsidian
  - 把油管视频做成双语课程笔记
  - YouTube视频翻译保存
---

# YouTube to Obsidian

将 YouTube 视频自动转化为 Obsidian 双语笔记的完整编排流程。

## 流程概览（4步）

```
yt-download
    ↓
EN VTT 存在？
    ├─ 是 → vtt_parser.py（解析碎片）
    │           ↓
    │       paragraph_weaver.py（LLM合并→段落）
    │           ↓
    │       translator.py（LLM翻译，含frontmatter）
    │           ↓
    └─ 否 → speech-to-text（Whisper转写）→ 同上
                    ↓
video-obsidian-save/formatter.py（纯存储）
```

---

## Step 1：下载视频 + 字幕

```bash
yt-dlp --js-runtimes node --remote-components ejs:github --cookies-from-browser chrome \
  -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" \
  --write-auto-subs --sub-langs "en,zh-CN" \
  -o "~/youtube_videos/%(title)s/%(title)s.%(ext)s" \
  "https://www.youtube.com/watch?v=VIDEO_ID"
```

**输出目录结构：**
```
youtube_videos/{清理后标题}/
├── {title}.mp4
├── {title}.en.vtt          ← 英文自动字幕（关键输入）
├── {title}.zh-CN.srt        ← 官方中文（可选）
└── {title}.info.json        ← 元数据（title/date/duration/uploader）
```

**幂等：** 文件存在则跳过。

---

## Step 2：处理字幕

### 2a：检查 EN VTT 是否存在

```bash
ls ~/youtube_videos/{标题}/*.en.vtt
```

| 情况 | 操作 |
|------|------|
| EN VTT 存在 | 直接进入 Step 2b |
| EN VTT 不存在 | 先用 Whisper 转写，再进入 Step 2b |

### 2b：Whisper 转写（如需要）

```bash
VIDEO_PATH="~/youtube_videos/{标题}/{标题}.mp4"
python3 -c "
import whisper
model = whisper.load_model('base')
result = model.transcribe('$VIDEO_PATH', language='en')
with open('${VIDEO_PATH%.mp4}.en.vtt', 'w') as f:
    for seg in result['segments']:
        start = seg['start']
        end = seg['end']
        text = seg['text'].strip()
        f.write(f'{start:.3f} --> {end:.3f}\\n{text}\\n\\n')
"
```

### 2c：VTT 格式修正（如 Whisper 转写）

Whisper 输出的 VTT 时间戳格式为 `0.000 --> 4.960`（仅秒.毫秒），但下游 `vtt_parser.py` 期望 `00:00:00.000 --> 00:00:04.960`（含时分秒）。必须转换：

```bash
python3 -c "
import re
with open('INPUT.en.vtt') as f:
    content = f.read()
def fix_ts(m):
    s, e = float(m.group(1)), float(m.group(2))
    def hms(sec):
        h=int(sec)//3600; m=(int(sec)%3600)//60; s=sec%60
        return f'{h:02d}:{m:02d}:{s:06.3f}'
    return f'{hms(s)} --> {hms(e)}'
fixed = re.sub(r'(\d+\.?\d*)\s*-->\s*(\d+\.?\d*)', fix_ts, content)
with open('OUTPUT.en.vtt', 'w') as f:
    f.write('WEBVTT\\n\\n' + fixed)
"
```

> **注意**：此步骤只对 Whisper 转写的 VTT 需要。yt-dlp 下载的原始 VTT 时间戳格式已正确，无需转换。

---

## Step 3：翻译 pipeline（video-translate-to-table）

调用 `video-translate-to-table` 三步：

```bash
SKILL_DIR="$HOME/.hermes/skills-mine/productivity/video-translate-to-table/scripts"
VIDEO_DIR="~/youtube_videos/{标题}"
VTT_FILE=$(ls "$VIDEO_DIR"/*.en.vtt | head -1)
URL="https://www.youtube.com/watch?v=VIDEO_ID"

cd "$SKILL_DIR"

# Step 3.1：VTT → 碎片 JSON
python3 vtt_parser.py "$VTT_FILE" --output-json "$VIDEO_DIR/.fragments.json"

# Step 3.2：碎片 → 段落（LLM合并）
python3 paragraph_weaver.py "$VIDEO_DIR/.fragments.json" --output "$VIDEO_DIR/.paragraphs.json"

# Step 3.3：段落 → 双语 markdown（LLM翻译 + frontmatter）
python3 translator.py "$VIDEO_DIR/.paragraphs.json" \
  --url "$URL" \
  --info "$VIDEO_DIR/$(ls $VIDEO_DIR/*.info.json | xargs basename)" \
  --output "$VIDEO_DIR/{标题}-translate.md"
```

**translator.py 输出格式（Obsidian ready）：**

```markdown
---
title: "Your Body Language May Shape Who You Are | Amy Cuddy | TED"
source: "https://www.youtube.com/watch?v=Ks-_Mh1QhMc"
date: 2012-10-01
duration: "21:03"
uploader: "TED"
video_id: "Ks-_Mh1QhMc"
tags:
  - ted
  - translate
  - youtube
---

# Your Body Language May Shape Who You Are | Amy Cuddy | TED

| 开始时间 | English | 中文 |
| -------- | ------- | ---- |
| [00:00:15](...) | So I want to start... | 我想先给你们一个... |
```

**frontmatter 由 translator.py 从 info.json 自动生成**，无需手动维护。

---

## Step 4：存入 Obsidian

调用 `video-obsidian-save/formatter.py`：

```bash
python3 ~/.hermes/skills-mine/productivity/video-obsidian-save/scripts/formatter.py \
  --video-dir "~/youtube_videos/{标题}" \
  --course-name "{课程目录名}"
```

**formatter.py 工作流程（纯存储）：**
1. 找到 `{video_dir}/*-translate.md`（已是完整 Obsidian 格式）
2. 复制 → `Clippings-Videos/{course-name}/{course-name}.md`
3. 更新 `Clippings-Videos/Index.md`（去重追加）

---

## 关键设计原则

**LLM 能做的事在翻译阶段做，不要留到存储阶段。**

- `translator.py` 有 LLM → 负责生成 frontmatter、优化标题
- `formatter.py` 无 LLM → 纯 cp + 写 Index

---

## 验证

```bash
# 检查 Obsidian 文件
ls ~/Library/Mobile\\ Documents/iCloud~md~obsidian/Documents/Ray/Clippings-Videos/{课程名}/

# 检查 frontmatter
head -15 ~/Library/Mobile\\ Documents/iCloud~md~obsidian/Documents/Ray/Clippings-Videos/{课程名}/{课程名}.md

# 检查 Index
tail -5 ~/Library/Mobile\\ Documents/iCloud~md~obsidian/Documents/Ray/Clippings-Videos/Index.md
```

## 已知陷阱

1. **`~/.hermes/.env` 变量不自动 export** — Step 3（main.py）和 Step 4（formatter.py）都是 subprocess，不会继承未 export 的环境变量。必须手动加载：`set -a; source ~/.hermes/.env; set +a` 后再运行命令。
2. **Whisper VTT 时间戳格式** — 见 Step 2c，必须做格式修正才能被 vtt_parser.py 识别。
3. **yt-download 脚本语法错误** — 旧版 download.sh 有 orphaned `fi` 导致文件重命名失败。如出现 %s 命名的文件无 SANITIZED 前缀，检查脚本是否已更新。

#!/bin/bash
set -euo pipefail

# ─────────────────────────────────────────
# 配置
# ─────────────────────────────────────────
YOUTUBE_URL="${1:-}"
MODE="full"  # full=视频+字幕, sub-only=纯字幕
MAX_RETRIES="${2:-5}"
SLEEP_RETRY="${3:-10}"

# 检测字幕模式
if [[ "$YOUTUBE_URL" == "--sub-only" ]] || [[ "$YOUTUBE_URL" == "-s" ]]; then
    YOUTUBE_URL="${2:-}"
    MODE="sub-only"
    MAX_RETRIES="${3:-5}"
    SLEEP_RETRY="${4:-10}"
fi

# Python 辅助函数（处理特殊字符）
# 策略：搜索所有 .info.json，内容中含 video_id 则匹配
python_detect_dir() {
    VIDEO_ID_ARG="$1" python3 - <<PYEOF
import glob, os, json
base_dir = os.path.expanduser('~/youtube_videos')
video_id = os.environ.get('VIDEO_ID_ARG', '')
for info_path in glob.glob(os.path.join(base_dir, '**', '*.info.json'), recursive=True):
    try:
        with open(info_path, encoding='utf-8') as f:
            d = json.load(f)
        if d.get('id') == video_id:
            print(os.path.dirname(info_path), end='')
            break
    except (json.JSONDecodeError, OSError):
        continue
PYEOF
}

if [[ -z "$YOUTUBE_URL" ]]; then
    echo "Usage: $0 <YOUTUBE_URL> [MAX_RETRIES] [SLEEP_RETRY]" >&2
    echo "       $0 --sub-only <YOUTUBE_URL> [MAX_RETRIES] [SLEEP_RETRY]" >&2
    echo "Example: $0 https://www.youtube.com/watch?v=dQw4w9WgXcQ 5 10" >&2
    echo "Example: $0 --sub-only https://www.youtube.com/watch?v=dQw4w9WgXcQ" >&2
    exit 1
fi

BASE_DIR="$HOME/youtube_videos"

# 从URL提取 video_id
VIDEO_ID=$(echo "$YOUTUBE_URL" | grep -oE '(v=|youtu\.be/)([a-zA-Z0-9_-]{11})' | tail -1 | sed 's/.*\///' | sed 's/v=//')
if [[ -z "$VIDEO_ID" ]]; then
    echo "Error: 无法从 URL 提取 video_id: $YOUTUBE_URL" >&2
    exit 1
fi
echo "[INFO] 视频ID: $VIDEO_ID"
echo "[INFO] 模式: $MODE"

# ─────────────────────────────────────────
# Step 1: 幂等检查
# ─────────────────────────────────────────
if [[ "$MODE" == "sub-only" ]]; then
    # 纯字幕模式：检查字幕文件是否存在
    EXISTING_DIR=$(python_detect_dir "$VIDEO_ID")
    if [[ -n "$EXISTING_DIR" ]] && ls "$EXISTING_DIR"/*.en.vtt 2>/dev/null | grep -q .; then
        echo "[SKIP] 字幕已存在: $EXISTING_DIR"
        echo "[DONE] 输出目录: $EXISTING_DIR"
        exit 0
    fi
else
    # 完整模式：检查视频是否存在
    EXISTING_DIR=$(python_detect_dir "$VIDEO_ID")
    if [[ -n "$EXISTING_DIR" ]] && ls "$EXISTING_DIR"/*.mp4 "$EXISTING_DIR"/*.webm "$EXISTING_DIR"/*.mkv 2>/dev/null | grep -q .; then
        echo "[SKIP] 视频已存在: $EXISTING_DIR"
        echo "[DONE] 输出目录: $EXISTING_DIR"
        exit 0
    fi
fi

# ─────────────────────────────────────────
# Step 2: 下载到临时目录
# ─────────────────────────────────────────
TMP_DIR="$BASE_DIR/${VIDEO_ID}_tmp"
mkdir -p "$TMP_DIR"

export ALL_PROXY=http://127.0.0.1:7890

# 构建 yt-dlp 参数
YTDLP_ARGS=(
    -P "$TMP_DIR"
    --js-runtimes node
    --cookies-from-browser chrome
    --write-subs
    --sub-langs "en"
    --sub-format vtt
    --write-info-json
    --no-overwrites
    -c
    --retry-sleep 3
)

# 仅字幕模式
if [[ "$MODE" == "sub-only" ]]; then
    YTDLP_ARGS+=(--skip-download)
    echo "[INFO] 纯字幕模式：不下载视频"
else
    YTDLP_ARGS+=(-f "bestvideo+bestaudio/best")
    echo "[INFO] 完整模式：下载视频+字幕"
fi

# 自动字幕兜底（需要显式设置 AUTO_SUBS=1）
if [[ "${AUTO_SUBS:-0}" == "1" ]]; then
    echo "[INFO] 自动字幕兜底：已启用"
    YTDLP_ARGS+=(--write-auto-subs)
fi

echo "[INFO] 开始下载..."

ATTEMPT=0
until yt-dlp "${YTDLP_ARGS[@]}" "$YOUTUBE_URL" 2>&1 | tee -a "$TMP_DIR/download.log"; do
    EXIT_CODE=${PIPESTATUS[0]}
    ATTEMPT=$((ATTEMPT + 1))
    if [[ $ATTEMPT -ge $MAX_RETRIES ]]; then
        echo "[ERROR] 已达最大重试次数 ($MAX_RETRIES)，退出" | tee -a "$TMP_DIR/download.log" >&2
        exit $EXIT_CODE
    fi
    echo "[WARN] 下载失败（退出码: $EXIT_CODE），${SLEEP_RETRY}s 后重试 ($ATTEMPT/$MAX_RETRIES)" | tee -a "$TMP_DIR/download.log" >&2
    echo "       断点文件已保存，下次运行自动续传" | tee -a "$TMP_DIR/download.log" >&2
    sleep "$SLEEP_RETRY"
    SLEEP_RETRY=$((SLEEP_RETRY * 2))
done

# ─────────────────────────────────────────
# Step 3: 提取标题并 sanitize
# ─────────────────────────────────────────
# 查找 info.json（yt-dlp 用视频标题命名，不一定含 video_id）
INFO_JSON=$(ls "$TMP_DIR"/*.info.json 2>/dev/null | head -1)
if [[ -n "$INFO_JSON" ]] && [[ -f "$INFO_JSON" ]]; then
    TITLE=$(python3 -c "import json,sys; d=json.load(open('$INFO_JSON', encoding='utf-8')); print(d.get('title',''))" 2>/dev/null || echo "")
fi

if [[ -n "$TITLE" ]]; then
    SANITIZED=$(python3 -c "
import re, sys
t = '''$TITLE'''
t = t.replace('\u2014', '-').replace('\u2013', '-')
t = t.replace(',', '').replace(':', '')
t = re.sub(r'[<>:\"/\\\\|?*\x00-\x1f]', '_', t)
t = re.sub(r'\s+', '-', t.strip())
t = re.sub(r'-+', '-', t)
t = t.strip('-')[:100]
print(t)
" 2>/dev/null || echo "$VIDEO_ID")
else
    SANITIZED="$VIDEO_ID"
fi

FINAL_DIR="$BASE_DIR/$SANITIZED"

echo "[INFO] 标题: $TITLE"
echo "[INFO] 规范化名: $SANITIZED"

# ─────────────────────────────────────────
# Step 4: 移动/重命名目录
# ─────────────────────────────────────────
if [[ "$TMP_DIR" != "$FINAL_DIR" ]]; then
    if [[ -d "$FINAL_DIR" ]]; then
        # 主目录已存在 → 把新下载的字幕/info.json 合并进去
        cp -n "$TMP_DIR"/*.vtt "$FINAL_DIR/" 2>/dev/null || true
        cp -n "$TMP_DIR"/*.info.json "$FINAL_DIR/" 2>/dev/null || true
        rm -rf "$TMP_DIR"
        echo "[WARN] 同名视频已存在，字幕已合并: $FINAL_DIR"
    else
        mv "$TMP_DIR" "$FINAL_DIR"
        echo "[INFO] 目录重命名: $TMP_DIR → $FINAL_DIR"
    fi
fi

# ─────────────────────────────────────────
# Step 5: 将目录内的文件也重命名为 SANITIZED
# ─────────────────────────────────────────
    # 重命名文件（yt-dlp 用视频标题命名，脚本重命名为 sanitized+video_id）
    python3 - <<PYEOF
import glob, os, re, shutil

final_dir = os.environ.get('FINAL_DIR', '')
sanitized = os.environ.get('SANITIZED', '')
video_id = os.environ.get('VIDEO_ID', '')
mode = os.environ.get('MODE', '')

if not os.path.isdir(final_dir) or not sanitized or not video_id:
    exit(0)

# 字幕文件：找 .en.vtt 且不含 sanitized 前缀的
for f in glob.glob(os.path.join(final_dir, '*.en.vtt')):
    basename = os.path.basename(f)
    target = f'{sanitized}-{video_id}.en.vtt'
    if not basename.startswith(sanitized + '-' + video_id + '.'):
        new_path = os.path.join(final_dir, target)
        print(f'[INFO] 字幕重命名: {basename} → {target}')
        shutil.move(f, new_path)

# 视频文件（完整模式）
if mode == 'full':
    for ext in ('mp4', 'webm', 'mkv'):
        for f in glob.glob(os.path.join(final_dir, f'*.{ext}')):
            basename = os.path.basename(f)
            target = f'{sanitized}-{video_id}.{ext}'
            if not basename.startswith(sanitized + '-' + video_id + '.'):
                print(f'[INFO] 视频重命名: {basename} → {target}')
                shutil.move(f, os.path.join(final_dir, target))
                break

# info.json
for f in glob.glob(os.path.join(final_dir, '*.info.json')):
    basename = os.path.basename(f)
    target = f'{sanitized}-{video_id}.info.json'
    if not basename.startswith(sanitized + '-' + video_id + '.'):
        print(f'[INFO] info.json 重命名: {basename} → {target}')
        shutil.move(f, os.path.join(final_dir, target))
PYEOF

echo ""
echo "[DONE] 下载完成"
echo "[DONE] 输出目录: $FINAL_DIR"
echo "[FILES]"
ls -lh "$FINAL_DIR/" 2>/dev/null

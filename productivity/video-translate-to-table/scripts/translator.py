#!/usr/bin/env python3
"""
translator.py — 翻译段落为 Obsidian 格式 markdown（含 frontmatter）

用法:
    python3 translator.py paragraphs.json --url URL --title TITLE --info info.json -o out.md
"""

import argparse
import json
import os
import re
from datetime import date
from pathlib import Path

API_KEY = os.environ["MINIMAX_API_KEY"]
ENDPOINT = os.environ.get("MINIMAX_BASE_URL", "https://zh.agione.co/hyperone/xapi/api")
MODEL = os.environ.get("TRANSLATOR_MODEL", "deepseek/DeepSeek-V4-Flash/1c61f")


def load_minimax_client():
    import openai
    return openai.OpenAI(api_key=API_KEY, base_url=ENDPOINT)


TRANSLATE_SYSTEM = """You are a professional English-to-Chinese subtitle translator for technical talks and educational videos.

Rules:
1. Translate to Simplified Chinese (简体中文)
2. ALWAYS translate these words (do NOT leave them in English):
   - powerful / powerless → 有权势的 / 没有权势的
   - power / powerful / powerless (as adjectives) → 权力/有权势的/没有权势的
   - assertive, dominance, dominant → 自信的、主导的、支配的
   - hormones (testosterone, cortisol) → 荷尔蒙（睾酮、皮质醇）
   - alpha (in "alpha male") → alpha（阿尔法，灵长类社群首领）
3. Keep person names in English: Nalini Ambady, Dana Carney, Susan Fiske, Amy Cuddy
4. Keep institution names in English: Tufts University, Princeton, Berkeley
5. Preserve [music], [applause], [laughter] tags as-is
6. Translate idiomatically, not word-by-word
7. Only output the translation, no explanations

Output format: Return one translation per line, in the same order.
Format: [N] Chinese translation

IMPORTANT: Start your output with [0] (the first character must be '[')."""


def extract_translations(raw: str, expected: int) -> dict[int, str]:
    """从 LLM 原始输出提取 [N] 翻译文本"""
    translations = {}
    for line in raw.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        m = re.match(r'\[(\d+)\]\s*(.+)', line)
        if m:
            translations[int(m.group(1))] = m.group(2).strip()
    return translations


def translate_batch(client, paragraphs: list[dict], start_idx: int,
                    prev_context: str) -> tuple[dict[int, str], str]:
    """翻一批段落，返回 {局部索引: 中文} 和最后一条中文（作为下一批上下文）"""
    batch_size = 10
    batch = paragraphs[start_idx:start_idx + batch_size]

    user_lines = []
    for i, p in enumerate(batch):
        user_lines.append(f"[{i}] {p['en']}")

    user_prompt = "\n".join(user_lines)
    if prev_context:
        user_prompt = f"[上下文（参考）]\n上一条：{prev_context}\n\n[当前批次]\n{user_prompt}"

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": TRANSLATE_SYSTEM},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.3,
        max_tokens=3000
    )

    raw = response.choices[0].message.content
    translations = extract_translations(raw, len(batch))
    last_zh = translations.get(len(batch) - 1, "")

    return translations, last_zh


def translate_all(paragraphs: list[dict], video_url: str, video_title: str,
                   output_path: str = None, info: dict = None) -> str:
    """完整翻译流程 + 生成含 frontmatter 的 markdown"""
    client = load_minimax_client()
    translations = {}
    prev_context = ""

    total = len(paragraphs)
    batch_size = 10

    for i in range(0, total, batch_size):
        batch_num = i // batch_size + 1
        batch_count = min(batch_size, total - i)
        print(f"  批次 {batch_num}/{(total + batch_size - 1) // batch_size}：{batch_count} 条...", end='', flush=True)

        batch_translations, prev_context = translate_batch(
            client, paragraphs, i, prev_context
        )

        for idx, zh in batch_translations.items():
            translations[i + idx] = zh

        print(f" {len(batch_translations)} 条")

    print(f"\n✅ 翻译完成：{len(translations)}/{total} 条")

    # 生成含 frontmatter 的 markdown
    markdown = generate_markdown(paragraphs, translations, video_url, video_title, info)

    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(markdown)
        print(f"已保存 → {output_path}")

    return markdown


def _timestamp_to_seconds(ts: str) -> int:
    """'00:01:23' → 83"""
    h, m, s = ts.split(':')
    return int(h) * 3600 + int(m) * 60 + int(s)


def build_frontmatter(info: dict, video_title: str) -> str:
    """从 info.json 构建 YAML frontmatter"""
    title = info.get("title", video_title)
    source = info.get("webpage_url", "")
    video_id = info.get("id", "")
    uploader = info.get("uploader", info.get("channel", ""))
    duration_sec = info.get("duration", 0)
    upload_date_raw = info.get("upload_date", "")

    # 日期
    if upload_date_raw and len(upload_date_raw) == 8:
        upload_date = f"{upload_date_raw[:4]}-{upload_date_raw[4:6]}-{upload_date_raw[6:8]}"
    else:
        upload_date = date.today().isoformat()

    # 时长
    if duration_sec:
        h = duration_sec // 3600
        m = (duration_sec % 3600) // 60
        s = duration_sec % 60
        duration_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
    else:
        duration_str = ""

    # 自动 tags（去重）
    tags = set(["youtube", "translate"])
    if uploader:
        tags.add(uploader.lower().replace(" ", "-"))
    if "ted" in title.lower():
        tags.add("ted")
    if "talk" in title.lower() or "speech" in title.lower():
        tags.add("talk")

    tag_str = "\n  - ".join(sorted(tags))

    return f"""---
title: "{title}"
source: "{source}"
date: {upload_date}
duration: "{duration_str}"
uploader: "{uploader}"
video_id: "{video_id}"
tags:
  - {tag_str}
---

"""


def generate_markdown(paragraphs: list[dict], translations: dict[int, str],
                     video_url: str, video_title: str, info: dict = None) -> str:
    """生成含 frontmatter 的 translate.md 表格"""
    frontmatter = build_frontmatter(info, video_title) if info else ""

    lines = []
    lines.append(f"# {video_title}\n")
    lines.append(f"> Source: {video_url}\n")
    lines.append("")
    lines.append("| 开始时间 | English | 中文 |")
    lines.append("| -------- | ------- | ---- |")

    for i, p in enumerate(paragraphs):
        ts = p['start'].split('.')[0]
        en = p['en'].replace('|', '\\|')
        zh = translations.get(i, "").replace('|', '\\|')
        ts_sec = _timestamp_to_seconds(ts)
        link = f"[{ts}]({video_url}&t={ts_sec})"
        lines.append(f"| {link} | {en} | {zh} |")

    return frontmatter + "\n".join(lines)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='翻译段落为 translate.md')
    parser.add_argument('paragraphs_json', help='paragraph_weaver.py 输出的 JSON 文件')
    parser.add_argument('--url', required=True, help='YouTube URL')
    parser.add_argument('--title', required=True, help='视频标题')
    parser.add_argument('--info', dest='info_json',
                        help='yt-dlp info.json 路径（可选，用于生成 frontmatter）')
    parser.add_argument('--output', '-o', default=None,
                        help='输出 .md 文件路径（默认：自动从 paragraphs_json 路径推断）')
    args = parser.parse_args()

    with open(args.paragraphs_json, encoding='utf-8') as f:
        paragraphs = json.load(f)

    info = None
    if args.info_json and Path(args.info_json).exists():
        with open(args.info_json, encoding='utf-8') as f:
            info = json.load(f)

    # 自动推断 output_path（从 paragraphs_json 路径生成对应 translate.md 路径）
    if args.output is None:
        args.output = str(Path(args.paragraphs_json).with_suffix('')).replace('.paragraphs', '-translate').replace('.en', '') + '.md'

    print(f"加载 {len(paragraphs)} 个段落，开始翻译...")
    print(f"输出 → {args.output}")
    md = translate_all(paragraphs, args.url, args.title, args.output, info=info)

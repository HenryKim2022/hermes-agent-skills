#!/usr/bin/env python3
"""
paragraph_weaver.py — 将 VTT 碎片合并为段落，保留时间戳

用法：
    python3 paragraph_weaver.py <fragments.json> [--output <paragraphs.json>]

输入：vtt_parser.py 输出的 JSON
输出：JSON array，每项 {"start": "HH:MM:SS", "duration": float, "en": "..."}
"""

import re
import sys
import json
import argparse
import os
from pathlib import Path

# Minimax API 配置（从环境变量读取，禁止硬编码）
API_KEY = os.environ["MINIMAX_API_KEY"]
ENDPOINT = os.environ.get("MINIMAX_BASE_URL", "https://zh.agione.co/hyperone/xapi/api")
MODEL = os.environ.get("WEAVER_MODEL", "deepseek/DeepSeek-V4-Flash/1c61f")


def load_minimax_client():
    import openai
    return openai.OpenAI(api_key=API_KEY, base_url=ENDPOINT)


def seconds_to_display(seconds: float) -> str:
    h = int(seconds) // 3600
    m = (int(seconds) % 3600) // 60
    s = int(seconds) % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def pre_merge_by_time(entries: list[dict], gap: float = 15.0) -> list[dict]:
    """
    两阶段预合并策略，适合 ASR 自动字幕：

    阶段1 - 去重：同视频10秒内重复的文本碎片只保留一条（保留最新）
                注意：只做去重，不做时间合并！LLM 自己会根据语义断句。
                如果视频有长停顿（> batch_size * avg_gap 秒），LLM 自然会在正确位置分段。

    阶段2：返回去重后的干净条目

    这样：
    - 不会错误合并不同主题的内容
    - 保留完整的语义边界让 LLM 自行判断
    """
    if not entries:
        return []

    # ---------- 阶段1：去重（10秒窗口内同文本只留一条） ----------
    seen: dict[str, tuple[str, float]] = {}
    unique_entries: list[dict] = []

    for entry in entries:
        text = entry['text'].strip()
        if len(text) < 5:          # 过滤 ASR 噪声碎片
            continue
        key = text.lower().replace(' ', '')
        prev = seen.get(key)
        if prev is not None:
            # 同文本在10秒内：只保留最新那条
            if entry['start_sec'] - prev[1] <= 10:
                seen[key] = (text, entry['start_sec'])
            else:
                # 超过10秒，算新内容
                seen[key] = (text, entry['start_sec'])
                unique_entries.append(entry)
        else:
            seen[key] = (text, entry['start_sec'])
            unique_entries.append(entry)

    return unique_entries


SYSTEM_PROMPT = """You are given sequential subtitle fragments from a YouTube video (word-level captions pre-grouped by time).
These are IN ORDER and may be mid-sentence. Time gaps between fragments are shown in seconds.

Your task: Reconstruct complete, natural English sentences/paragraphs.
- Merge fragments that belong together (same topic/sentence)
- Fix truncated words (e.g., "execu" → "execute", "aicles" → "agents", "al" → "all")
- Remove repetitive subword artifacts
- Preserve [music], [applause] tags where they appear
- Each output entry should be a coherent paragraph (1-3 sentences typically)
- Keep entries that are already complete sentences as-is

Output: JSON array only. Each entry:
{"start": "HH:MM:SS", "duration": float_seconds, "en": "reconstructed paragraph"}

Important:
- start: use the FIRST fragment's timestamp (HH:MM:SS format from input)
- duration: time span of this paragraph in seconds (just for reference)
- en: the reconstructed English text (1-3 sentences)
- Output MUST start with '[' and end with ']'
- No explanations, no numbers outside JSON, no thinking blocks
"""


def weave_batch(client, batch: list[dict]) -> list[dict]:
    """送 LLM 合并一批碎片，返回段落列表"""
    # 构建输入
    lines = []
    for i, e in enumerate(batch):
        lines.append(f"[{i}] @ {e['start']} (+{e.get('duration', 0):.1f}s): {e['text']}")

    user_content = "\n".join(lines)

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ],
        temperature=0.3,
        max_tokens=4000
    )

    raw = response.choices[0].message.content.strip()

    # 去掉思考块
    raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL)

    # 提取 JSON array
    json_match = re.search(r'\[[\s\S]*\]', raw)
    if not json_match:
        print(f"  ⚠️ JSON 解析失败，原始输出：{raw[:200]}")
        return []

    try:
        paragraphs = json.loads(json_match.group())
        return paragraphs
    except json.JSONDecodeError as e:
        print(f"  ⚠️ JSON decode error: {e}")
        print(f"  原始：{raw[:300]}")
        return []


def weave_all(entries: list[dict], batch_size: int = 100, max_concurrent: int = 3) -> list[dict]:
    """
    完整流程：去重预合并 → 分批 LLM 并发合并 → 合并结果

    batch_size: 每批送 LLM 的碎片数量（建议100-200）
    max_concurrent: 最大并发 LLM 调用数（建议3，太高可能触发限流）
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # 预合并（只做去重，不做时间合并）
    merged = pre_merge_by_time(entries)
    print(f"去重后：{len(entries)} 条 → {len(merged)} 条")

    if not merged:
        return []

    # 构建批次
    batches = [merged[i:i + batch_size] for i in range(0, len(merged), batch_size)]
    total_batches = len(batches)
    print(f"分 {total_batches} 批次，并发数 {max_concurrent}")

    all_paragraphs = []
    completed = 0

    def process_batch(batch_idx: int, batch: list[dict]) -> tuple[int, list[dict]]:
        client = load_minimax_client()
        paras = weave_batch(client, batch)
        return batch_idx, paras

    results: dict[int, list[dict]] = {}

    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        futures = {executor.submit(process_batch, i, b): i for i, b in enumerate(batches)}
        for future in as_completed(futures):
            batch_idx, paras = future.result()
            completed += 1
            results[batch_idx] = paras
            print(f"  批次 {completed}/{total_batches} 完成：{len(paras)} 段落")

    # 按批次顺序排序（确保时间线正确）
    for i in sorted(results.keys()):
        all_paragraphs.extend(results[i])

    return all_paragraphs


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='将 VTT 碎片合并为段落')
    parser.add_argument('fragments_json', help='vtt_parser.py 输出的 JSON 文件')
    parser.add_argument('--output', '-o', help='输出 JSON 文件路径')
    args = parser.parse_args()

    with open(args.fragments_json, encoding='utf-8') as f:
        entries = json.load(f)

    print(f"加载 {len(entries)} 条碎片，开始段落合并...")
    paragraphs = weave_all(entries)

    print(f"\n✅ 共生成 {len(paragraphs)} 个段落")

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(paragraphs, f, ensure_ascii=False, indent=2)
        print(f"已保存 → {args.output}")

    # 打印前几条预览
    print("\n前 5 条段落预览：")
    for p in paragraphs[:5]:
        print(f"  {p['start']}  {p['en'][:70]}")

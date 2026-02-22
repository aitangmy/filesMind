#!/usr/bin/env python3
"""
Markdown层级修复工具
根据章节编号（如1.2.3）自动推断正确的标题层级
"""

import re

_OCR_LEVEL_JITTER_TOLERANCE = 1


def _extract_heading_number_signature(title: str):
    chapter_pattern = re.compile(r"^(\d+(?:\.\d+)*)\.?\s*(.*)")
    m = chapter_pattern.match((title or "").strip())
    if not m:
        return None
    parts = []
    for token in m.group(1).split("."):
        if not token:
            continue
        try:
            parts.append(int(token))
        except (TypeError, ValueError):
            return None
    return tuple(parts) if parts else None


def _resolve_level_by_numbering(sig, history: list, fallback_level: int) -> int:
    if not sig:
        return fallback_level

    # Sibling-first: in malformed docs, preserve local sibling continuity before
    # falling back to parent+1.
    for item in reversed(history):
        prev_sig = item.get("sig")
        if not prev_sig:
            continue
        if len(prev_sig) == len(sig) and prev_sig[:-1] == sig[:-1]:
            return int(item.get("level", fallback_level))

    if len(sig) > 1:
        parent_sig = sig[:-1]
        for item in reversed(history):
            if item.get("sig") == parent_sig:
                return int(item.get("level", fallback_level)) + 1

    if len(sig) == 1:
        for item in reversed(history):
            prev_sig = item.get("sig")
            if prev_sig and len(prev_sig) == 1:
                return int(item.get("level", fallback_level))

    return fallback_level


def _snap_orig_level_for_stack(orig_level: int, level_stack: list, jitter_tolerance: int = _OCR_LEVEL_JITTER_TOLERANCE) -> int:
    if jitter_tolerance <= 0 or len(level_stack) <= 1:
        return orig_level
    best_orig = None
    best_key = None
    for idx, (stack_orig, _stack_fixed) in enumerate(level_stack[1:], start=1):
        diff = abs(stack_orig - orig_level)
        if diff > jitter_tolerance:
            continue
        # Prefer: (1) closest level, (2) shallower/equal than current level,
        # (3) most recent stack position.
        key = (diff, 0 if stack_orig <= orig_level else 1, -idx)
        if best_key is None or key < best_key:
            best_key = key
            best_orig = stack_orig
    return best_orig if best_orig is not None else orig_level


def _resolve_non_numbered_level(orig_level: int, level_stack: list) -> int:
    effective_orig_level = _snap_orig_level_for_stack(orig_level, level_stack)

    # Close deeper branches first; this prevents stale deep contexts from
    # contaminating sibling alignment.
    while len(level_stack) > 1 and level_stack[-1][0] > effective_orig_level:
        level_stack.pop()

    if level_stack[-1][0] == effective_orig_level:
        return int(level_stack[-1][1])

    fixed_level = int(level_stack[-1][1]) + 1
    level_stack.append((effective_orig_level, fixed_level))
    return fixed_level


def fix_markdown_hierarchy(markdown_content):
    """
    根据章节编号修复Markdown标题层级
    规则:
    - 1.x → H2
    - 1.1.x → H3
    - 1.1.1.x → H4
    - 1.1.1.1.x → H5
    - 1.1.1.1.1.x → H6
    """
    lines = markdown_content.split("\n")
    fixed_lines = []
    level_stack = [(0, 1)]  # (orig_level, fixed_level)
    numbering_history = []

    for line in lines:
        stripped = line.strip()
        header_match = re.match(r"^(#{1,6})\s+(.*)", stripped)
        if not header_match:
            fixed_lines.append(stripped)
            continue

        title = header_match.group(2).strip()
        orig_level = len(header_match.group(1))
        sig = _extract_heading_number_signature(title)

        if sig:
            fallback = len(sig) + 1
            level = _resolve_level_by_numbering(sig, numbering_history, fallback)
            anchor_orig_level = _snap_orig_level_for_stack(orig_level, level_stack)
        else:
            level = _resolve_non_numbered_level(orig_level, level_stack)

        level = min(max(level, 2), 6)
        fixed_lines.append("#" * level + " " + title)
        numbering_history.append({"sig": sig, "level": level})

        if sig:
            # Keep shallower parent context, drop same/deeper stale branches,
            # then anchor at current numbering depth.
            while len(level_stack) > 1 and level_stack[-1][0] >= anchor_orig_level:
                level_stack.pop()
            level_stack.append((anchor_orig_level, level))
        elif len(level_stack) > 1:
            top_orig_level, _top_fixed_level = level_stack[-1]
            level_stack[-1] = (top_orig_level, level)

    return "\n".join(fixed_lines)


def analyze_fixed_structure(markdown_content):
    """分析修复后的结构"""
    lines = markdown_content.split("\n")

    stats = {"H1": 0, "H2": 0, "H3": 0, "H4": 0, "H5": 0, "H6": 0}

    headers = []

    for line in lines:
        match = re.match(r"^(#{1,6})\s+(.*)", line.strip())
        if match:
            level = len(match.group(1))
            title = match.group(2)[:50]
            stats[f"H{level}"] = stats.get(f"H{level}", 0) + 1
            headers.append((level, title))

    return stats, headers


if __name__ == "__main__":
    # 读取原始Markdown
    md_file = r"F:\workspace\filesMind\test_output\test_architecture.md"

    with open(md_file, "r", encoding="utf-8") as f:
        content = f.read()

    print("=" * 70)
    print("修复前的结构")
    print("=" * 70)
    stats_before, _ = analyze_fixed_structure(content)
    for level, count in sorted(stats_before.items()):
        if count > 0:
            print(f"  {level}: {count}")

    print("\n" + "=" * 70)
    print("正在修复层级...")
    print("=" * 70)

    fixed_content = fix_markdown_hierarchy(content)

    print("\n" + "=" * 70)
    print("修复后的结构")
    print("=" * 70)
    stats_after, headers = analyze_fixed_structure(fixed_content)
    for level, count in sorted(stats_after.items()):
        if count > 0:
            print(f"  {level}: {count}")

    # 保存修复后的文件
    output_file = r"F:\workspace\filesMind\test_output\test_architecture_fixed.md"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(fixed_content)

    print(f"\n已保存修复后的文件: {output_file}")

    # 显示修复后的前30个标题
    print("\n" + "=" * 70)
    print("修复后的前30个标题")
    print("=" * 70)
    for level, title in headers[:30]:
        indent = "  " * (level - 1)
        print(f"{indent}[H{level}] {title}")

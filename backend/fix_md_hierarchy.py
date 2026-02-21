#!/usr/bin/env python3
"""
Markdown层级修复工具
根据章节编号（如1.2.3）自动推断正确的标题层级
"""

import re


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

    # 章节编号匹配模式 - 更精确地匹配数字编号
    # 支持: 1.  1.1  1.1.1  1.2.3.4  等格式
    chapter_pattern = re.compile(r"^(\d+(?:\.\d+)*)\.?\s*(.*)")

    for line in lines:
        stripped = line.strip()

        # 检查是否是标题行
        header_match = re.match(r"^(#{1,6})\s+(.*)", stripped)
        if header_match:
            hash_mark = header_match.group(1)
            title = header_match.group(2)

            # 尝试匹配章节编号
            chapter_match = chapter_pattern.match(title)
            if chapter_match:
                num = chapter_match.group(1)
                text = chapter_match.group(2) if chapter_match.group(2) else ""

                # 根据编号确定层级
                num_parts = [p for p in num.split(".") if p]  # 过滤空字符串
                level = len(num_parts) + 1  # 1. → H2, 1.1. → H3

                # 限制在H2-H6范围内
                level = min(max(level, 2), 6)

                # 生成新的标题
                new_header = "#" * level + " " + title
                fixed_lines.append(new_header)
            else:
                # 没有章节编号，保持原样
                fixed_lines.append(stripped)
        else:
            # 非标题行，保持原样
            fixed_lines.append(stripped)

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

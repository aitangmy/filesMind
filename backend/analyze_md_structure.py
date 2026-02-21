#!/usr/bin/env python3
"""分析Markdown文件结构完整性"""

import re

md_file = r"F:\workspace\filesMind\test_output\test_architecture.md"

with open(md_file, "r", encoding="utf-8") as f:
    content = f.read()

lines = content.split("\n")

# 统计各类标题数量
h1_count = 0
h2_count = 0
h3_count = 0
h4_count = 0
h5_count = 0
h6_count = 0
total_headers = 0
list_items = 0
tables = 0
images = 0

header_lines = []

for line in lines:
    stripped = line.strip()

    # 统计标题
    h_match = re.match(r"^(#{1,6})\s+(.*)", stripped)
    if h_match:
        level = len(h_match.group(1))
        title = h_match.group(2)[:50]  # 取前50字符
        header_lines.append((level, title))

        if level == 1:
            h1_count += 1
        elif level == 2:
            h2_count += 1
        elif level == 3:
            h3_count += 1
        elif level == 4:
            h4_count += 1
        elif level == 5:
            h5_count += 1
        elif level == 6:
            h6_count += 1
        total_headers += 1

    # 统计列表项
    if stripped.startswith(("-", "*", "+")):
        list_items += 1

    # 统计表格
    if stripped.startswith("|"):
        tables += 1

    # 统计图片
    if "<!-- image -->" in stripped or "![" in stripped:
        images += 1

print("=" * 60)
print("Markdown结构分析报告")
print("=" * 60)
print(f"\n总行数: {len(lines)}")
print(f"总标题数: {total_headers}")
print("\n标题层级分布:")
print(f"  H1 (#):    {h1_count}")
print(f"  H2 (##):   {h2_count}")
print(f"  H3 (###):  {h3_count}")
print(f"  H4 (####): {h4_count}")
print(f"  H5 (#####): {h5_count}")
print(f"  H6 (######): {h6_count}")
print(f"\n列表项数量: {list_items}")
print(f"表格行数: {tables}")
print(f"图片标记: {images}")

# 检查层级跳级问题
print("\n" + "=" * 60)
print("层级结构检查")
print("=" * 60)

prev_level = 0
jump_issues = []
for i, (level, title) in enumerate(header_lines):
    if prev_level > 0 and level > prev_level + 1:
        jump_issues.append(f"行{i + 1}: {prev_level} -> {level}: {title[:30]}")
    prev_level = level

if jump_issues:
    print(f"\n发现 {len(jump_issues)} 处层级跳级:")
    for issue in jump_issues[:10]:  # 只显示前10个
        print(f"  - {issue}")
    if len(jump_issues) > 10:
        print(f"  ... 还有 {len(jump_issues) - 10} 处")
else:
    print("\n✓ 未发现层级跳级问题")

# 显示前30个标题的结构
print("\n" + "=" * 60)
print("前30个标题结构")
print("=" * 60)
for i, (level, title) in enumerate(header_lines[:30]):
    indent = "  " * (level - 1)
    print(f"{indent}[H{level}] {title}")

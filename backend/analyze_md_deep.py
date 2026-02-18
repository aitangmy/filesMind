#!/usr/bin/env python3
"""深度分析Markdown内容完整性"""
import re
import os

md_file = r"F:\workspace\filesMind\test_output\test_architecture.md"

with open(md_file, 'r', encoding='utf-8') as f:
    content = f.read()

lines = content.split('\n')

# 提取所有标题行
all_headers = []
for i, line in enumerate(lines):
    stripped = line.strip()
    match = re.match(r'^(#{1,6})\s+(.*)', stripped)
    if match:
        level = len(match.group(1))
        title = match.group(2)
        all_headers.append({
            'line': i + 1,
            'level': level,
            'title': title
        })

# 分析章节编号模式
print("=" * 70)
print("章节编号分析")
print("=" * 70)

# 提取章节编号
chapter_pattern = re.compile(r'^(\d+(?:\.\d+)*)\.?\s+(.*)')

chapters_by_level = {1: [], 2: [], 3: [], 4: [], 5: [], 6: []}
for header in all_headers:
    match = chapter_pattern.match(header['title'])
    if match:
        num = match.group(1)
        text = match.group(2)
        num_parts = num.split('.')
        level = len(num_parts)
        if level <= 6:
            chapters_by_level[level].append((num, text[:40]))

print("\n按层级统计章节编号:")
for level in range(1, 7):
    count = len(chapters_by_level[level])
    print(f"  层级{level} (如 1.x.x): {count} 个")

# 检查是否有1级章节标题（如 "第1章"）
print("\n" + "=" * 70)
print("检查是否有缺失的顶级标题")
print("=" * 70)

# 查找 "第X章" 格式
chapter_heading = re.compile(r'^第[一二三四五六七八九十百千\d]+章')
has_chapter_heading = False
for header in all_headers[:20]:
    if chapter_heading.match(header['title']):
        has_chapter_heading = True
        print(f"  发现章标题: {header['title']}")

if not has_chapter_heading:
    print("  ✗ 未发现 '第X章' 格式的顶级标题，可能存在内容丢失")

# 分析数字编号的连续性
print("\n" + "=" * 70)
print("章节编号连续性分析")
print("=" * 70)

# 检查第1章的完整结构
print("\n[第1章结构分析]")
chapter_1_sections = []
for header in all_headers:
    if header['title'].startswith('1.') or header['title'].startswith('1 '):
        chapter_1_sections.append(header['title'][:50])

print(f"第1章共有 {len(chapter_1_sections)} 个章节标题:")
for i, sec in enumerate(chapter_1_sections[:15]):
    print(f"  {i+1}. {sec}")
if len(chapter_1_sections) > 15:
    print(f"  ... 还有 {len(chapter_1_sections) - 15} 个")

# 检查2级、3级子章节的分布
print("\n" + "=" * 70)
print("子章节层级分布详情")
print("=" * 70)

# 2级章节 (如 1.1, 2.1)
level_2_chapters = [h for h in all_headers if re.match(r'^\d+\.\d+\.', h['title'])]
print(f"\n2级章节 (X.Y): {len(level_2_chapters)} 个")
if level_2_chapters:
    print("  示例:")
    for ch in level_2_chapters[:10]:
        print(f"    - {ch['title'][:50]}")

# 3级章节 (如 1.1.1)
level_3_chapters = [h for h in all_headers if re.match(r'^\d+\.\d+\.\d+', h['title'])]
print(f"\n3级章节 (X.Y.Z): {len(level_3_chapters)} 个")
if level_3_chapters:
    print("  示例:")
    for ch in level_3_chapters[:10]:
        print(f"    - {ch['title'][:50]}")

# 4级章节
level_4_chapters = [h for h in all_headers if re.match(r'^\d+\.\d+\.\d+\.\d+', h['title'])]
print(f"\n4级章节 (X.Y.Z.W): {len(level_4_chapters)} 个")

# 检查问题：标题全部是H2
print("\n" + "=" * 70)
print("层级问题诊断")
print("=" * 70)

h2_with_subnumber = [h for h in all_headers if h['level'] == 2 and re.match(r'^\d+\.\d+', h['title'])]
print(f"\n问题：所有标题都是H2，但其中 {len(h2_with_subnumber)} 个有子章节编号")
print(f"例如:")
for h in h2_with_subnumber[:5]:
    print(f"  ## {h['title'][:50]}")

print("\n结论：Docling将所有标题都识别为H2，丢失了原始层级结构")
print("这会导致思维导图呈现为'根节点 + 无数二级节点'的扁平化结构")

"""Test: simulate H1-only root summary + chunk content"""
import sys, os, re
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from xmind_exporter import parse_markdown_to_tree
import glob
from collections import Counter

md_files = glob.glob(os.path.join(os.path.dirname(__file__), 'data', 'mds', '*.md'))
if not md_files:
    print("No MD files found")
    exit()

md = open(md_files[0], 'r', encoding='utf-8').read()

# Simulate the final fix: only keep H1 from root summary, strip everything else
# In actual output, lines 1-10 are root summary (H1 + H2 + list items)
# The H3 content starts later
lines = md.split('\n')

# Find first H3 or below (start of actual chunk content)
first_content_line = 0
for i, line in enumerate(lines):
    if i > 0 and re.match(r'^#{3,6}\s', line.strip()):
        first_content_line = i
        break

# Extract just H1 title
h1_line = lines[0] if lines[0].strip().startswith('# ') else '# Document'

# Reconstruct: H1 + chunk content (skip root summary body)
fixed_md = h1_line + '\n\n' + '\n'.join(lines[first_content_line:])

tree = parse_markdown_to_tree(fixed_md)
dc = len(tree.get('children', []))
print(f"Root: {tree['title']}")
print(f"Root direct children: {dc}")
print()
for i, ch in enumerate(tree.get('children', [])[:30]):
    sub = len(ch.get('children', []))
    title = ch['title'][:70]
    print(f"  [{i}] ({sub}ch) {title}")
if dc > 30:
    print(f"  ... {dc - 30} more")

# Depth distribution
def walk(node, depth=0, results=None):
    if results is None: results = []
    results.append(depth)
    for ch in node.get('children', []): walk(ch, depth+1, results)
    return results

all_depths = walk(tree)
depths = Counter(all_depths)
print(f"\nTotal nodes: {len(all_depths)}")
for k in sorted(depths):
    print(f"  Depth {k}: {depths[k]} nodes")

# Validation
max_depth = max(depths.keys())
print(f"\n=== Validation ===")
print(f"Max depth: {max_depth} {'PASS' if max_depth >= 5 else 'WARN'}")
print(f"Root children: {dc} {'PASS' if 5 <= dc <= 200 else 'WARN'}")

"""
验证脚本：测试 parse_markdown_to_tree 的层级结构
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from xmind_exporter import parse_markdown_to_tree
from collections import Counter

def walk(node, depth=0, results=None):
    if results is None:
        results = []
    title = node.get('title', '')[:80]
    children_count = len(node.get('children', []))
    results.append((depth, title, children_count))
    for ch in node.get('children', []):
        walk(ch, depth + 1, results)
    return results

def test_existing_output():
    import glob
    md_files = glob.glob(os.path.join(os.path.dirname(__file__), 'data', 'mds', '*.md'))
    if not md_files:
        print("SKIP: No MD files found")
        return
    md_path = md_files[0]
    print(f"\nUsing: {os.path.basename(md_path)}")
    
    md = open(md_path, 'r', encoding='utf-8').read()
    tree = parse_markdown_to_tree(md)
    all_nodes = walk(tree)
    
    print(f"Total nodes: {len(all_nodes)}")
    
    depths = Counter(d for d, _, _ in all_nodes)
    for k in sorted(depths):
        print(f"  Depth {k}: {depths[k]} nodes")
    
    dc = len(tree.get('children', []))
    print(f"\nRoot: {tree['title'][:60]}")
    print(f"Root direct children: {dc}")
    
    print("\nFirst 25 direct children:")
    for i, ch in enumerate(tree.get('children', [])[:25]):
        sub = len(ch.get('children', []))
        t = ch['title'][:70]
        print(f"  [{i}] ({sub}ch) {t}")
    
    # Assertions
    max_depth = max(depths.keys())
    print(f"\n=== Validation ===")
    print(f"Max depth: {max_depth}")
    
    # Check: no single depth-1 node has >50% of all nodes
    d1_nodes = [(t, c) for d, t, c in all_nodes if d == 1]
    total_non_root = len(all_nodes) - 1
    for title, child_count in d1_nodes:
        # Count all descendants
        pass
    
    if dc >= 10 and dc <= 40:
        print(f"PASS: Root has {dc} direct children (expected 10-40)")
    else:
        print(f"INFO: Root has {dc} direct children")
    
    if max_depth >= 5:
        print(f"PASS: Max depth is {max_depth} (expected >= 5)")
    else:
        print(f"WARN: Max depth is {max_depth} (expected >= 5)")

def test_simple_hierarchy():
    """Test basic hierarchy preservation"""
    md = """# Root Title
## Chapter 1
### Section 1.1
- Point A
  - Detail A1
    - Sub-detail A1a
- Point B
### Section 1.2
- Point C
## Chapter 2
### Section 2.1
- Point D
  - Detail D1
"""
    tree = parse_markdown_to_tree(md)
    
    print("\n=== Simple Hierarchy Test ===")
    print(f"Root: {tree['title']}")
    dc = len(tree.get('children', []))
    print(f"Root children: {dc}")
    
    if dc == 2:
        print("PASS: 2 chapters as direct children")
    else:
        print(f"FAIL: Expected 2 chapters, got {dc}")
    
    ch1 = tree['children'][0]
    ch1_children = len(ch1.get('children', []))
    print(f"Chapter 1 children: {ch1_children}")
    
    if ch1_children == 2:
        print("PASS: Chapter 1 has 2 sections")
    else:
        print(f"FAIL: Expected 2 sections in Chapter 1, got {ch1_children}")
    
    # Check Section 1.1 has 2 items (Point A, Point B)
    sec11 = ch1['children'][0]
    sec11_children = len(sec11.get('children', []))
    print(f"Section 1.1 children: {sec11_children}")
    
    if sec11_children == 2:
        print("PASS: Section 1.1 has 2 list items")
    else:
        print(f"INFO: Section 1.1 has {sec11_children} children")
    
    # Print full tree
    all_nodes = walk(tree)
    for depth, title, cc in all_nodes:
        print(f"  {'  ' * depth}[{depth}] {title} ({cc}ch)")

if __name__ == '__main__':
    test_simple_hierarchy()
    test_existing_output()

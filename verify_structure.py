import sys
import os

# Ensure backend module can be imported
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from backend.structure_utils import build_hierarchy_tree

# 模拟一个复杂的 Markdown 文档
sample_md = """
这是前言部分，属于 Root 节点的内容。
它应该被保留。

# 第一章 基础
这是第一章的介绍。

## 1.1 定义
这是 1.1 的正文内容，非常长...
(此处省略 1000 字)

## 1.2 历史
### 1.2.1 古代
内容 A

### 1.2.2 现代
内容 B

# 第二章 进阶
## 2.1 核心概念
"""

def test_structure():
    print("Building tree...")
    root = build_hierarchy_tree(sample_md)
    
    # 验证 Root 内容 (孤儿内容)
    print(f"Root Content: {root.full_content[:20]}...") 
    assert "前言部分" in root.full_content
    
    # 验证层级
    chap1 = root.children[0]
    print(f"Node: {chap1.topic}, Level: {chap1.level}")
    assert chap1.topic == "第一章 基础"
    
    sec1_1 = chap1.children[0]
    print(f"  Node: {sec1_1.topic}, Breadcrumbs: {sec1_1.get_breadcrumbs()}")
    assert sec1_1.topic == "1.1 定义"
    assert "第一章 基础" in sec1_1.get_breadcrumbs()
    
    # 验证回溯 (1.2.2 -> 第二章)
    chap2 = root.children[1]
    print(f"Node: {chap2.topic}")
    assert chap2.topic == "第二章 进阶"

    print("\n✅ 验证通过！骨架提取逻辑正确。")

if __name__ == "__main__":
    test_structure()

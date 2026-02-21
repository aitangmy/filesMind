"""Regression tests for H1-only root summary trimming."""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import structure_utils as su  # noqa: E402


def _trim_to_h1_plus_h3_content(markdown: str) -> str:
    """Keep the H1 title and real content beginning from first H3+ heading."""
    lines = markdown.split("\n")
    if not lines:
        return "# Document\n"

    h1_line = lines[0] if lines[0].strip().startswith("# ") else "# Document"

    first_content_line = None
    for i, line in enumerate(lines):
        if i > 0 and re.match(r"^#{3,6}\s", line.strip()):
            first_content_line = i
            break

    if first_content_line is None:
        return f"{h1_line}\n"
    return f"{h1_line}\n\n" + "\n".join(lines[first_content_line:])


def _max_depth(node, depth: int = 0) -> int:
    if not node.children:
        return depth
    return max(_max_depth(child, depth + 1) for child in node.children)


def test_trimmed_root_summary_keeps_deep_structure():
    markdown = """# 1. Project Handbook
## Executive Summary
- Snapshot A
- Snapshot B
### 1.1 Architecture
#### 1.1.1 Service Layout
Key details A
### 1.2 Data Flow
#### 1.2.1 Ingestion
Key details B
"""
    fixed = _trim_to_h1_plus_h3_content(markdown)
    tree = su.build_hierarchy_tree(fixed)

    assert len(tree.children) == 1
    doc = tree.children[0]
    assert doc.topic == "1. Project Handbook"

    direct_topics = [child.topic for child in doc.children]
    assert "Executive Summary" not in direct_topics
    assert "1.1 Architecture" in direct_topics
    assert "1.2 Data Flow" in direct_topics
    assert _max_depth(tree) >= 3


def test_trimmed_root_summary_falls_back_to_h1_when_no_h3_exists():
    markdown = """# Lightweight Notes
## Summary
- A
- B
"""
    fixed = _trim_to_h1_plus_h3_content(markdown)
    tree = su.build_hierarchy_tree(fixed)

    assert len(tree.children) == 1
    assert tree.children[0].topic == "Lightweight Notes"
    assert tree.children[0].children == []

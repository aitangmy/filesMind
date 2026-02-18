"""
test_universal_hf.py — Verify Method A+B universal header/footer detection

Run with:
    python backend/test_universal_hf.py
"""
import sys
import json
sys.path.insert(0, "backend")

from structure_utils import (
    detect_and_remove_headers_footers,
    preprocess_markdown,
    build_hierarchy_tree,
    _detect_toc_region,
    _is_split_heading,
    is_valid_heading,
    infer_level_from_numbering,
)

results = []

def check(name, got, expected, note=""):
    ok = got == expected
    results.append({"test": name, "pass": ok, "expected": repr(expected), "got": repr(got), "note": note})
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}")
    if not ok:
        print(f"       expected: {repr(expected)}")
        print(f"       got:      {repr(got)}")
    if note:
        print(f"       note: {note}")


# ─────────────────────────────────────────────────────────────────────────────
# Method B: Frequency-based header/footer detection
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== Method B: Frequency-Based Header/Footer Detection ===")

# Simulate a 5-page document using explicit page-break markers.
# Each page has: HEADER, content, FOOTER (except last page has no footer).
# This mirrors real Docling output which can emit <!-- page break --> markers.
HEADER = "Company Confidential Report 2024"
FOOTER = "Page"
UNIQUE_CONTENT = [
    "Introduction to the system",
    "Architecture overview",
    "Database design",
    "Security considerations",
    "Deployment guide",
]

lines = []
for i, content in enumerate(UNIQUE_CONTENT):
    if i > 0:
        lines.append("<!-- page break -->")
    lines.append(HEADER)
    lines.append("")
    lines.append(f"## Chapter {i+1}")
    lines.append(content)
    lines.append("")
    if i < 4:  # footer on 4/5 pages
        lines.append(FOOTER)

cleaned, fps = detect_and_remove_headers_footers(lines)

check("HF-B-1 Header fingerprint detected",
      HEADER.lower() in fps, True,
      f"fingerprints: {fps}")
check("HF-B-2 Footer fingerprint detected",
      FOOTER.lower() in fps, True)
check("HF-B-3 Chapter headings NOT removed",
      any("## Chapter" in l for l in cleaned), True)
check("HF-B-4 Unique content NOT removed",
      any("Architecture overview" in l for l in cleaned), True)
check("HF-B-5 Header lines replaced with blank",
      all(l != HEADER for l in cleaned), True)

# Test: content that appears only once should NOT be removed
RARE_LINE = "This line appears only once in the document"
lines_with_rare = lines + [RARE_LINE]
cleaned2, fps2 = detect_and_remove_headers_footers(lines_with_rare)
check("HF-B-6 Rare line NOT removed",
      any(RARE_LINE in l for l in cleaned2), True)

# Test: too few pages → no removal
short_lines = [HEADER, "Content A", HEADER, "Content B"]
cleaned3, fps3 = detect_and_remove_headers_footers(short_lines)
check("HF-B-7 Too few pages → no removal",
      len(fps3), 0, "Need >= 2 pages for reliable detection")

# ─────────────────────────────────────────────────────────────────────────────
# Chinese document simulation (like the redbook)
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== Chinese Document Simulation ===")

CHINESE_HEADER = "2026 年 5 月芝士架构公共知识红宝书（系统架构设计师公共基础知识）"
CHINESE_FOOTER = "添加微信 deckardcain4 加群"

cn_lines = []
for i in range(6):  # 6 pages
    if i > 0:
        cn_lines.append("<!-- page break -->")
    cn_lines.append(CHINESE_HEADER)
    cn_lines.append("")
    cn_lines.append(f"## {i+1}.1 章节标题")
    cn_lines.append("这是正文内容，描述系统架构的基本概念。")
    cn_lines.append("")
    cn_lines.append(CHINESE_FOOTER)
    cn_lines.append("")

cn_cleaned, cn_fps = detect_and_remove_headers_footers(cn_lines)

check("CN-1 Chinese header detected",
      any(CHINESE_HEADER[:10].lower() in fp for fp in cn_fps), True)
check("CN-2 Chinese footer detected",
      any("添加微信" in fp for fp in cn_fps), True)
check("CN-3 Chapter headings preserved",
      any("## " in l for l in cn_cleaned), True)
check("CN-4 Body text preserved",
      any("正文内容" in l for l in cn_cleaned), True)

# ─────────────────────────────────────────────────────────────────────────────
# TOC Detection
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== TOC Detection ===")

toc_lines = [
    "## 目录",
    "1.1 系统架构 ...... 1",
    "1.2 软件架构 ...... 5",
    "1.3 设计模式 ...... 12",
    "1.4 数据库 ...... 18",
    "1.5 分布式 ...... 25",
    "## 第一章 系统架构",
    "正文内容",
]
s, e = _detect_toc_region(toc_lines)
check("TOC-1 TOC detected", s >= 0, True, f"start={s}, end={e}")

no_toc = ["## 第一章", "正文", "## 1.1 概述", "更多内容"]
s2, e2 = _detect_toc_region(no_toc)
check("TOC-2 No TOC in normal content", s2, -1)

# ─────────────────────────────────────────────────────────────────────────────
# Split Heading Merge
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== Split Heading Merge ===")

split_md = """## 1.3.9.
## 其他模型-增量模型（次重点 ★★★☆☆ ）

## Q2
## ：红宝书背出就稳了吗？

## 1.1 正常标题
正文内容
"""

processed = preprocess_markdown(split_md)
proc_lines = processed.split('\n')

check("SPLIT-1 1.3.9. merged with title",
      any("1.3.9." in l and "其他模型" in l for l in proc_lines), True)
check("SPLIT-2 Q2 merged with title",
      any("Q2" in l and "红宝书" in l for l in proc_lines), True)
check("SPLIT-3 Normal heading preserved",
      any("1.1 正常标题" in l for l in proc_lines), True)

# ─────────────────────────────────────────────────────────────────────────────
# Q-series heading level inference
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== Q-Series Heading Level Inference ===")

check("Q-1 Q1 → level 2", infer_level_from_numbering("Q1：什么是系统架构？", 3), 2)
check("Q-2 Q10 → level 2", infer_level_from_numbering("Q10 如何备考？", 3), 2)
check("Q-3 1.1.1 → level 3", infer_level_from_numbering("1.1.1 子节标题", 2), 3)
check("Q-4 2×10ns rejected", infer_level_from_numbering("2×10ns + 5×10ns", 2), 2,
      "math expression should fall back to markdown level")

# ─────────────────────────────────────────────────────────────────────────────
# is_valid_heading
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== is_valid_heading ===")

check("VH-1 Normal heading valid", is_valid_heading("1.1 系统架构概述"), True)
check("VH-2 Formula rejected", is_valid_heading("2×10ns + 5×10ns = 7×10ns"), False)
check("VH-3 List item rejected", is_valid_heading("2）以下关于..."), False)
check("VH-4 Too long rejected",
      is_valid_heading("这是一段非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常长的文本，超过了六十个字符的限制"), False)

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
passed = sum(1 for r in results if r["pass"])
total  = len(results)
print(f"\n{'='*55}")
print(f"Results: {passed}/{total} passed")
print(f"{'='*55}")

with open("backend/test_universal_hf_results.json", "w", encoding="utf-8") as f:
    json.dump({"passed": passed, "total": total, "tests": results}, f,
              ensure_ascii=False, indent=2)
print("Results saved to backend/test_universal_hf_results.json")

sys.exit(0 if passed == total else 1)

import re
import json
from collections import Counter

# =============================================================================
# structure_utils.py — PDF Markdown → Hierarchy Tree
#
# Enhancement history:
#   v1  Original: level inferred from '#' count only
#   v2  Solution C: numeric section inference (1.1.1 → depth 3)
#   v3  Fix 1: tightened numeric regex (reject "2×10ns")
#       Fix 2: is_valid_heading() to demote body text / formulas
#   v4  Enhancement 1 (Method B): frequency+position-based HF removal
#       Enhancement 2: split-heading merge (## 1.3.9. + ## Title → one node)
#       Enhancement 3: TOC region detection and skipping
#       Enhancement 4: Q-series heading support (Q1, Q2 …)
# =============================================================================


# ── Enhancement 1 (Method B): Frequency+Position-based HF detection ──────────
#
# Core idea: In a PDF, page headers and footers:
#   (a) Repeat on many pages (frequency criterion)
#   (b) Appear at the very top or bottom of each page (position criterion)
#
# Both criteria must be satisfied to avoid false positives (e.g. a common
# phrase in body text that happens to repeat across pages).
#
# This is 100% universal — no keyword lists, no language assumptions.

_HF_MIN_PAGE_FRACTION = 0.40   # line must appear in ≥ 40% of pages
_HF_APPROX_LINES_PER_PAGE = 30 # used when no page-break markers are present
_HF_MIN_PAGES = 2              # need at least 2 pages for reliable detection
_HF_MAX_LINE_LEN = 120         # very long lines are never headers/footers
_HF_POSITION_ZONE = 0.30       # top/bottom 30% of each page segment = HF zone


def _normalise_hf_line(line: str) -> str:
    """Normalise a line for frequency comparison."""
    line = re.sub(r'^#+\s*', '', line)   # strip heading markers
    line = re.sub(r'\s+', ' ', line)     # collapse whitespace
    return line.strip().lower()


def detect_and_remove_headers_footers(lines: list) -> tuple:
    """
    Method B: Frequency+Position-based header/footer removal.

    A line is classified as a header/footer only if it satisfies BOTH:
      1. **Frequency**: appears in >= _HF_MIN_PAGE_FRACTION of all page segments.
      2. **Position**: when it appears, it is within the top or bottom
         _HF_POSITION_ZONE fraction of the page segment's lines.

    The positional constraint prevents common body-text phrases from being
    incorrectly classified as headers/footers.

    Returns (cleaned_lines, hf_fingerprints).
    """
    # ── Step 1: Split into page segments ─────────────────────────────────────
    PAGE_BREAK_RE = re.compile(r'<!--\s*page.?break\s*-->', re.IGNORECASE)

    segments = []
    current = []
    for line in lines:
        if PAGE_BREAK_RE.search(line):
            if current:
                segments.append(current)
            current = []
        else:
            current.append(line)
    if current:
        segments.append(current)

    # If no page-break markers, estimate pages by line count
    if len(segments) <= 1:
        all_lines = segments[0] if segments else lines
        n = len(all_lines)
        page_size = max(5, _HF_APPROX_LINES_PER_PAGE)
        segments = [all_lines[i: i + page_size] for i in range(0, n, page_size)]

    num_pages = len(segments)
    if num_pages < _HF_MIN_PAGES:
        return lines, set()

    # ── Step 2: For each segment, record lines in the HF zone ────────────────
    positional_sets = []

    for seg in segments:
        seg_len = len(seg)
        zone_size = max(1, int(seg_len * _HF_POSITION_ZONE))
        hf_zone_indices = set(range(zone_size)) | set(range(seg_len - zone_size, seg_len))

        pos_set = set()
        for idx, raw in enumerate(seg):
            norm = _normalise_hf_line(raw)
            if not norm or len(norm) > _HF_MAX_LINE_LEN:
                continue
            if idx in hf_zone_indices:
                pos_set.add(norm)
        positional_sets.append(pos_set)

    # ── Step 3: Count frequency in positional zone ────────────────────────────
    pos_page_count = Counter()
    for pos_set in positional_sets:
        for norm in pos_set:
            pos_page_count[norm] += 1

    # ── Step 4: Identify header/footer fingerprints ───────────────────────────
    threshold = max(2, int(num_pages * _HF_MIN_PAGE_FRACTION))
    hf_fingerprints = {
        norm for norm, count in pos_page_count.items()
        if count >= threshold
    }

    if hf_fingerprints:
        print(
            f"[Method B] Detected {len(hf_fingerprints)} header/footer fingerprint(s) "
            f"(threshold: {threshold}/{num_pages} pages): "
            + ", ".join(repr(fp[:40]) for fp in list(hf_fingerprints)[:5])
        )

    # ── Step 5: Remove matching lines ────────────────────────────────────────
    cleaned = []
    for raw in lines:
        norm = _normalise_hf_line(raw)
        if norm in hf_fingerprints:
            cleaned.append('')
        else:
            cleaned.append(raw)

    return cleaned, hf_fingerprints


# ── Enhancement 3: TOC detection ─────────────────────────────────────────────
_TOC_LINE_RE = re.compile(r'(?:\.{3,}|…{2,})\s*\d+\s*$')
_TOC_DENSITY_THRESHOLD = 0.30
_TOC_SCAN_LINES = 600


def _detect_toc_region(lines: list) -> tuple:
    """
    Scan the first _TOC_SCAN_LINES lines and return (start, end) indices of
    the TOC block, or (-1, -1) if no TOC is detected.
    """
    scan = lines[:_TOC_SCAN_LINES]
    toc_flags = [bool(_TOC_LINE_RE.search(l)) for l in scan]

    first = next((i for i, f in enumerate(toc_flags) if f), -1)
    last  = next((i for i, f in enumerate(reversed(toc_flags)) if f), -1)
    if first == -1:
        return (-1, -1)
    last = len(toc_flags) - 1 - last

    region_len = last - first + 1
    density = sum(toc_flags[first:last + 1]) / max(region_len, 1)
    if density < _TOC_DENSITY_THRESHOLD:
        return (-1, -1)

    start = max(0, first - 5)
    return (start, last)


# ── Enhancement 2: Split-heading detection ───────────────────────────────────
_SPLIT_HEADING_RE = re.compile(
    r'^(#+)\s*'
    r'(?:'
    r'Q?\d+(?:\.\d+)*\.?'
    r'|[A-Z]\d*'
    r')\s*$',
    re.IGNORECASE
)


def _is_split_heading(line: str) -> bool:
    """True if this heading line contains ONLY a section number / Q-label."""
    return bool(_SPLIT_HEADING_RE.match(line.rstrip()))


# ── Enhancement 4 + Fix 1: Strict numeric section regex ──────────────────────
_STRICT_NUMERIC_RE = re.compile(
    r'^(\d+(?:\.\d+)*)\.?\s*'
    r'(?=[a-zA-Z\u4e00-\u9fff\uff08\u3010\[（【])'
)

# ── Fix 2 helpers: body-text / formula detection ─────────────────────────────
_BODY_TEXT_STARTERS = re.compile(
    r'^['
    r'=＝'
    r'（('
    r'①②③④⑤⑥⑦⑧⑨⑩'
    r'πσ∈∉∪∩≡≠≤≥∀∃∧∨¬'
    r'+-/*'
    r']'
)
_LIST_ITEM_RE   = re.compile(r'^\d+[）)、]')
_FORMULA_PATTERNS = re.compile(
    r'[=＝×÷±∈∉≡≠≤≥∧∨¬πσ]'
    r'|\d+\s*[×÷]\s*\d+'
    r'|\{[^}]{0,60}\}'
    r'|\[[^\]]{0,60}\]'
)
_MAX_HEADING_LENGTH = 60


def is_valid_heading(topic: str) -> bool:
    """
    Heuristic filter: decide whether a Markdown heading line is a genuine
    section title or body text that Docling mis-labelled as a heading.
    """
    topic = topic.strip()

    if len(topic) > _MAX_HEADING_LENGTH:
        return False

    if _BODY_TEXT_STARTERS.match(topic):
        return False

    if _LIST_ITEM_RE.match(topic):
        return False

    if _FORMULA_PATTERNS.search(topic):
        has_section_number = bool(_STRICT_NUMERIC_RE.match(topic))
        has_chinese_chapter = bool(re.match(
            r'^\u7b2c[\u96f6\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\d]+'
            r'[\u7ae0\u8282\u7bc7\u90e8]',
            topic
        ))
        if not has_section_number and not has_chinese_chapter:
            return False

    return True


# ── Solution C: numeric level inference ──────────────────────────────────────

def infer_level_from_numbering(topic: str, markdown_level: int) -> int:
    """
    Infer the true heading level from numeric section numbering.

    Enhancement 4: Q-series headings (Q1, Q2 …) are treated as level 2.
    Fix 1: uses _STRICT_NUMERIC_RE which rejects math expressions.
    """
    topic = topic.strip()

    numeric_match = _STRICT_NUMERIC_RE.match(topic)
    if numeric_match:
        segments = numeric_match.group(1).split('.')
        depth = len([s for s in segments if s])
        return depth

    if re.match(
        r'^\u7b2c[\u96f6\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\d]+'
        r'[\u7ae0\u8282\u7bc7\u90e8]',
        topic
    ):
        return 1

    if re.match(r'^(?:Chapter|Section|Part|Appendix)\s+[\dIVXivx]+', topic, re.IGNORECASE):
        return 1

    # Enhancement 4: Q-series FAQ headings
    if re.match(r'^Q\d+\s*[：:。\s]', topic, re.IGNORECASE):
        return 2

    return markdown_level


# ── Pre-processing pipeline ───────────────────────────────────────────────────

def preprocess_markdown(text: str) -> str:
    """
    Clean and normalise the raw Markdown produced by Docling.

    Pass 1 — Header/footer removal (Method B: frequency+position-based)
    Pass 2 — TOC region skipping
    Pass 3 — Split-heading merge
    """
    lines = text.split('\n')

    # ── Pass 1: frequency+position-based header/footer removal ───────────────
    lines, _hf_fps = detect_and_remove_headers_footers(lines)

    # ── Pass 2: TOC region detection and heading demotion ────────────────────
    toc_start, toc_end = _detect_toc_region(lines)
    if toc_start >= 0:
        print(f"[preprocess] TOC detected at lines {toc_start}–{toc_end}")
        for i in range(toc_start, toc_end + 1):
            m = re.match(r'^(#+)\s+(.*)', lines[i])
            if m:
                lines[i] = m.group(2)

    # ── Pass 3: split-heading merge ───────────────────────────────────────────
    merged = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if _is_split_heading(line):
            hashes = re.match(r'^(#+)', line).group(1)
            label  = line.strip().lstrip('#').strip()

            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1

            if j < len(lines):
                next_line = lines[j].strip()
                next_text = re.sub(r'^#+\s*', '', next_line).strip()
                if next_text:
                    merged.append(f"{hashes} {label}{next_text}")
                    i = j + 1
                    continue

        merged.append(line)
        i += 1
    lines = merged

    return '\n'.join(lines)


# ── Tree data structures ──────────────────────────────────────────────────────

class TreeNode:
    def __init__(self, topic, level, parent=None):
        self.id = str(id(self))
        self.topic = topic
        self.level = level
        self.content_lines = []
        self.children = []
        self.ai_details = []
        self.parent = parent

    @property
    def full_content(self):
        return "\n".join(self.content_lines).strip()

    def add_child(self, node):
        self.children.append(node)
        node.parent = self

    def get_breadcrumbs(self):
        chain = []
        curr = self
        while curr:
            if curr.level > 0:
                chain.append(curr.topic)
            curr = curr.parent
        return " > ".join(reversed(chain))

    def to_dict(self):
        return {
            "topic": self.topic,
            "level": self.level,
            "content_length": len(self.full_content),
            "children": [child.to_dict() for child in self.children]
        }


# ── Main parsing function ─────────────────────────────────────────────────────

def build_hierarchy_tree(markdown_text):
    """
    Parse Markdown into a TreeNode tree.

    Pipeline:
      1. preprocess_markdown()  — Method B HF removal, TOC skip, split merge
      2. Pre-scan valid headings to decide numeric inference mode
      3. Main loop: validate headings, infer level, build tree
    """
    markdown_text = preprocess_markdown(markdown_text)
    lines = markdown_text.split('\n')

    root  = TreeNode("Root", 0)
    stack = [root]

    # Pre-scan for numeric inference threshold
    raw_header_lines = [l for l in lines if re.match(r'^(#+)\s+(.*)', l)]

    valid_header_lines = []
    for l in raw_header_lines:
        m = re.match(r'^(#+)\s+(.*)', l)
        if m and is_valid_heading(m.group(2).strip()):
            valid_header_lines.append(l)

    numbered_count = sum(
        1 for l in valid_header_lines
        if re.match(
            r'^#+\s+(?:'
            r'\d+(?:\.\d+)*\.?\s*(?=[a-zA-Z\u4e00-\u9fff\uff08\u3010\[（【])'
            r'|\u7b2c[\u96f6\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\d]+[\u7ae0\u8282\u7bc7\u90e8]'
            r'|(?:Chapter|Section|Part|Appendix)\s+[\dIVXivx]+'
            r'|Q\d+\s*[：:。\s]'
            r')',
            l, re.IGNORECASE
        )
    )
    use_numbering_inference = (
        len(valid_header_lines) > 0 and
        (numbered_count / len(valid_header_lines)) >= 0.5
    )

    total_raw   = len(raw_header_lines)
    total_valid = len(valid_header_lines)
    demoted     = total_raw - total_valid
    print(
        f"[build_hierarchy_tree] Raw headings: {total_raw}, "
        f"Valid: {total_valid}, Demoted: {demoted}, "
        f"Numbered: {numbered_count} → "
        f"{'Numeric inference ON' if use_numbering_inference else 'Markdown # count mode'}"
    )

    for line in lines:
        header_match = re.match(r'^(#+)\s+(.*)', line)

        if header_match:
            markdown_level = len(header_match.group(1))
            topic = header_match.group(2).strip()

            if not is_valid_heading(topic):
                if topic:
                    stack[-1].content_lines.append(topic)
                continue

            if use_numbering_inference:
                level = infer_level_from_numbering(topic, markdown_level)
            else:
                level = markdown_level

            new_node = TreeNode(topic, level)

            while len(stack) > 1 and stack[-1].level >= level:
                stack.pop()

            stack[-1].add_child(new_node)
            stack.append(new_node)

        else:
            line = line.strip()
            if line:
                stack[-1].content_lines.append(line)

    return root


# ── Export helper ─────────────────────────────────────────────────────────────

def tree_to_markdown(node, depth=0):
    """Recursively export the tree as Markdown."""
    lines = []

    if node.level > 0:
        lines.append(f"{'#' * node.level} {node.topic}")

    if node.ai_details:
        for item in node.ai_details:
            lines.append(f"- **{item.get('topic', '')}**")
            for det in item.get('details', []):
                lines.append(f"  - {det}")

    if node.children:
        lines.append("")
        for child in node.children:
            result = tree_to_markdown(child, depth + 1)
            if result:
                lines.append(result)

    return "\n".join(lines).strip()

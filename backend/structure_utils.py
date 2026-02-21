import re
import json
import html
import hashlib
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

_HF_MIN_PAGE_FRACTION = 0.40  # line must appear in ≥ 40% of pages
_HF_APPROX_LINES_PER_PAGE = 30  # used when no page-break markers are present
_HF_MIN_PAGES = 2  # need at least 2 pages for reliable detection
_HF_MAX_LINE_LEN = 120  # very long lines are never headers/footers
_HF_POSITION_ZONE = 0.30  # top/bottom 30% of each page segment = HF zone

_FM_ANCHOR_RE = re.compile(
    r"<!--\s*fm_anchor:(.*?)\s*--|(?:\\)?&lt;!--\s*fm_anchor:(.*?)\s*--(?:\\)?&gt;",
    re.IGNORECASE | re.DOTALL,
)


def _anchor_payload_from_match(match: re.Match) -> str:
    payload = match.group(1) if match.group(1) is not None else match.group(2)
    return html.unescape((payload or "").strip())


def _normalise_hf_line(line: str) -> str:
    """Normalise a line for frequency comparison."""
    line = re.sub(r"^#+\s*", "", line)  # strip heading markers
    line = re.sub(r"\s+", " ", line)  # collapse whitespace
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
    PAGE_BREAK_RE = re.compile(r"<!--\s*page.?break\s*-->", re.IGNORECASE)

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
        segments = [all_lines[i : i + page_size] for i in range(0, n, page_size)]

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
    hf_fingerprints = {norm for norm, count in pos_page_count.items() if count >= threshold}

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
            cleaned.append("")
        else:
            cleaned.append(raw)

    return cleaned, hf_fingerprints


# ── Enhancement 3: TOC detection ─────────────────────────────────────────────
_TOC_LINE_RE = re.compile(r"(?:\.{3,}|…{2,})\s*\d+\s*$")
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
    last = next((i for i, f in enumerate(reversed(toc_flags)) if f), -1)
    if first == -1:
        return (-1, -1)
    last = len(toc_flags) - 1 - last

    region_len = last - first + 1
    density = sum(toc_flags[first : last + 1]) / max(region_len, 1)
    if density < _TOC_DENSITY_THRESHOLD:
        return (-1, -1)

    start = max(0, first - 5)
    return (start, last)


# ── Enhancement 2: Split-heading detection ───────────────────────────────────
_SPLIT_HEADING_RE = re.compile(
    r"^\s*(#{1,6})\s*"
    r"(?:"
    r"Q?\d+(?:\.\d+)*\.?"
    r"|[A-Z]\d*"
    r")\s*$",
    re.IGNORECASE,
)


def _is_split_heading(line: str) -> bool:
    """True if this heading line contains ONLY a section number / Q-label."""
    return bool(_SPLIT_HEADING_RE.match(line.rstrip()))


# ── Enhancement 4 + Fix 1: Strict numeric section regex ──────────────────────
_STRICT_NUMERIC_RE = re.compile(
    r"^(\d+(?:\.\d+)*)\.?\s*"
    r"(?=[a-zA-Z\u4e00-\u9fff\uff08\u3010\[（【])"
)

# ── Fix 2 helpers: body-text / formula detection ─────────────────────────────
_BODY_TEXT_STARTERS = re.compile(
    r"^["
    r"=＝"
    r"（("
    r"①②③④⑤⑥⑦⑧⑨⑩"
    r"πσ∈∉∪∩≡≠≤≥∀∃∧∨¬"
    r"+-/*"
    r"]"
)
_LIST_ITEM_RE = re.compile(r"^\d+[）)、]")
_FORMULA_PATTERNS = re.compile(
    r"[=＝×÷±∈∉≡≠≤≥∧∨¬πσ]"
    r"|\d+\s*[×÷]\s*\d+"
    r"|\{[^}]{0,60}\}"
    r"|\[[^\]]{0,60}\]"
)
_MAX_HEADING_LENGTH = 60
_PURE_SYMBOL_RE = re.compile(r"^[\s★☆*#\-_=~`·•\[\]【】()（）]+$")
_PURE_DIGIT_RE = re.compile(r"^\d{2,}$")
_SHORT_GARBAGE_TOKEN_RE = re.compile(r"^[A-Za-z]\d{0,3}[*#]?$")
_DIAGRAM_LABEL_RE = re.compile(r"^[A-Za-z]{1,4}\s*\([^)]{1,30}\)$")
_SENTENCE_PUNCT_RE = re.compile(r"[，。！？；?!;]")
_LONG_DIGIT_PREFIX_2_RE = re.compile(r"^\d{4,}(\d{2}(?:\.\d+)+(?:\.?\s*.*)?)$")
_LONG_DIGIT_PREFIX_1_RE = re.compile(r"^\d{4,}(\d(?:\.\d+)+(?:\.?\s*.*)?)$")
_WEAK_END_PUNCT_RE = re.compile(r"[。！？；，、：:]$")
_WEAK_OPERATOR_PHRASE_RE = re.compile(r"\s+[+＝=]\s+")
_WEAK_SHORT_PAREN_TERM_RE = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9]{1,4}\s*[（(][^）)]{1,12}[）)]$")
_WEAK_TWO_TOKEN_CN_RE = re.compile(r"^[\u4e00-\u9fff]{1,4}\s+[\u4e00-\u9fff]{2,8}$")

# ── Phase 2 Enhancement: Additional noise patterns ───────────────────────────
_WATERMARK_RE = re.compile(
    r"^(?:confidential|draft|internal|"
    r"\u5185\u90e8|\u673a\u5bc6|\u4ec5\u4f9b\u53c2\u8003|\u4fdd\u5bc6|"
    r"\u8349\u7a3f|\u5f85\u5ba1|\u672a\u5b9a\u7a3f)$",
    re.IGNORECASE,
)
_PAGE_NUMBER_RE = re.compile(
    r"^(?:"
    r"-\s*\d+\s*-"
    r"|page\s+\d+"
    r"|\u7b2c\s*\d+\s*\u9875"
    r"|\d+\s*/\s*\d+"
    r"|\d+\s+of\s+\d+"
    r")$",
    re.IGNORECASE,
)
_DECORATIVE_LINE_RE = re.compile(r"^[\s\-=_~*\u25a0\u25b2\u25cf\u25c6\u25cb\u25b3\u25c7\u2605\u2606\u2022\u00b7]{3,}$")
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
_FILE_PATH_RE = re.compile(r"^(?:[A-Z]:\\|/(?:usr|home|var|etc|opt|tmp)/)", re.IGNORECASE)
_COPYRIGHT_RE = re.compile(r"^[\u00a9\xc2]|^copyright\s|^\u7248\u6743|^all\s+rights\s+reserved", re.IGNORECASE)
_STANDALONE_NOISE_RE = re.compile(
    r"^(?:"
    r"-\s*\d+\s*-"
    r"|page\s+\d+"
    r"|\u7b2c\s*\d+\s*\u9875"
    r"|\d+\s*/\s*\d+"
    r"|\d+\s+of\s+\d+"
    r")$",
    re.IGNORECASE,
)
_REPEATED_DECORATIVE_MAX_LEN = 40
_REPEATED_DECORATIVE_MIN_COUNT = 3
_MD_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
_PURE_DASH_LINE_RE = re.compile(r"^\s*-{5,}\s*$")


def _normalise_repeated_noise_line(line: str) -> str:
    line = re.sub(r"^#+\s*", "", line)
    line = re.sub(r"\s+", " ", line)
    return line.strip()


def detect_and_remove_repeated_decorative_lines(lines: list) -> tuple:
    """
    Remove globally repeated decorative/noise lines.

    This complements Method B (position+frequency) for cases where OCR/output
    order causes noise lines to escape top/bottom zone detection.
    """
    candidates = []
    for raw in lines:
        text = _normalise_repeated_noise_line(raw)
        if not text:
            continue
        if len(text) > _REPEATED_DECORATIVE_MAX_LEN:
            continue
        if (
            _STANDALONE_NOISE_RE.match(text)
            or _DECORATIVE_LINE_RE.match(text)
            or _WATERMARK_RE.match(text)
            or _COPYRIGHT_RE.match(text)
            or _URL_RE.match(text)
        ):
            candidates.append(text.lower())

    counter = Counter(candidates)
    repeated_noise = {text for text, count in counter.items() if count >= _REPEATED_DECORATIVE_MIN_COUNT}

    if repeated_noise:
        print(
            f"[preprocess] Repeated decorative lines removed: {len(repeated_noise)} "
            f"(min_count={_REPEATED_DECORATIVE_MIN_COUNT})"
        )

    cleaned = []
    for raw in lines:
        text = _normalise_repeated_noise_line(raw).lower()
        if text in repeated_noise:
            cleaned.append("")
        else:
            cleaned.append(raw)
    return cleaned, repeated_noise


def _nearest_non_empty_line(lines: list, start_idx: int, step: int) -> str:
    i = start_idx + step
    while 0 <= i < len(lines):
        stripped = lines[i].strip()
        if stripped:
            return stripped
        i += step
    return ""


def _is_table_row_candidate(text: str) -> bool:
    return text.count("|") >= 2 and not text.startswith("#")


def detect_and_remove_table_separator_lines(lines: list) -> tuple:
    """
    Remove markdown table separator rows from content.

    Why:
    - Docling/OCR occasionally emits extra separator rows inside table bodies
      (e.g. "|-----|-----|"), which later appear as noisy "-----" lines in map nodes.
    - Markmap does not need those separator rows to show table text content.
    """
    cleaned = []
    removed = 0

    for idx, raw in enumerate(lines):
        stripped = raw.strip()
        if not stripped:
            cleaned.append(raw)
            continue

        if _MD_TABLE_SEPARATOR_RE.match(stripped):
            removed += 1
            continue

        # OCR may occasionally drop pipe characters and leave a pure dash line
        # between table rows. Remove only in obvious table context.
        if _PURE_DASH_LINE_RE.match(stripped):
            prev_text = _nearest_non_empty_line(lines, idx, -1)
            next_text = _nearest_non_empty_line(lines, idx, 1)
            if _is_table_row_candidate(prev_text) or _is_table_row_candidate(next_text):
                removed += 1
                continue

        cleaned.append(raw)

    return cleaned, removed


def _normalize_heading_topic(topic: str) -> str:
    """
    Recover likely heading text from OCR line-noise.
    Example: "7174811.2. 内存管理" -> "11.2. 内存管理"
    """
    topic = topic.strip()
    for pattern in (_LONG_DIGIT_PREFIX_2_RE, _LONG_DIGIT_PREFIX_1_RE):
        m = pattern.match(topic)
        if m:
            topic = m.group(1).strip()
            break
    return topic


def _has_structured_prefix(topic: str) -> bool:
    return bool(
        _STRICT_NUMERIC_RE.match(topic)
        or re.match(
            r"^\u7b2c[\u96f6\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\d]+"
            r"[\u7ae0\u8282\u7bc7\u90e8]",
            topic,
        )
        or re.match(r"^(?:Chapter|Section|Part|Appendix)\s+[\dIVXivx]+", topic, re.IGNORECASE)
        or re.match(r"^Q\d+\s*[：:。\s]", topic, re.IGNORECASE)
    )


def _extract_numeric_segments(topic: str):
    m = _STRICT_NUMERIC_RE.match(topic)
    if not m:
        return None
    parts = []
    for seg in m.group(1).split("."):
        if not seg:
            continue
        try:
            parts.append(int(seg))
        except ValueError:
            return None
    return tuple(parts) if parts else None


def _is_weak_unstructured_heading(topic: str) -> bool:
    """
    Identify low-confidence heading text that often comes from OCR/body fragments.

    Important: this is only used with context checks (sandwiched between related
    numbered headings), to avoid over-filtering real short titles.
    """
    if _has_structured_prefix(topic):
        return False

    normalized = re.sub(r"\s+", " ", topic).strip()

    if _WEAK_END_PUNCT_RE.search(normalized):
        return True

    if _WEAK_OPERATOR_PHRASE_RE.search(normalized):
        return True

    if _WEAK_SHORT_PAREN_TERM_RE.match(normalized):
        return True

    if _WEAK_TWO_TOKEN_CN_RE.match(normalized):
        return True

    return False


def _should_demote_bridge_heading(heading_meta: list, pos: int) -> bool:
    """
    Demote weak unstructured headings that are between related numeric headings.

    Example:
      11.2. 内存管理
      段号 + 段内地址。      <- demote to content
      11.2.2. 虚拟内存
    """
    current = heading_meta[pos]
    if not current.get("valid"):
        return False
    if current.get("numeric") is not None:
        return False
    if not _is_weak_unstructured_heading(current.get("topic", "")):
        return False

    next_meta = None
    for i in range(pos + 1, len(heading_meta)):
        if heading_meta[i].get("valid") and heading_meta[i].get("numeric") is not None:
            next_meta = heading_meta[i]
            break

    if not next_meta:
        return False

    next_num = next_meta.get("numeric")
    if next_num is None:
        return False

    prev_numeric_meta = None
    for i in range(pos - 1, -1, -1):
        if heading_meta[i].get("valid") and heading_meta[i].get("numeric") is not None:
            prev_numeric_meta = heading_meta[i]
            break

    # Find nearest previous numeric heading that can serve as ancestor anchor
    # of next_num (not necessarily the immediate previous heading).
    anchor_num = None
    for i in range(pos - 1, -1, -1):
        if not heading_meta[i].get("valid"):
            continue
        candidate = heading_meta[i].get("numeric")
        if candidate is None:
            continue
        if len(candidate) < len(next_num) and next_num[: len(candidate)] == candidate:
            anchor_num = candidate
            break

    # Cross-chapter fallback:
    # Sometimes OCR emits a short glue phrase between chapter N and chapter N+1.
    # Example:
    #   12.11. 数据分片
    #   分片类型 定义与条件
    #   13. 信息安全
    # Demote only when signals are strong and conservative.
    if anchor_num is None and prev_numeric_meta is not None:
        prev_num = prev_numeric_meta.get("numeric")
        if (
            isinstance(prev_num, tuple)
            and len(prev_num) >= 2
            and len(next_num) == 1
            and prev_num[0] != next_num[0]
            and current.get("level", 0) < prev_numeric_meta.get("level", 0)
            and current.get("level", 0) <= next_meta.get("level", 0)
        ):
            return True

    if anchor_num is None:
        return False

    # Keep demotion conservative: current weak heading should not be deeper than
    # the next numeric heading; it often appears as an OCR bridge line.
    if current.get("level", 0) > next_meta.get("level", 0):
        return False

    return True


def is_valid_heading(topic: str) -> bool:
    """
    Heuristic filter: decide whether a Markdown heading line is a genuine
    section title or body text that Docling mis-labelled as a heading.
    """
    topic = _normalize_heading_topic(topic)

    if not topic:
        return False

    if len(topic) > _MAX_HEADING_LENGTH:
        return False

    if _PURE_SYMBOL_RE.match(topic):
        return False

    if _PURE_DIGIT_RE.match(topic):
        return False

    if len(topic) == 1 and re.match(r"[\u4e00-\u9fffA-Za-z0-9]", topic):
        return False

    if _SHORT_GARBAGE_TOKEN_RE.match(topic):
        return False

    if _DIAGRAM_LABEL_RE.match(topic):
        return False

    if topic in {"年", "月", "日"}:
        return False

    if _BODY_TEXT_STARTERS.match(topic):
        return False

    if _LIST_ITEM_RE.match(topic):
        return False

    has_structured_prefix = _has_structured_prefix(topic)
    if _SENTENCE_PUNCT_RE.search(topic) and not has_structured_prefix:
        if len(topic) >= 18 or len(_SENTENCE_PUNCT_RE.findall(topic)) >= 2:
            return False

    if _FORMULA_PATTERNS.search(topic):
        if not has_structured_prefix:
            return False

    # ── Phase 2: Additional noise filters ────────────────────────────────────
    if _WATERMARK_RE.match(topic):
        return False

    if _PAGE_NUMBER_RE.match(topic):
        return False

    if _DECORATIVE_LINE_RE.match(topic):
        return False

    if _URL_RE.match(topic):
        return False

    if _FILE_PATH_RE.match(topic):
        return False

    if _COPYRIGHT_RE.match(topic):
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
        segments = numeric_match.group(1).split(".")
        depth = len([s for s in segments if s])
        return depth

    if re.match(
        r"^\u7b2c[\u96f6\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\d]+"
        r"[\u7ae0\u8282\u7bc7\u90e8]",
        topic,
    ):
        return 1

    if re.match(r"^(?:Chapter|Section|Part|Appendix)\s+[\dIVXivx]+", topic, re.IGNORECASE):
        return 1

    # Enhancement 4: Q-series FAQ headings
    if re.match(r"^Q\d+\s*[：:。\s]", topic, re.IGNORECASE):
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
    lines = text.split("\n")

    # ── Pass 0: Remove standalone noise lines (page numbers, watermarks,
    #    decorative dividers) that are NOT headings but pollute content ────────
    cleaned_lines = []
    noise_removed = 0
    for line in lines:
        stripped = line.strip()
        # Skip heading lines — they are handled by is_valid_heading later
        if stripped.startswith("#"):
            cleaned_lines.append(line)
            continue
        # Remove standalone noise
        if stripped and (
            _STANDALONE_NOISE_RE.match(stripped)
            or _WATERMARK_RE.match(stripped)
            or _DECORATIVE_LINE_RE.match(stripped)
            or _COPYRIGHT_RE.match(stripped)
        ):
            noise_removed += 1
            continue
        cleaned_lines.append(line)
    lines = cleaned_lines
    if noise_removed:
        print(f"[preprocess] Removed {noise_removed} standalone noise lines")

    # ── Pass 0.5: remove markdown table separator noise ──────────────────────
    lines, table_sep_removed = detect_and_remove_table_separator_lines(lines)
    if table_sep_removed:
        print(f"[preprocess] Removed {table_sep_removed} table separator line(s)")

    # ── Pass 1: frequency+position-based header/footer removal ───────────────
    lines, _hf_fps = detect_and_remove_headers_footers(lines)

    # ── Pass 1.5: remove globally repeated decorative lines ───────────────────
    lines, _rep_noise = detect_and_remove_repeated_decorative_lines(lines)

    # ── Pass 2: TOC region detection and heading demotion ────────────────────
    toc_start, toc_end = _detect_toc_region(lines)
    if toc_start >= 0:
        print(f"[preprocess] TOC detected at lines {toc_start}–{toc_end}")
        for i in range(toc_start, toc_end + 1):
            m = re.match(r"^(#+)\s+(.*)", lines[i])
            if m:
                lines[i] = m.group(2)

    # ── Pass 3: split-heading merge ───────────────────────────────────────────
    merged = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if _is_split_heading(line):
            hash_match = re.match(r"^\s*(#+)", line)
            if not hash_match:
                merged.append(line)
                i += 1
                continue
            hashes = hash_match.group(1)
            label = re.sub(r"^\s*#+\s*", "", line).strip()

            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1

            if j < len(lines):
                next_line = lines[j].strip()
                next_text = re.sub(r"^#+\s*", "", next_line).strip()
                if next_text:
                    merged.append(f"{hashes} {label}{next_text}")
                    i = j + 1
                    continue

        merged.append(line)
        i += 1
    lines = merged

    return "\n".join(lines)


# ── Tree data structures ──────────────────────────────────────────────────────


class TreeNode:
    def __init__(self, topic, level, parent=None):
        self.id = ""
        self.topic = topic
        self.level = level
        self.content_lines = []
        self.children = []
        self.ai_details = []
        self.parent = parent
        self.source_line_start = 0
        self.source_line_end = 0
        self.pdf_page_no = None
        self.pdf_y_ratio = None

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
            "id": self.id,
            "topic": self.topic,
            "level": self.level,
            "source_line_start": self.source_line_start,
            "source_line_end": self.source_line_end,
            "pdf_page_no": self.pdf_page_no,
            "pdf_y_ratio": self.pdf_y_ratio,
            "content_length": len(self.full_content),
            "children": [child.to_dict() for child in self.children],
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
    lines = markdown_text.split("\n")

    root = TreeNode("Root", 0)
    root.id = "root"
    root.source_line_start = 1
    stack = [root]

    # Pre-scan for numeric inference threshold
    raw_header_topics = []
    valid_header_topics = []
    heading_meta = []
    heading_pos_by_line_index = {}
    for line_index, line in enumerate(lines):
        m = re.match(r"^(#+)\s+(.*)", line)
        if not m:
            continue

        raw_topic = m.group(2).strip()
        anchor_match = _FM_ANCHOR_RE.search(raw_topic)
        anchor_data = None
        if anchor_match:
            try:
                anchor_data = json.loads(_anchor_payload_from_match(anchor_match))
            except Exception:
                pass
            raw_topic = (raw_topic[: anchor_match.start()] + raw_topic[anchor_match.end() :]).strip()

        topic = _normalize_heading_topic(raw_topic)
        markdown_level = len(m.group(1))
        valid = is_valid_heading(topic)
        numeric = _extract_numeric_segments(topic) if valid else None

        raw_header_topics.append(topic)
        if valid:
            valid_header_topics.append(topic)

        heading_pos_by_line_index[line_index] = len(heading_meta)
        heading_meta.append(
            {"topic": topic, "level": markdown_level, "valid": valid, "numeric": numeric, "anchor_data": anchor_data}
        )

    numbered_count = sum(
        1
        for topic in valid_header_topics
        if re.match(
            r"^(?:"
            r"\d+(?:\.\d+)*\.?\s*(?=[a-zA-Z\u4e00-\u9fff\uff08\u3010\[（【])"
            r"|\u7b2c[\u96f6\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\d]+[\u7ae0\u8282\u7bc7\u90e8]"
            r"|(?:Chapter|Section|Part|Appendix)\s+[\dIVXivx]+"
            r"|Q\d+\s*[：:。\s]"
            r")",
            topic,
            re.IGNORECASE,
        )
    )
    use_numbering_inference = len(valid_header_topics) > 0 and (numbered_count / len(valid_header_topics)) >= 0.5

    total_raw = len(raw_header_topics)
    total_valid = len(valid_header_topics)
    demoted = total_raw - total_valid
    print(
        f"[build_hierarchy_tree] Raw headings: {total_raw}, "
        f"Valid: {total_valid}, Demoted: {demoted}, "
        f"Numbered: {numbered_count} → "
        f"{'Numeric inference ON' if use_numbering_inference else 'Markdown # count mode'}"
    )

    for line_index, line in enumerate(lines):
        header_match = re.match(r"^(#+)\s+(.*)", line)

        if header_match:
            raw_topic = header_match.group(2).strip()
            anchor_match = _FM_ANCHOR_RE.search(raw_topic)
            if anchor_match:
                raw_topic = (raw_topic[: anchor_match.start()] + raw_topic[anchor_match.end() :]).strip()

            markdown_level = len(header_match.group(1))
            topic = _normalize_heading_topic(raw_topic.strip())

            if not is_valid_heading(topic):
                if topic:
                    stack[-1].content_lines.append(topic)
                    stack[-1].source_line_end = max(stack[-1].source_line_end, line_index + 1)
                continue

            heading_pos = heading_pos_by_line_index.get(line_index)
            if heading_pos is not None and _should_demote_bridge_heading(heading_meta, heading_pos):
                stack[-1].content_lines.append(topic)
                stack[-1].source_line_end = max(stack[-1].source_line_end, line_index + 1)
                continue

            if use_numbering_inference:
                level = infer_level_from_numbering(topic, markdown_level)
            else:
                level = markdown_level

            new_node = TreeNode(topic, level)
            new_node.source_line_start = line_index + 1
            new_node.source_line_end = line_index + 1

            while len(stack) > 1 and stack[-1].level >= level:
                finished = stack.pop()
                finished.source_line_end = max(finished.source_line_end, line_index)

            # Assign anchor to new node if available
            heading_pos = heading_pos_by_line_index.get(line_index)
            if heading_pos is not None:
                meta = heading_meta[heading_pos]
                if meta.get("anchor_data"):
                    anchor = meta["anchor_data"]
                    new_node.pdf_page_no = anchor.get("page_no")
                    bbox = anchor.get("bbox")
                    page_height = anchor.get("page_height", 1000)
                    if bbox and page_height:
                        origin = str(bbox.get("coord_origin", "BOTTOM_LEFT")).upper()
                        t_coord = float(bbox.get("t", bbox.get("top", 0)))
                        y_ratio = (
                            (1.0 - (t_coord / float(page_height)))
                            if origin == "BOTTOM_LEFT"
                            else (t_coord / float(page_height))
                        )
                        new_node.pdf_y_ratio = round(max(0.0, min(1.0, float(y_ratio))), 4)

            stack[-1].add_child(new_node)
            stack.append(new_node)

        else:
            line = line.strip()
            # remove anchor tag from content lines
            anchor_match = _FM_ANCHOR_RE.search(line)
            while anchor_match:
                if not getattr(stack[-1], "pdf_page_no", None):
                    try:
                        anchor = json.loads(_anchor_payload_from_match(anchor_match))
                        stack[-1].pdf_page_no = anchor.get("page_no")
                        bbox = anchor.get("bbox")
                        page_height = anchor.get("page_height", 1000)
                        if bbox and page_height:
                            origin = str(bbox.get("coord_origin", "BOTTOM_LEFT")).upper()
                            t_coord = float(bbox.get("t", bbox.get("top", 0)))
                            y_ratio = (
                                (1.0 - (t_coord / float(page_height)))
                                if origin == "BOTTOM_LEFT"
                                else (t_coord / float(page_height))
                            )
                            stack[-1].pdf_y_ratio = round(max(0.0, min(1.0, float(y_ratio))), 4)
                    except Exception:
                        pass

                line = (line[: anchor_match.start()] + line[anchor_match.end() :]).strip()
                anchor_match = _FM_ANCHOR_RE.search(line)

            if line:
                stack[-1].content_lines.append(line)
                stack[-1].source_line_end = max(stack[-1].source_line_end, line_index + 1)

    total_lines = len(lines)
    while len(stack) > 1:
        finished = stack.pop()
        finished.source_line_end = max(finished.source_line_end, total_lines)
    root.source_line_end = max(root.source_line_end, total_lines)

    return root


def assign_stable_node_ids(root: TreeNode, file_id: str = ""):
    """
    Assign deterministic node ids so frontend click mapping remains stable
    across reloads and restarts for the same parsed structure.
    """
    root.id = "root"

    def walk(parent: TreeNode, path: list):
        for sibling_index, child in enumerate(parent.children):
            new_path = path + [child.topic]
            key = f"{file_id}|{' > '.join(new_path)}|{sibling_index}|{child.source_line_start}|{child.source_line_end}"
            digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
            child.id = f"n_{digest}"
            walk(child, new_path)

    walk(root, [])


def flatten_tree_nodes(root: TreeNode) -> list:
    """Return pre-order flattened list (excluding root)."""
    flattened = []

    def walk(node: TreeNode):
        for child in node.children:
            flattened.append(child)
            walk(child)

    walk(root)
    return flattened


# ── Export helper ─────────────────────────────────────────────────────────────


def tree_to_markdown(node, depth=0):
    """Recursively export the tree as Markdown."""
    lines = []

    if node.level > 0:
        lines.append(f"{'#' * node.level} {node.topic}")

    if node.ai_details:
        for item in node.ai_details:
            lines.append(f"- **{item.get('topic', '')}**")
            for det in item.get("details", []):
                lines.append(f"  - {det}")
    elif node.content_lines:
        # 修复：如果没有 AI 细节（处理失败或节点不需要处理），保留原始正文
        content = node.full_content
        if content:
            lines.append(content)

    if node.children:
        lines.append("")
        for child in node.children:
            result = tree_to_markdown(child, depth + 1)
            if result:
                lines.append(result)

    return "\n".join(lines).strip()

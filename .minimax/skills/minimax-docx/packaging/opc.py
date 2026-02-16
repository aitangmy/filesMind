"""
OPC Archive Assembly

Implements Open Packaging Conventions according to ECMA-376 Part 2.
Orders package parts based on content type semantics rather than path heuristics.

The [Content_Types].xml manifest drives part classification, ensuring archive
structure reflects the semantic role of each component in the document.

See: ECMA-376-2:2016, Section 10 (Physical Package)
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from typing import Callable


_CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"


class ContentTypeManifest:
    """Interprets the [Content_Types].xml manifest.

    Provides content type resolution for package parts by examining both
    default extension mappings and explicit part overrides.
    """

    def __init__(self, content_types_xml: str | bytes | None = None):
        self._defaults: dict[str, str] = {}
        self._overrides: dict[str, str] = {}

        if content_types_xml:
            self._parse(content_types_xml)

    def _parse(self, xml_content: str | bytes) -> None:
        """Extract content type mappings from the manifest XML."""
        try:
            root = ET.fromstring(xml_content if isinstance(xml_content, bytes)
                                 else xml_content.encode("utf-8"))
            for child in root:
                tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if tag == "Default":
                    ext = child.get("Extension", "").lower()
                    ct = child.get("ContentType", "")
                    if ext:
                        self._defaults[ext] = ct
                elif tag == "Override":
                    part = child.get("PartName", "")
                    ct = child.get("ContentType", "")
                    if part:
                        self._overrides[part.lstrip("/")] = ct
        except ET.ParseError:
            return

    def get_content_type(self, part_name: str) -> str:
        """Resolve the content type for a given part.

        Args:
            part_name: Path within the package

        Returns:
            Content type string, or 'application/octet-stream' as fallback
        """
        normalized = part_name.lstrip("/")
        if normalized in self._overrides:
            return self._overrides[normalized]
        ext = Path(normalized).suffix.lstrip(".").lower()
        return self._defaults.get(ext, "application/octet-stream")


class OPCPartClassifier:
    """Assigns semantic categories to package parts.

    Classification is based on content type analysis rather than filesystem
    path patterns, following the OPC specification's content-type-first approach.
    """

    _CONTENT_TYPE_CATEGORIES = {
        "application/vnd.openxmlformats-package.relationships+xml": "relationships",
        "application/vnd.openxmlformats-package.core-properties+xml": "metadata",
        "application/vnd.openxmlformats-officedocument.extended-properties+xml": "metadata",
        "application/vnd.openxmlformats-officedocument.custom-properties+xml": "metadata",

        "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml": "main_document",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml": "definitions",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml": "definitions",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml": "definitions",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml": "definitions",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.webSettings+xml": "definitions",

        "application/vnd.openxmlformats-officedocument.theme+xml": "theming",

        "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml": "page_layout",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml": "page_layout",

        "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml": "annotations",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml": "annotations",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.endnotes+xml": "annotations",

        "image/png": "media",
        "image/jpeg": "media",
        "image/gif": "media",
        "image/tiff": "media",
        "image/x-emf": "media",
        "image/x-wmf": "media",
    }

    _CATEGORY_ORDER = {
        "manifest": 0,
        "relationships": 1,
        "metadata": 2,
        "main_document": 3,
        "definitions": 4,
        "theming": 5,
        "page_layout": 6,
        "annotations": 7,
        "media": 8,
        "unknown": 9,
    }

    def __init__(self, manifest: ContentTypeManifest | None = None):
        self._manifest = manifest or ContentTypeManifest()

    def classify(self, part_name: str) -> str:
        """Determine the semantic category of a part.

        Args:
            part_name: Path within the package

        Returns:
            Category identifier string
        """
        if part_name == "[Content_Types].xml":
            return "manifest"
        if part_name.endswith(".rels"):
            return "relationships"

        ct = self._manifest.get_content_type(part_name)
        return self._CONTENT_TYPE_CATEGORIES.get(ct, "unknown")

    def sort_key(self, part_name: str) -> tuple[int, int, str]:
        """Generate a sorting key for archive ordering.

        Sorting criteria (in priority order):
        1. Semantic category (manifest first, media last)
        2. Relationship nesting depth (root before nested)
        3. Alphabetical path (for stable ordering)
        """
        category = self.classify(part_name)
        order = self._CATEGORY_ORDER.get(category, 99)

        rel_depth = part_name.count("/") if category == "relationships" else 0

        return (order, rel_depth, part_name)


class OPCPackager:
    """Assembles OPC-compliant archives with semantic part ordering."""

    def repackage(self, source_dir: Path, output_path: Path) -> None:
        """Rebuild a .docx from an extracted directory.

        Reads the content type manifest to determine proper part ordering,
        then creates a new archive with parts arranged semantically.

        Args:
            source_dir: Directory containing extracted package contents
            output_path: Destination path for the new .docx file
        """
        ct_path = source_dir / "[Content_Types].xml"
        manifest = None
        if ct_path.exists():
            manifest = ContentTypeManifest(ct_path.read_bytes())

        classifier = OPCPartClassifier(manifest)

        all_files = [f for f in source_dir.rglob("*") if f.is_file()]
        sorted_files = sorted(
            all_files,
            key=lambda f: classifier.sort_key(str(f.relative_to(source_dir)))
        )

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as arc:
            for fpath in sorted_files:
                arc.write(fpath, fpath.relative_to(source_dir))

    def create_package(
        self,
        output_path: Path,
        content_provider: Callable[[str], bytes | None],
        manifest: list[str],
    ) -> None:
        """Build a new .docx from a content callback.

        Used when creating packages from scratch where no existing
        content type manifest is available. Falls back to heuristic ordering.

        Args:
            output_path: Destination path for the new .docx
            content_provider: Callback that returns content bytes for each part
            manifest: List of part paths to include in the package
        """
        classifier = OPCPartClassifier()
        sorted_manifest = sorted(manifest, key=classifier.sort_key)

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as arc:
            for path in sorted_manifest:
                content = content_provider(path)
                if content is not None:
                    arc.writestr(path, content)

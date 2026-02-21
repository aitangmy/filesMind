from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict

from parser_service import process_pdf_safely


@dataclass(slots=True)
class ParsePdfInput:
    doc_id: str
    file_path: str
    output_dir: str


@dataclass(slots=True)
class ParsePdfOutput:
    markdown: str
    image_map: Dict[str, Any]


class ParsePdfActivity:
    async def run(self, payload: ParsePdfInput) -> ParsePdfOutput:
        md_content, image_map = await asyncio.to_thread(
            process_pdf_safely,
            payload.file_path,
            payload.output_dir,
            payload.doc_id,
        )
        if not md_content or not str(md_content).strip():
            raise RuntimeError("PDF parsing produced empty markdown")
        return ParsePdfOutput(markdown=md_content, image_map=image_map or {})

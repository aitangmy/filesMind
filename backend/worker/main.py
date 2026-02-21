"""Worker bootstrap for local workflow execution.

Temporal runtime wiring will replace this entrypoint in the final deployment.
"""

from __future__ import annotations

import argparse
import asyncio
import os

from workflows.document_workflow import DocumentWorkflow
from workflow_contracts.models import WorkflowInput


async def _run_once(args: argparse.Namespace) -> None:
    wf = DocumentWorkflow()
    result = await wf.run(
        WorkflowInput(
            doc_id=args.doc_id,
            filename=args.filename,
            file_path=args.file_path,
            file_hash=args.file_hash,
            parser_backend=args.parser_backend,
            model_profile=args.model_profile,
            runtime_config={},
        )
    )
    print(f"doc_id={result.doc_id} status={result.status.value} markdown={result.summary.markdown_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one document workflow")
    parser.add_argument("--doc-id", required=True)
    parser.add_argument("--filename", required=True)
    parser.add_argument("--file-path", required=True)
    parser.add_argument("--file-hash", required=True)
    parser.add_argument("--parser-backend", default=os.getenv("PARSER_BACKEND", "docling"))
    parser.add_argument("--model-profile", default="default")
    args = parser.parse_args()
    asyncio.run(_run_once(args))


if __name__ == "__main__":
    main()

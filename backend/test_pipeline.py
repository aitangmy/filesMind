import asyncio
import os
from unittest.mock import MagicMock, patch, AsyncMock
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from cognitive_engine import generate_mindmap_structure

async def _test_pipeline_logic():
    print("Testing Pipeline Logic...")
    
    # Mock Data
    dummy_chunks = ["## Section 1\nContent 1", "## Section 2\nContent 2"]
    
    # Mock Cognitive Engine Response
    # Response for chunks
    mock_chunk_response = MagicMock()
    mock_chunk_response.choices[0].message.content = "### Subnode 1\n- Detail"

    # Response for root summary (Reduce phase)
    mock_root_response = MagicMock()
    mock_root_response.choices[0].message.content = "## Section 1"

    # Patch get_client to return our mock client
    with patch('cognitive_engine.get_client') as mock_get_client:
        mock_client = AsyncMock()
        # side_effect allows different responses for different calls
        # 1. summarize_chunk (2 times)
        # 2. generate_root_summary (1 time)
        mock_client.chat.completions.create.side_effect = [
            mock_chunk_response, 
            mock_chunk_response, 
            mock_root_response
        ]
        mock_get_client.return_value = mock_client
        
        print("Running generate_mindmap_structure...")
        result = await generate_mindmap_structure(dummy_chunks)
        
        print("\n--- Result ---")
        print(result)
        
        if "### Subnode 1" in result and "## Section 1" in result:
            print("\nSUCCESS: Deep hierarchy verified.")
        else:
            print("\nFAILURE: Hierarchy lost or flattened.")

async def _test_generated_files():
    print("\n\nTesting Generated Files...")
    test_files = [
        "test_docs/doc_shallow.md",
        "test_docs/doc_deep.md",
        "test_docs/doc_mixed.md"
    ]
    
    for file_path in test_files:
        if not os.path.exists(file_path):
            print(f"Skipping {file_path} (not found)")
            continue
            
        print(f"\nProcessing {file_path}...")
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Simulate chunks (split by lines for simplicity in this test)
        lines = content.split('\n')
        chunks = []
        current_chunk = []
        for line in lines:
            if line.startswith("#"):
                if current_chunk:
                    chunks.append("\n".join(current_chunk))
                current_chunk = [line]
            else:
                current_chunk.append(line)
        if current_chunk:
            chunks.append("\n".join(current_chunk))
            
        # Mock Response: Echo the hierarchy structure
        # We need a dynamic side_effect that returns content based on input
        # But for verification, we just want to see if the pipeline PRESERVES the '#' levels
        # So we mock the AI to return the input text basically unchanged (as if it summarized perfectly)
        
        async def mock_create_side_effect(*args, **kwargs):
            messages = kwargs.get('messages', [])
            user_content = messages[-1]['content']
            # Extract text content from user prompt (updated to match new Chinese prompt)
            start_marker = "【原文内容】：\n"
            start_index = user_content.find(start_marker)
            if start_index != -1:
                input_text = user_content[start_index + len(start_marker):]
                # Simulate AI preserving headers
                return MagicMock(choices=[MagicMock(message=MagicMock(content=input_text))])
            return MagicMock(choices=[MagicMock(message=MagicMock(content="# Summary"))])

        with patch('cognitive_engine.get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.chat.completions.create.side_effect = mock_create_side_effect
            mock_get_client.return_value = mock_client
            
            result = await generate_mindmap_structure(chunks)
            
            # Verification: Check if diverse headers exist
            h2_count = result.count("## ")
            h3_count = result.count("### ")
            h4_count = result.count("#### ")
            print(f"  Result Stats: H2={h2_count}, H3={h3_count}, H4={h4_count}")
            
            if "doc_deep.md" in file_path:
                if h4_count > 0:
                    print("  SUCCESS: Deep hierarchy (H4) preserved.")
                else:
                    print("  FAILURE: Deep hierarchy lost.")

def test_pipeline_logic_sync():
    asyncio.run(_test_pipeline_logic())

def test_generated_files_sync():
    asyncio.run(_test_generated_files())

if __name__ == "__main__":
    asyncio.run(_test_pipeline_logic())
    asyncio.run(_test_generated_files())

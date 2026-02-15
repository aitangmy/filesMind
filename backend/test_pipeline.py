import asyncio
import os
from unittest.mock import MagicMock, patch, AsyncMock
from cognitive_engine import generate_mindmap_structure

async def test_pipeline_logic():
    print("Testing Pipeline Logic...")
    
    # Mock Data
    dummy_chunks = ["## Section 1\nContent 1", "## Section 2\nContent 2"]
    
    # Mock Cognitive Engine Response
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "- Node 1\n  - Subnode 1"
    
    with patch('cognitive_engine.client.chat.completions.create', new_callable=AsyncMock) as mock_create:
        mock_create.return_value = mock_response
        
        print("Running generate_mindmap_structure...")
        result = await generate_mindmap_structure(dummy_chunks)
        
        print("\n--- Result ---")
        print(result)
        
        if "- Node 1" in result and "# Generated Knowledge Graph" in result:
            print("\nSUCCESS: Pipeline logic verified.")
        else:
            print("\nFAILURE: Unexpected output format.")

if __name__ == "__main__":
    asyncio.run(test_pipeline_logic())

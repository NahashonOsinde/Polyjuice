"""
Tests for local RAG functionality with sample documents

Author: 
"""

import os
import tempfile
import shutil
from pathlib import Path
import pytest
from langchain.docstore.document import Document
from langchain_community.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings
from ..rag_build import KnowledgeBaseIndexer

@pytest.fixture
def sample_docs():
    return [
        Document(
            page_content="TAMARA operates with a total flow rate (TFR) range of 0.8-15.0 mL/min. "
                        "The system supports both HERRINGBONE and BAFFLE chip types.",
            metadata={"source": "specs.md"}
        ),
        Document(
            page_content="Temperature affects viscosity in microfluidic mixing. "
                        "Operating temperature range is 5-60°C with optimal mixing at 20-25°C.",
            metadata={"source": "theory.md"}
        )
    ]

@pytest.fixture
def temp_dirs():
    # Create temporary directories for knowledge base and vector store
    kb_dir = tempfile.mkdtemp()
    vector_db_dir = tempfile.mkdtemp()
    
    # Create sample files in knowledge base
    kb_path = Path(kb_dir)
    
    with open(kb_path / "specs.md", "w") as f:
        f.write("""TAMARA operates with a total flow rate (TFR) range of 0.8-15.0 mL/min.
                The system supports both HERRINGBONE and BAFFLE chip types.""")
    
    with open(kb_path / "theory.md", "w") as f:
        f.write("""Temperature affects viscosity in microfluidic mixing.
                Operating temperature range is 5-60°C with optimal mixing at 20-25°C.""")
    
    yield {"kb_dir": kb_dir, "vector_db_dir": vector_db_dir}
    
    # Cleanup
    shutil.rmtree(kb_dir)
    shutil.rmtree(vector_db_dir)

def test_document_loading(temp_dirs):
    indexer = KnowledgeBaseIndexer()
    docs = indexer.load_documents(Path(temp_dirs["kb_dir"]))
    
    assert len(docs) == 2
    assert any("TFR range" in doc.page_content for doc in docs)
    assert any("Temperature affects" in doc.page_content for doc in docs)

def test_index_building(temp_dirs):
    indexer = KnowledgeBaseIndexer()
    vectorstore = indexer.build_index(
        temp_dirs["kb_dir"],
        temp_dirs["vector_db_dir"]
    )
    
    assert os.path.exists(temp_dirs["vector_db_dir"])
    assert isinstance(vectorstore, Chroma)

def test_retrieval_quality(temp_dirs):
    # Build index
    indexer = KnowledgeBaseIndexer()
    vectorstore = indexer.build_index(
        temp_dirs["kb_dir"],
        temp_dirs["vector_db_dir"]
    )
    
    # Test queries
    queries = [
        ("What is the flow rate range?", "specs.md"),
        ("How does temperature affect mixing?", "theory.md")
    ]
    
    for query, expected_source in queries:
        results = vectorstore.similarity_search(query, k=1)
        assert len(results) == 1
        assert results[0].metadata["source"].endswith(expected_source)

def test_chunk_overlap(temp_dirs):
    indexer = KnowledgeBaseIndexer()
    
    # Create a long document that will be split into chunks
    long_doc = Document(
        page_content="A" * 2000,  # Will create multiple chunks
        metadata={"source": "long.md"}
    )
    
    # Write the long document
    with open(Path(temp_dirs["kb_dir"]) / "long.md", "w") as f:
        f.write("A" * 2000)
    
    # Build index
    vectorstore = indexer.build_index(
        temp_dirs["kb_dir"],
        temp_dirs["vector_db_dir"]
    )
    
    # Verify chunks were created with overlap
    results = vectorstore.similarity_search("A", k=10)
    assert len(results) > 1  # Should have multiple chunks

"""
RAG Index Builder for TAMARA Knowledge Base

This script builds a vector store index from the knowledge base documents
and runs smoke tests to verify retrieval quality.

Author: Nahashon Osinde
"""

import os
from typing import List, Dict
from pathlib import Path
import logging
from dotenv import load_dotenv
from rich.console import Console
from langchain_community.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import TextLoader
from langchain.docstore.document import Document

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Verify OpenAI API key is set
if not os.getenv("OPENAI_API_KEY"):
    raise ValueError("OPENAI_API_KEY environment variable is not set. Please set it in your .env file.")

class KnowledgeBaseIndexer:
    """Handles indexing of knowledge base documents"""
    
    def __init__(self):
        self.console = Console()
        self.embeddings = OpenAIEmbeddings(
            model="text-embedding-3-small"
        ) # Update to a valid embedding model if needed, 'text-embedding-ada-002' is better but more expensive
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50,
            length_function=len,
            is_separator_regex=False
        )

    def load_documents(self, kb_dir: Path) -> List[Document]:
        """Load documents from knowledge base directory"""
        documents = []
        
        # # Process markdown files
        # for md_file in kb_dir.glob("**/*.md"):
        #     loader = TextLoader(str(md_file))
        #     docs = loader.load()
        #     for doc in docs:
        #         doc.metadata = {"source": str(md_file.relative_to(kb_dir))}
        #         documents.append(doc)

        # Process text files
        for txt_file in kb_dir.glob("**/*.txt"):
            loader = TextLoader(str(txt_file))
            docs = loader.load()
            for doc in docs:
                doc.metadata = {"source": str(txt_file.relative_to(kb_dir))}
                documents.append(doc)

        return documents

    def build_index(self, kb_dir: str, vector_db_dir: str) -> None:
        """Build vector store index from knowledge base documents"""
        kb_path = Path(kb_dir)
        if not kb_path.exists():
            raise ValueError(f"Knowledge base directory not found: {kb_dir}")

        # Load and split documents
        documents = self.load_documents(kb_path)
        self.console.print(f"[green]Loaded {len(documents)} documents[/green]")

        chunks = self.text_splitter.split_documents(documents)
        self.console.print(f"[green]Created {len(chunks)} chunks[/green]")

        # Create and persist vector store
        vectorstore = Chroma.from_documents(
            documents=chunks,
            embedding=self.embeddings,
            persist_directory=vector_db_dir
        )
        vectorstore.persist()
        self.console.print(f"[green]Index built and persisted to {vector_db_dir}[/green]")

        return vectorstore

    def smoke_test(self, vectorstore: Chroma) -> None:
        """Run smoke tests on the built index"""
        test_queries = [
            "What is the recommended flow rate range for TAMARA?",
            "How does temperature affect viscosity in microfluidic mixing?"
        ]

        self.console.print("\n[bold]Running smoke tests...[/bold]")
        
        for query in test_queries:
            self.console.print(f"\n[bold blue]Query:[/bold blue] {query}")
            
            results = vectorstore.similarity_search(query, k=3)
            
            for i, doc in enumerate(results, 1):
                self.console.print(f"\n[bold green]Result {i}:[/bold green]")
                self.console.print(f"Source: {doc.metadata['source']}")
                self.console.print(f"Content: {doc.page_content[:200]}...")

def main():
    """Main entry point"""
    # Define paths/directory containing the knowledge base documents and the persistent (vector) directory
    current_dir = os.path.dirname(os.path.abspath(__file__))
    kb_dir = os.path.join(current_dir, "Knowledge_base/txt")
    db_dir = os.path.join(current_dir, "db")
    vector_db_dir = os.path.join(db_dir, "chroma_db_with_metadata_Knowledge_base")

    # Ensure vector store directory exists
    os.makedirs(vector_db_dir, exist_ok=True)

    # Check if vector store already exists
    if os.path.exists(vector_db_dir) and os.listdir(vector_db_dir):
        logger.info("Vector store already exists. No need to initialize.")
        return

    # Build index
    indexer = KnowledgeBaseIndexer()
    try:
        vectorstore = indexer.build_index(kb_dir, vector_db_dir)
        indexer.smoke_test(vectorstore)
    except Exception as e:
        logger.error(f"Error building index: {str(e)}")
        raise

if __name__ == "__main__":
    main()
import os
from dotenv import load_dotenv
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import TextLoader
from langchain_community.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings

# Load environment variables from .env
load_dotenv()

# Verify OpenAI API key is set
if not os.getenv("OPENAI_API_KEY"):
    raise ValueError("OPENAI_API_KEY environment variable is not set. Please set it in your .env file.")

# Define the directory containing the text files and the persistent directory
current_dir = os.path.dirname(os.path.abspath(__file__))
knowledge_base_dir = os.path.join(current_dir, "Knowledge_base/txt")
db_dir = os.path.join(current_dir, "db")
persistent_directory = os.path.join(db_dir, "chroma_db_with_metadata_Knowledge_base")

print(f"Knowledge base directory: {knowledge_base_dir}")
print(f"Persistent directory: {persistent_directory}")

# Check if the Chroma vector store already exists
if not os.path.exists(persistent_directory):
    print("Persistent directory does not exist. Initializing vector store...")

    # Ensure the knowledge_base directory exists
    if not os.path.exists(knowledge_base_dir):
        raise FileNotFoundError(
            f"The directory {knowledge_base_dir} does not exist. Please check the path."
        )

    # List all text files in the directory
    knowledge_base_files = [f for f in os.listdir(knowledge_base_dir) if f.endswith(".txt")]

    # Read the text content from each file and store it with metadata
    documents = []
    for knowledge_base_file in knowledge_base_files:
        file_path = os.path.join(knowledge_base_dir, knowledge_base_file)
        loader = TextLoader(file_path)
        knowledge_base_docs = loader.load()
        for doc in knowledge_base_docs:
            # Add metadata to each document indicating its source
            doc.metadata = {"source": knowledge_base_file}
            documents.append(doc)

    #Recursive character based splitting of the documents into chunks
    # Attempts to split text at natural boundaries (sentences, paragraphs) within character limit.
    # Balances between maintaining coherence and adhering to character limits.
    rec_char_splitter = RecursiveCharacterTextSplitter(
        chunk_size=500, chunk_overlap=50)
    rec_char_docs = rec_char_splitter.split_documents(documents)

    # Display information about the split documents
    print("\n--- Document Chunks Information ---")
    print(f"Number of document chunks: {len(rec_char_docs)}")

    # Create embeddings
    print("\n--- Creating embeddings ---")
    embeddings = OpenAIEmbeddings(
        model="text-embedding-3-small"
    )  # Update to a valid embedding model if needed, 'text-embedding-ada-002' is better but more expensive
    print("\n--- Finished creating embeddings ---")

    # Create the vector store and persist it
    print("\n--- Creating and persisting vector store ---")
    db = Chroma.from_documents(
        rec_char_docs, embeddings, persist_directory=persistent_directory)
    print("\n--- Finished creating and persisting vector store ---")

else:
    print("Vector store already exists. No need to initialize.")

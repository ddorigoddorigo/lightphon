"""
RAG (Retrieval-Augmented Generation) Manager
Handles document ingestion, embedding generation, and retrieval for local RAG.
Uses llama-server's /embedding endpoint for generating embeddings.
"""

import os
import json
import hashlib
import logging
import numpy as np
from typing import List, Dict, Tuple, Optional
from pathlib import Path
import httpx
import re

logger = logging.getLogger(__name__)

class RAGManager:
    """Manages RAG operations: document chunking, embeddings, and retrieval."""
    
    def __init__(self, storage_dir: str = None):
        """
        Initialize RAG Manager.
        
        Args:
            storage_dir: Directory to store embeddings and document data.
                        Defaults to user's AppData/Local/LightPhon/rag
        """
        if storage_dir is None:
            storage_dir = os.path.join(
                os.environ.get('LOCALAPPDATA', os.path.expanduser('~')),
                'LightPhon', 'rag'
            )
        
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        self.documents_dir = self.storage_dir / 'documents'
        self.embeddings_dir = self.storage_dir / 'embeddings'
        self.documents_dir.mkdir(exist_ok=True)
        self.embeddings_dir.mkdir(exist_ok=True)
        
        # Chunk settings
        self.chunk_size = 512  # tokens (approximate with chars / 4)
        self.chunk_overlap = 50  # overlap between chunks
        
        # In-memory cache of embeddings for fast retrieval
        self.embeddings_cache: Dict[str, Dict] = {}
        
        # llama-server endpoint (will be set when server starts)
        self.llama_port: Optional[int] = None
        
        # Load existing embeddings into cache
        self._load_embeddings_cache()
        
        logger.info(f"RAG Manager initialized. Storage: {self.storage_dir}")
    
    def set_llama_port(self, port: int):
        """Set the llama-server port for embedding generation."""
        self.llama_port = port
        logger.info(f"RAG Manager using llama-server on port {port}")
    
    def _load_embeddings_cache(self):
        """Load all existing embeddings into memory cache."""
        for emb_file in self.embeddings_dir.glob('*.json'):
            try:
                with open(emb_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    doc_id = emb_file.stem
                    self.embeddings_cache[doc_id] = data
                    logger.debug(f"Loaded embeddings for document: {data.get('filename', doc_id)}")
            except Exception as e:
                logger.error(f"Error loading embeddings {emb_file}: {e}")
    
    def clear(self):
        """Clear all documents from the RAG knowledge base."""
        try:
            # Clear in-memory cache
            doc_count = len(self.embeddings_cache)
            self.embeddings_cache.clear()
            
            # Delete all embedding files
            for emb_file in self.embeddings_dir.glob('*.json'):
                try:
                    emb_file.unlink()
                except Exception as e:
                    logger.error(f"Error deleting {emb_file}: {e}")
            
            # Delete all document files
            for doc_file in self.documents_dir.glob('*'):
                try:
                    doc_file.unlink()
                except Exception as e:
                    logger.error(f"Error deleting {doc_file}: {e}")
            
            logger.info(f"RAG cleared: removed {doc_count} documents")
            return True, f"Cleared {doc_count} documents"
        except Exception as e:
            logger.error(f"Error clearing RAG: {e}")
            return False, f"Error: {str(e)}"
    
    def _chunk_text(self, text: str) -> List[str]:
        """
        Split text into overlapping chunks.
        
        Args:
            text: The text to chunk
            
        Returns:
            List of text chunks
        """
        # Clean text
        text = re.sub(r'\s+', ' ', text).strip()
        
        # Approximate chunk size in characters (assuming ~4 chars per token)
        char_chunk_size = self.chunk_size * 4
        char_overlap = self.chunk_overlap * 4
        
        chunks = []
        start = 0
        
        while start < len(text):
            end = start + char_chunk_size
            
            # Try to break at sentence boundary
            if end < len(text):
                # Look for sentence end near the chunk boundary
                for sep in ['. ', '! ', '? ', '\n\n', '\n']:
                    last_sep = text.rfind(sep, start + char_chunk_size // 2, end + 100)
                    if last_sep != -1:
                        end = last_sep + len(sep)
                        break
            
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            
            start = end - char_overlap
            if start < 0:
                start = 0
        
        return chunks
    
    def _compute_doc_id(self, content: str, filename: str) -> str:
        """Compute unique document ID based on content hash."""
        hash_input = f"{filename}:{content}"
        return hashlib.sha256(hash_input.encode()).hexdigest()[:16]
    
    async def _get_embedding(self, text: str) -> Optional[List[float]]:
        """
        Get embedding for text using llama-server.
        
        Args:
            text: Text to embed
            
        Returns:
            Embedding vector or None if failed
        """
        if self.llama_port is None:
            logger.error("llama-server port not set")
            return None
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"http://localhost:{self.llama_port}/embedding",
                    json={"content": text}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    # Handle both formats: {"embedding": [...]} or [{"embedding": [...]}]
                    if isinstance(data, list) and len(data) > 0:
                        # llama-server returns a list of objects
                        embedding = data[0].get('embedding') if isinstance(data[0], dict) else data
                    elif isinstance(data, dict):
                        embedding = data.get('embedding')
                    else:
                        embedding = None
                        
                    if embedding:
                        return embedding
                    logger.error(f"No embedding in response: {data}")
                else:
                    logger.error(f"Embedding request failed: {response.status_code}")
                    
        except Exception as e:
            logger.error(f"Error getting embedding: {e}")
        
        return None
    
    def _get_embedding_sync(self, text: str) -> Optional[List[float]]:
        """Synchronous version of get_embedding."""
        if self.llama_port is None:
            logger.error("llama-server port not set")
            return None
        
        try:
            response = httpx.post(
                f"http://localhost:{self.llama_port}/embedding",
                json={"content": text},
                timeout=60.0
            )
            
            if response.status_code == 200:
                data = response.json()
                logger.debug(f"Embedding response type: {type(data)}, first 100 chars: {str(data)[:100]}")
                
                embedding = None
                # Handle various formats from llama-server
                if isinstance(data, list):
                    if len(data) > 0:
                        first_item = data[0]
                        if isinstance(first_item, dict):
                            # Format: [{"embedding": [...]}]
                            embedding = first_item.get('embedding')
                        elif isinstance(first_item, (int, float)):
                            # Format: [0.1, 0.2, ...] - raw embedding array
                            embedding = data
                        elif isinstance(first_item, list):
                            # Format: [[0.1, 0.2, ...]] - nested array
                            embedding = first_item
                elif isinstance(data, dict):
                    # Format: {"embedding": [...]}
                    embedding = data.get('embedding')
                    
                if embedding:
                    logger.debug(f"Got embedding with {len(embedding)} dimensions")
                    return embedding
                logger.error(f"No embedding in response. Type: {type(data)}, Data: {str(data)[:200]}")
            else:
                logger.error(f"Embedding request failed: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Error getting embedding: {e}")
        
        return None
    
    def add_document(self, content: str, filename: str, 
                     progress_callback=None) -> Tuple[bool, str]:
        """
        Add a document to the RAG knowledge base.
        
        Args:
            content: Document text content
            filename: Original filename
            progress_callback: Optional callback(current, total, message)
            
        Returns:
            Tuple of (success, message)
        """
        if self.llama_port is None:
            return False, "llama-server not running. Please load a model first."
        
        try:
            # Compute document ID
            doc_id = self._compute_doc_id(content, filename)
            
            # Check if already indexed
            if doc_id in self.embeddings_cache:
                return True, f"Document '{filename}' already indexed."
            
            # Chunk the document
            chunks = self._chunk_text(content)
            if not chunks:
                return False, "Document is empty or could not be processed."
            
            logger.info(f"Processing document '{filename}': {len(chunks)} chunks")
            
            if progress_callback:
                progress_callback(0, len(chunks), f"Processing {len(chunks)} chunks...")
            
            # Generate embeddings for each chunk
            chunk_embeddings = []
            for i, chunk in enumerate(chunks):
                embedding = self._get_embedding_sync(chunk)
                if embedding is None:
                    logger.error(f"Failed to generate embedding for chunk {i+1}/{len(chunks)}: '{chunk[:100]}...'")
                    return False, f"Failed to generate embedding for chunk {i+1}"
                
                logger.debug(f"Chunk {i+1}/{len(chunks)} embedded successfully: {len(embedding)} dimensions")
                
                chunk_embeddings.append({
                    'chunk_id': i,
                    'text': chunk,
                    'embedding': embedding
                })
                
                if progress_callback:
                    progress_callback(i + 1, len(chunks), 
                                    f"Embedded chunk {i+1}/{len(chunks)}")
            
            # Save document data
            doc_data = {
                'doc_id': doc_id,
                'filename': filename,
                'chunk_count': len(chunks),
                'chunks': chunk_embeddings
            }
            
            # Save to file
            emb_file = self.embeddings_dir / f"{doc_id}.json"
            with open(emb_file, 'w', encoding='utf-8') as f:
                json.dump(doc_data, f)
            
            # Update cache
            self.embeddings_cache[doc_id] = doc_data
            
            logger.info(f"Document '{filename}' indexed successfully. ID: {doc_id}")
            return True, f"Document '{filename}' indexed: {len(chunks)} chunks"
            
        except Exception as e:
            logger.error(f"Error adding document: {e}")
            return False, f"Error: {str(e)}"
    
    def remove_document(self, doc_id: str) -> Tuple[bool, str]:
        """Remove a document from the knowledge base."""
        try:
            if doc_id not in self.embeddings_cache:
                return False, "Document not found"
            
            filename = self.embeddings_cache[doc_id].get('filename', doc_id)
            
            # Remove from cache
            del self.embeddings_cache[doc_id]
            
            # Remove file
            emb_file = self.embeddings_dir / f"{doc_id}.json"
            if emb_file.exists():
                emb_file.unlink()
            
            logger.info(f"Document '{filename}' removed")
            return True, f"Document '{filename}' removed"
            
        except Exception as e:
            logger.error(f"Error removing document: {e}")
            return False, f"Error: {str(e)}"
    
    def list_documents(self) -> List[Dict]:
        """List all indexed documents."""
        docs = []
        for doc_id, data in self.embeddings_cache.items():
            docs.append({
                'doc_id': doc_id,
                'filename': data.get('filename', 'Unknown'),
                'chunk_count': data.get('chunk_count', 0)
            })
        return docs
    
    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        a_np = np.array(a)
        b_np = np.array(b)
        
        dot_product = np.dot(a_np, b_np)
        norm_a = np.linalg.norm(a_np)
        norm_b = np.linalg.norm(b_np)
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return dot_product / (norm_a * norm_b)
    
    def retrieve(self, query: str, top_k: int = 3, 
                 min_similarity: float = 0.3) -> List[Dict]:
        """
        Retrieve most relevant chunks for a query.
        
        Args:
            query: The user's question
            top_k: Number of top results to return
            min_similarity: Minimum similarity threshold
            
        Returns:
            List of relevant chunks with scores
        """
        logger.info(f"RAG retrieve: query='{query[:50]}...', cache_docs={len(self.embeddings_cache)}")
        
        if not self.embeddings_cache:
            logger.warning("RAG retrieve: embeddings_cache is empty, no documents indexed")
            return []
        
        if self.llama_port is None:
            logger.error("llama-server port not set")
            return []
        
        # Get query embedding
        query_embedding = self._get_embedding_sync(query)
        if query_embedding is None:
            logger.error("Failed to get query embedding")
            return []
        
        logger.debug(f"RAG retrieve: got query embedding with {len(query_embedding)} dims")
        
        # Search all chunks
        results = []
        all_similarities = []
        for doc_id, doc_data in self.embeddings_cache.items():
            for chunk in doc_data.get('chunks', []):
                similarity = self._cosine_similarity(
                    query_embedding, 
                    chunk['embedding']
                )
                all_similarities.append(similarity)
                
                if similarity >= min_similarity:
                    results.append({
                        'doc_id': doc_id,
                        'filename': doc_data.get('filename', 'Unknown'),
                        'chunk_id': chunk['chunk_id'],
                        'text': chunk['text'],
                        'similarity': similarity
                    })
        
        if all_similarities:
            logger.info(f"RAG retrieve: checked {len(all_similarities)} chunks, "
                       f"max_sim={max(all_similarities):.3f}, min_sim={min(all_similarities):.3f}, "
                       f"matches={len(results)}")
        
        # Sort by similarity and return top_k
        results.sort(key=lambda x: x['similarity'], reverse=True)
        return results[:top_k]
    
    def augment_prompt(self, query: str, top_k: int = 3) -> Tuple[str, List[Dict]]:
        """
        Build RAG context content for injection into chat messages.
        
        Args:
            query: The user's question
            top_k: Number of context chunks to include
            
        Returns:
            Tuple of (rag_context_content, retrieved_chunks)
            The rag_context_content is suitable for use as system message content.
        """
        retrieved = self.retrieve(query, top_k=top_k)
        
        if not retrieved:
            return query, []
        
        # Build context section
        context_parts = []
        for i, chunk in enumerate(retrieved, 1):
            context_parts.append(
                f"[Context {i} from '{chunk['filename']}']:\n{chunk['text']}"
            )
        
        context = "\n\n".join(context_parts)
        
        # Build RAG system instruction (will be injected as system message)
        rag_content = f"""Use the following context from the knowledge base to answer the user's question. If the context doesn't contain relevant information, answer based on your general knowledge.

{context}"""
        
        return rag_content, retrieved
    
    def get_stats(self) -> Dict:
        """Get statistics about the knowledge base."""
        total_chunks = sum(
            len(doc.get('chunks', [])) 
            for doc in self.embeddings_cache.values()
        )
        
        return {
            'document_count': len(self.embeddings_cache),
            'total_chunks': total_chunks,
            'storage_dir': str(self.storage_dir)
        }


# File type handlers
def read_text_file(filepath: str) -> str:
    """Read plain text file."""
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        return f.read()

def read_pdf_file(filepath: str) -> str:
    """Read PDF file (requires pypdf)."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(filepath)
        text_parts = []
        for page in reader.pages:
            text_parts.append(page.extract_text())
        return '\n\n'.join(text_parts)
    except ImportError:
        raise ImportError("pypdf is required for PDF support. Install with: pip install pypdf")

def read_docx_file(filepath: str) -> str:
    """Read Word document (requires python-docx)."""
    try:
        from docx import Document
        doc = Document(filepath)
        text_parts = []
        for para in doc.paragraphs:
            text_parts.append(para.text)
        return '\n\n'.join(text_parts)
    except ImportError:
        raise ImportError("python-docx is required for DOCX support. Install with: pip install python-docx")

def read_document(filepath: str) -> Tuple[str, str]:
    """
    Read a document file and return its content.
    
    Args:
        filepath: Path to the document
        
    Returns:
        Tuple of (content, filename)
    """
    path = Path(filepath)
    filename = path.name
    suffix = path.suffix.lower()
    
    if suffix in ['.txt', '.md', '.py', '.js', '.html', '.css', '.json', '.xml', '.csv']:
        content = read_text_file(filepath)
    elif suffix == '.pdf':
        content = read_pdf_file(filepath)
    elif suffix in ['.docx', '.doc']:
        content = read_docx_file(filepath)
    else:
        # Try as text
        try:
            content = read_text_file(filepath)
        except:
            raise ValueError(f"Unsupported file type: {suffix}")
    
    return content, filename

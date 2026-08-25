"""منطق العمل (Business Logic)."""

from .chat_service import send_message
from .chunking import ChunkingError, TextChunk, chunk_text, normalize_text
from .rag_service import RetrievalOutcome, build_context_block, retrieve_context
from .retrieval import (
    SUPPORTED_RETRIEVAL_PROVIDERS,
    ChunkStore,
    MemoryChunkStore,
    OracleChunkStore,
    RetrievalError,
    RetrievedChunk,
    cosine_similarity,
    get_chunk_store,
    search_relevant_chunks,
)
from .document_service import (
    IngestionResult,
    ProcessedDocument,
    ingest_document,
    process_document,
)
from .text_extraction import (
    SUPPORTED_EXTENSIONS,
    CorruptFileError,
    EmptyDocumentError,
    FileExtractionError,
    FileTooLargeError,
    UnsupportedFileTypeError,
    extract_text,
    validate_upload,
)

__all__ = [
    "send_message",
    # التقطيع
    "ChunkingError",
    "TextChunk",
    "chunk_text",
    "normalize_text",
    # استخراج النص
    "SUPPORTED_EXTENSIONS",
    "CorruptFileError",
    "EmptyDocumentError",
    "FileExtractionError",
    "FileTooLargeError",
    "UnsupportedFileTypeError",
    "extract_text",
    "validate_upload",
    # البحث المتجهي (RAG)
    "SUPPORTED_RETRIEVAL_PROVIDERS",
    "ChunkStore",
    "MemoryChunkStore",
    "OracleChunkStore",
    "RetrievalError",
    "RetrievalOutcome",
    "RetrievedChunk",
    "build_context_block",
    "cosine_similarity",
    "get_chunk_store",
    "retrieve_context",
    "search_relevant_chunks",
    # المسار الكامل
    "IngestionResult",
    "ProcessedDocument",
    "ingest_document",
    "process_document",
]

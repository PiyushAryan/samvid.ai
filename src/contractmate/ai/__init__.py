"""Provider adapters and retrieval primitives for Samvid AI services."""

from contractmate.ai.chunking import DocumentChunk, PageAwareChunker, PageContent
from contractmate.ai.fireworks import FireworksEmbeddingsClient, FireworksRerankClient
from contractmate.ai.retrieval import HybridRetrievalService, RetrievalQuery, RetrievedChunk

__all__ = [
    "DocumentChunk",
    "FireworksEmbeddingsClient",
    "FireworksRerankClient",
    "HybridRetrievalService",
    "PageAwareChunker",
    "PageContent",
    "RetrievalQuery",
    "RetrievedChunk",
]

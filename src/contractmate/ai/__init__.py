"""Provider adapters and retrieval primitives for Samvid AI services."""

from contractmate.ai.chunking import DocumentChunk, PageAwareChunker, PageContent
from contractmate.ai.gateway import GatewayEmbeddingsClient, GatewayRerankClient
from contractmate.ai.retrieval import HybridRetrievalService, RetrievalQuery, RetrievedChunk

__all__ = [
    "DocumentChunk",
    "GatewayEmbeddingsClient",
    "GatewayRerankClient",
    "HybridRetrievalService",
    "PageAwareChunker",
    "PageContent",
    "RetrievalQuery",
    "RetrievedChunk",
]

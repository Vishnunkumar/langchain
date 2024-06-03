from __future__ import annotations

import concurrent.futures
from typing import Any, Iterable, List, Optional

import numpy as np
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever


def create_index(contexts: List[str], embeddings: Embeddings) -> np.ndarray:
    """
    Create an index of embeddings for a list of contexts.

    Args:
        contexts: List of contexts to embed.
        embeddings: Embeddings model to use.

    Returns:
        Index of embeddings.
    """
    with concurrent.futures.ThreadPoolExecutor() as executor:
        return np.array(list(executor.map(embeddings.embed_query, contexts)))


class PQRetriever(BaseRetriever):
    """`PQ retriever."""

    embeddings: Embeddings
    """Embeddings model to use."""
    index: Any
    """Index of embeddings."""
    texts: List[str]
    """List of texts to index."""
    metadatas: Optional[List[dict]] = None
    """List of metadatas corresponding with each text."""
    k: int = 4
    """Number of results to return."""
    relevancy_threshold: Optional[float] = None
    """Threshold for relevancy."""
    subspace: int = 4
    """No of subspaces to be created, should be a multiple of embedding shape"""
    clusters: int = 256
    """No of clusters to be created"""

    class Config:

        """Configuration for this pydantic object."""

        arbitrary_types_allowed = True

    
    @classmethod
    def from_texts(
        cls,
        texts: List[str],
        embeddings: Embeddings,
        metadatas: Optional[List[dict]] = None,
        **kwargs: Any,
    ) -> PQRetriever:

        index = create_index(texts, embeddings)
        return cls(
            embeddings=embeddings,
            index=index,
            texts=texts,
            metadatas=metadatas,
            **kwargs,
        ) 

    @classmethod
    def from_documents(
        cls,
        documents: Iterable[Document],
        embeddings: Embeddings,
        **kwargs: Any,
    ) -> PQRetriever:
        texts, metadatas = zip(*((d.page_content, d.metadata) for d in documents))
        return cls.from_texts(
            texts=texts, embeddings=embeddings, metadatas=metadatas, **kwargs
        )


    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> List[Document]:

        try:
            from nanopq import PQ
        except ImportError:
            raise ImportError(
                "Could not import nanopq, please install with `pip install "
                "nanopq`."
            )
        
        query_embeds = np.array(self.embeddings.embed_query(query))
        try:
            pq = PQ(M=self.subspace, K=self.clusters).fit(vecs=self.index, iter=20, seed=123)  
        except AssertionError:
            raise RuntimeError("subspace should be divisible by embedding size")
        
        index_code = pq.encode(vecs=self.index)
        dt = pq.dtable(query=query_embeds)
        dists = dt.adist(codes=index_code)

        sorted_ix = np.argsort(dists)

        top_k_results = [
            Document(
                page_content=self.texts[row],
                metadata=self.metadatas[row] if self.metadatas else {},
            )
            for row in sorted_ix[0 : self.k]
        ]
        
        return top_k_results
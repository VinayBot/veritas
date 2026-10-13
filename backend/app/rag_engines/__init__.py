"""Named, switchable RAG strategies.

Each strategy is a declared composition of building blocks that already exist elsewhere in
the app (chunkers, dense and keyword search, rank fusion, the reranker, HyDE, graph
traversal, the LangGraph agent, the council). Nothing here re-implements retrieval; it only
names combinations, says what each needs, and runs them.
"""

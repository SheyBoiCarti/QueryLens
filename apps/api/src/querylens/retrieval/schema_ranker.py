"""Lexical schema ranker and relevance scorer (Contracts C05, C10)."""

from __future__ import annotations

import re
from querylens.domain.schema import CatalogSnapshot, TableMetadata

SYNONYMS: dict[str, list[str]] = {
    "customer": ["client", "user", "buyer", "account"],
    "order": ["sale", "purchase", "transaction", "invoice"],
    "item": ["product", "line_item", "sku", "good"],
    "amount": ["price", "cost", "total", "revenue", "spending"],
}


def tokenize(text: str) -> set[str]:
    """Tokenize and normalize text into word stems with synonym expansion."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    tokens = set()
    for w in words:
        tokens.add(w)
        if w.endswith("s") and len(w) > 3:
            tokens.add(w[:-1])
        if w.endswith("es") and len(w) > 4:
            tokens.add(w[:-2])

    # Add synonyms
    for t in list(tokens):
        for canon, syns in SYNONYMS.items():
            if t == canon or t in syns:
                tokens.add(canon)
                tokens.update(syns)
    return tokens


class SchemaRanker:
    """Ranks visible tables by relevance to natural language question."""

    @staticmethod
    def rank_tables(question: str, snapshot: CatalogSnapshot, top_k: int = 5) -> list[TableMetadata]:
        q_tokens = tokenize(question)
        if not q_tokens:
            return snapshot.tables[:top_k]

        scored: list[tuple[float, TableMetadata]] = []

        for table in snapshot.tables:
            score = 0.0
            t_tokens = tokenize(table.name)

            # Match table name
            shared_table = q_tokens.intersection(t_tokens)
            score += len(shared_table) * 5.0

            # Match column names
            for col in table.columns:
                c_tokens = tokenize(col.name)
                shared_col = q_tokens.intersection(c_tokens)
                score += len(shared_col) * 2.0

            # Boost tables with foreign keys (centrality)
            score += min(len(table.foreign_keys), 3) * 0.5

            scored.append((score, table))

        # Sort descending by score, tie-break by table name
        scored.sort(key=lambda x: (-x[0], x[1].name))
        return [item[1] for item in scored[:top_k]]

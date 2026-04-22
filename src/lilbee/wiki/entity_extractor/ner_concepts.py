"""spaCy NER + noun-phrase concept extractor (default strategy).

Stub: the real implementation lands in the next task, which reuses the
spaCy pipeline from ``clustering_concepts.py`` and dedupes NER surface
forms against concept cluster labels.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lilbee.wiki.entity_extractor.base import ExtractedEntity

if TYPE_CHECKING:
    from lilbee.config import Config
    from lilbee.providers.base import LLMProvider
    from lilbee.store import SearchChunk


class NerConceptsExtractor:
    """Combine spaCy NER and noun-phrase clustering into one entity set."""

    def __init__(self, provider: LLMProvider, config: Config) -> None:
        self._provider = provider
        self._config = config

    def extract(self, chunks: list[SearchChunk]) -> list[ExtractedEntity]:
        raise NotImplementedError("NerConceptsExtractor.extract is not yet implemented")

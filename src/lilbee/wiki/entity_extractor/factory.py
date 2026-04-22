"""Runtime selector for the entity-extraction strategy."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from lilbee.config import WikiEntityMode
from lilbee.wiki.entity_extractor.base import EntityExtractor
from lilbee.wiki.entity_extractor.llm_tagged import LlmTaggedExtractor
from lilbee.wiki.entity_extractor.ner_concepts import NerConceptsExtractor
from lilbee.wiki.entity_extractor.ner_concepts_plus_llm_types import (
    NerConceptsPlusLlmTypesExtractor,
)

if TYPE_CHECKING:
    from lilbee.config import Config
    from lilbee.providers.base import LLMProvider


# Each implementation's constructor doubles as the factory callable; the
# Protocol itself can't declare ``__init__`` without losing structural
# typing, so the dispatch map types values as callables instead of classes.
_EXTRACTOR_BY_MODE: dict[
    WikiEntityMode,
    Callable[[LLMProvider, Config], EntityExtractor],
] = {
    WikiEntityMode.NER_CONCEPTS: NerConceptsExtractor,
    WikiEntityMode.NER_CONCEPTS_PLUS_LLM_TYPES: NerConceptsPlusLlmTypesExtractor,
    WikiEntityMode.LLM_TAGGED: LlmTaggedExtractor,
}


def get_entity_extractor(
    mode: WikiEntityMode, provider: LLMProvider, config: Config
) -> EntityExtractor:
    """Return an ``EntityExtractor`` implementation for *mode*."""
    factory = _EXTRACTOR_BY_MODE[mode]
    return factory(provider, config)

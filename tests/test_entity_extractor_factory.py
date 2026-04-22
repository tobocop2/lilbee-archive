"""Tests for the entity-extractor package scaffolding.

Covers the protocol, record shapes, factory dispatch, stub NotImplementedError
behaviour, and the config + settings_map plumbing. The per-strategy logic
(NER, concepts, LLM) is exercised in the strategy-specific test modules.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from lilbee.cli.settings_map import SETTINGS_MAP
from lilbee.config import WikiEntityMode, cfg
from lilbee.wiki.entity_extractor import (
    ChunkRef,
    EntityExtractor,
    EntityKind,
    ExtractedEntity,
    get_entity_extractor,
)
from lilbee.wiki.entity_extractor.llm_tagged import LlmTaggedExtractor
from lilbee.wiki.entity_extractor.ner_concepts import NerConceptsExtractor
from lilbee.wiki.entity_extractor.ner_concepts_plus_llm_types import (
    NerConceptsPlusLlmTypesExtractor,
)


class TestExtractedEntityRecord:
    def test_has_expected_fields_and_is_frozen(self) -> None:
        entity = ExtractedEntity(
            slug="tire-pressure",
            kind=EntityKind.CONCEPT,
            label="Tire pressure",
            type_hint="noun_phrase",
            chunk_refs=(ChunkRef(source="manual.pdf", chunk_index=12),),
        )
        assert entity.slug == "tire-pressure"
        assert entity.kind is EntityKind.CONCEPT
        assert entity.label == "Tire pressure"
        assert entity.type_hint == "noun_phrase"
        assert entity.chunk_refs == (ChunkRef(source="manual.pdf", chunk_index=12),)
        # frozen=True: assignment must fail to keep records hashable.
        with pytest.raises(AttributeError):
            entity.slug = "other"  # type: ignore[misc]

    def test_kind_enum_covers_both_variants(self) -> None:
        assert EntityKind.CONCEPT.value == "concept"
        assert EntityKind.ENTITY.value == "entity"


class TestFactoryDispatch:
    """Each mode routes to the matching extractor class."""

    @pytest.mark.parametrize(
        ("mode", "expected_cls"),
        [
            (WikiEntityMode.NER_CONCEPTS, NerConceptsExtractor),
            (WikiEntityMode.NER_CONCEPTS_PLUS_LLM_TYPES, NerConceptsPlusLlmTypesExtractor),
            (WikiEntityMode.LLM_TAGGED, LlmTaggedExtractor),
        ],
    )
    def test_returns_matching_implementation(
        self, mode: WikiEntityMode, expected_cls: type
    ) -> None:
        provider = MagicMock()
        extractor = get_entity_extractor(mode, provider, cfg)
        assert isinstance(extractor, expected_cls)
        # Every implementation must satisfy the runtime-checkable protocol.
        assert isinstance(extractor, EntityExtractor)


class TestStubsRaiseNotImplemented:
    """The unimplemented strategies still signal absence with NotImplementedError.

    NER_CONCEPTS is live (see ``tests/test_ner_concepts_extractor.py``); the
    other two remain stubs until their own tasks land.
    """

    @pytest.mark.parametrize(
        "mode",
        [WikiEntityMode.NER_CONCEPTS_PLUS_LLM_TYPES, WikiEntityMode.LLM_TAGGED],
    )
    def test_extract_raises_not_implemented(self, mode: WikiEntityMode) -> None:
        provider = MagicMock()
        extractor = get_entity_extractor(mode, provider, cfg)
        with pytest.raises(NotImplementedError):
            extractor.extract([])


class TestConfigPlumbing:
    def test_default_mode_is_ner_concepts(self) -> None:
        # Late-bound: read from cfg so a test that mutates the field restores
        # visibility via the fixture snapshot.
        assert cfg.wiki_entity_mode is WikiEntityMode.NER_CONCEPTS

    def test_settings_map_entry_lists_all_modes(self) -> None:
        entry = SETTINGS_MAP["wiki_entity_mode"]
        assert entry.type is str
        assert entry.group == "Wiki"
        assert entry.choices is not None
        assert set(entry.choices) == {m.value for m in WikiEntityMode}

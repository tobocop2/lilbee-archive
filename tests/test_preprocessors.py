"""Tests for format-specific preprocessors."""

from pathlib import Path

import pytest

from lilbee.preprocessors import preprocess_xml


class TestPreprocessXml:
    def test_godot_class_reference(self, tmp_path: Path) -> None:
        xml = tmp_path / "AStarGrid2D.xml"
        xml.write_text(
            '<?xml version="1.0"?>\n'
            '<class name="AStarGrid2D" inherits="RefCounted">\n'
            "  <brief_description>A* on a 2D grid.</brief_description>\n"
            "  <methods>\n"
            '    <method name="get_point_path">\n'
            '      <return type="PackedVector2Array" />\n'
            '      <param index="0" name="from_id" type="Vector2i" />\n'
            "      <description>Returns path IDs.</description>\n"
            "    </method>\n"
            "  </methods>\n"
            "</class>"
        )
        result = preprocess_xml(xml)
        assert "AStarGrid2D" in result
        assert "RefCounted" in result
        assert "get_point_path" in result
        assert "from_id" in result
        assert "Vector2i" in result
        assert "Returns path IDs" in result

    def test_nested_attributes(self, tmp_path: Path) -> None:
        xml = tmp_path / "test.xml"
        xml.write_text('<root version="2.0"><item id="1">Hello</item></root>')
        result = preprocess_xml(xml)
        assert "version" in result or "2.0" in result
        assert "Hello" in result

    def test_empty_xml(self, tmp_path: Path) -> None:
        xml = tmp_path / "empty.xml"
        xml.write_text("<root/>")
        result = preprocess_xml(xml)
        assert result.strip() == "" or "root" in result

    def test_malformed_xml(self, tmp_path: Path) -> None:
        xml = tmp_path / "bad.xml"
        xml.write_text("<root><unclosed>")
        result = preprocess_xml(xml)
        assert "<root>" in result

    def test_text_only_elements(self, tmp_path: Path) -> None:
        xml = tmp_path / "text.xml"
        xml.write_text("<doc><p>First paragraph.</p><p>Second paragraph.</p></doc>")
        result = preprocess_xml(xml)
        assert "First paragraph" in result
        assert "Second paragraph" in result

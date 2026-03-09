"""Language data for tree-sitter code chunking.

Extension-to-language mapping is auto-built at import time by intersecting pygments
extension data with the languages tree-sitter-language-pack supports. This avoids
maintaining a manual dict that drifts as tree-sitter-language-pack adds languages.

_DEFINITION_TYPES stays manual — it encodes domain-specific AST knowledge no library provides.
"""

from typing import get_args

from pygments.lexers import get_all_lexers
from tree_sitter_language_pack import SupportedLanguage

# Hack: SupportedLanguage is Literal[...] in 0.13; use get_args to extract.
# Replace with available_languages() when 2.0 ships.
_TS_LANGS: frozenset[str] = frozenset(get_args(SupportedLanguage))

_EXT_TO_LANG: dict[str, str] = {}
for _name, _aliases, _patterns, _ in get_all_lexers():
    for _alias in _aliases:
        if _alias in _TS_LANGS:
            for _pat in _patterns:
                if _pat.startswith("*."):
                    _EXT_TO_LANG.setdefault(_pat[1:].lower(), _alias)
            break

# AST node types that represent extractable definitions, per language.
_DEFINITION_TYPES: dict[str, frozenset[str]] = {
    "python": frozenset(
        {
            "function_definition",
            "class_definition",
            "decorated_definition",
        }
    ),
    "javascript": frozenset(
        {
            "function_declaration",
            "class_declaration",
            "export_statement",
            "lexical_declaration",
        }
    ),
    "typescript": frozenset(
        {
            "function_declaration",
            "class_declaration",
            "export_statement",
            "lexical_declaration",
            "interface_declaration",
            "type_alias_declaration",
        }
    ),
    "go": frozenset(
        {
            "function_declaration",
            "method_declaration",
            "type_declaration",
        }
    ),
    "rust": frozenset(
        {
            "function_item",
            "impl_item",
            "struct_item",
            "enum_item",
            "trait_item",
        }
    ),
    "java": frozenset(
        {
            "class_declaration",
            "method_declaration",
            "interface_declaration",
        }
    ),
    "c": frozenset({"function_definition", "struct_specifier"}),
    "cpp": frozenset(
        {
            "function_definition",
            "class_specifier",
            "struct_specifier",
        }
    ),
    "ruby": frozenset({"method", "class", "module", "singleton_method"}),
    "php": frozenset({"function_definition", "class_declaration", "method_declaration"}),
    "csharp": frozenset({"method_declaration", "class_declaration", "interface_declaration"}),
    "bash": frozenset({"function_definition"}),
    "kotlin": frozenset({"function_declaration", "class_declaration", "object_declaration"}),
    "swift": frozenset({"function_declaration", "class_declaration", "protocol_declaration"}),
    "scala": frozenset(
        {"function_definition", "class_definition", "object_definition", "trait_definition"}
    ),
    "lua": frozenset({"function_declaration", "function_definition_statement"}),
    "elixir": frozenset({"call"}),
    "haskell": frozenset({"function", "type_alias", "newtype", "adt"}),
    "dart": frozenset({"function_signature", "class_definition", "method_signature"}),
    "ocaml": frozenset({"let_binding", "type_definition", "module_binding"}),
    "erlang": frozenset({"function_clause"}),
    "clojure": frozenset({"list_lit"}),
    "elm": frozenset({"function_declaration_left", "type_alias_declaration", "type_declaration"}),
    "julia": frozenset({"function_definition", "struct_definition", "module_definition"}),
    "r": frozenset({"function_definition"}),
    "perl": frozenset({"function_definition"}),
    "groovy": frozenset({"function_definition", "class_definition", "method_declaration"}),
    "fortran": frozenset({"function", "subroutine", "module"}),
    "pascal": frozenset({"function_declaration", "procedure_declaration"}),
    "d": frozenset({"function_declaration", "class_declaration", "struct_declaration"}),
    "nim": frozenset({"proc_declaration", "func_declaration", "type_section"}),
    "zig": frozenset({"function_declaration"}),
    "v": frozenset({"function_declaration", "struct_declaration"}),
    "odin": frozenset({"procedure_declaration"}),
    "solidity": frozenset({"function_definition", "contract_declaration"}),
    "terraform": frozenset({"block"}),
    "sql": frozenset({"create_function_statement", "create_table_statement"}),
    "objc": frozenset({"function_definition", "class_interface", "class_implementation"}),
    "cuda": frozenset({"function_definition", "struct_specifier"}),
    "fsharp": frozenset({"function_or_value_defn", "type_definition", "module_defn"}),
}

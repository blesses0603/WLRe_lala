"""程式內審核的精確來源／解析器配對；不依賴遊戲功能模組。"""
from dataclasses import dataclass

from wlre.resources_runtime.parsers import scenes, texts


@dataclass(frozen=True)
class SourceAdapter:
    parser_id: str
    package: str
    asset_path: str
    parse: object
    error_type: type
    parser_version: int
    schema_version: int
    record_size: int | None
    uninterpreted_ranges: tuple
    unresolved_relations: tuple[str, ...]
    acceptance_scope: str

    def receipt(self, table):
        return {
            'parser_version': self.parser_version, 'schema_version': self.schema_version,
            'record_count': len(table.records), 'records_offset': 4,
            'record_size': self.record_size, 'uninterpreted_ranges': self.uninterpreted_ranges,
            'unresolved_relations': self.unresolved_relations,
            'acceptance_scope': self.acceptance_scope,
        }


SCENES = SourceAdapter(
    scenes.PARSER_ID, 'DataPackage', 'Assets/ResourcesBuild/Data/ScenesData_C.bytes',
    scenes.parse_scene_table, scenes.SceneFormatError, scenes.PARSER_VERSION,
    scenes.SCHEMA_VERSION, scenes.RECORD_SIZE, scenes.UNINTERPRETED_RANGES,
    ('name_id', 'model_id'), 'scene_definitions_only')
TEXTS = SourceAdapter(
    texts.PARSER_ID, 'DataPackage', 'Assets/ResourcesBuild/Data/TextData_C.bytes',
    texts.parse_text_table, texts.TextFormatError, texts.PARSER_VERSION,
    texts.SCHEMA_VERSION, None, (), (), 'text_definitions_only')


def adapter_for(requirement):
    return next((adapter for adapter in (SCENES, TEXTS)
                 if (requirement.parser_id, requirement.package, requirement.asset_path)
                 == (adapter.parser_id, adapter.package, adapter.asset_path)), None)

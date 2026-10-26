"""有界的已審核解析器入口；回報欄位缺口，不核准遊戲協定。"""
from dataclasses import dataclass

from wlre.resources_runtime.official.contracts import (
    ResourceFinding,
    ResourceStatus,
    supported_requirement,
)
from wlre.resources_runtime.parsers.scenes import SceneFormatError, parse_scene_table


@dataclass(frozen=True)
class CompatibilityResult:
    finding: ResourceFinding
    table: object | None = None


class CompatibilityValidator:
    def validate(self, requirement, raw):
        if not supported_requirement(requirement):
            return CompatibilityResult(requirement.finding(ResourceStatus.UNSUPPORTED,
                'parser_or_asset_binding_unsupported'))
        try:
            table = parse_scene_table(raw)
            if not table.records:
                raise SceneFormatError('required_scene_index_empty')
        except SceneFormatError as exc:
            # 解析器只產生程式內固定代碼，不回傳原始外部例外文字。
            return CompatibilityResult(requirement.finding(ResourceStatus.INVALID,
                str(exc), field='scene_record_layout'))
        return CompatibilityResult(requirement.finding(ResourceStatus.VALID,
            'scene_definitions_validated'), table)

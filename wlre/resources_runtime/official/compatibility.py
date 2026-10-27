"""有界的已審核解析器入口；回報欄位缺口，不核准遊戲協定。"""
from dataclasses import dataclass

from wlre.resources_runtime.official.adapters import SCENES, adapter_for
from wlre.resources_runtime.official.contracts import (
    ResourceFinding,
    ResourceStatus,
    supported_requirement,
)


@dataclass(frozen=True)
class CompatibilityResult:
    finding: ResourceFinding
    table: object | None = None


class CompatibilityValidator:
    def validate(self, requirement, raw):
        if not supported_requirement(requirement):
            return CompatibilityResult(requirement.finding(ResourceStatus.UNSUPPORTED,
                'parser_or_asset_binding_unsupported'))
        adapter = adapter_for(requirement)
        try:
            table = adapter.parse(raw)
            if not table.records:
                raise adapter.error_type('required_resource_index_empty')
        except adapter.error_type as exc:
            # 解析器只產生程式內固定代碼，不回傳原始外部例外文字。
            return CompatibilityResult(requirement.finding(ResourceStatus.INVALID,
                str(exc), field=('scene_record_layout' if adapter is SCENES else 'text_record_layout')))
        return CompatibilityResult(requirement.finding(ResourceStatus.VALID,
            ('scene_definitions_validated' if adapter is SCENES else 'text_definitions_validated')), table)

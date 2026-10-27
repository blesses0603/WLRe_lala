"""場景消費者的欄位需求；這是程式契約，不是人工遊戲資料表。"""
from collections import Counter
from dataclasses import dataclass

from wlre.resources_runtime.official.contracts import ResourceStatus

# 所需來源尚未接入時保留 UNKNOWN，不拿舊地圖／門資料混充本次官方快照。
_UNOBSERVED = (
    ('model_content', 'verified_scene_bundle_required'),
    ('map_image', 'verified_map_image_required'),
    ('coordinate_mapping', 'verified_coordinate_mapping_required'),
    ('teleport_destination', 'verified_scene_event_links_required'),
    ('walkable_grid', 'official_scanned_grid_required'),
    ('dynamic_obstacles', 'live_obstacle_observation_required'),
)


@dataclass(frozen=True)
class SceneField:
    field: str
    status: ResourceStatus
    code: str


@dataclass(frozen=True)
class SceneAssessment:
    scene_id: int
    name: str | None
    model_id: int
    map_width: int
    map_height: int
    fields: tuple[SceneField, ...]

    def status(self, field):
        for row in self.fields:
            if row.field == field:
                return row.status
        raise KeyError(field)

    @property
    def label_ready(self):
        return self.status('name') is ResourceStatus.VALID

    @property
    def map_ready(self):
        return all(self.status(field) is ResourceStatus.VALID for field in
                   ('model_manifest', 'model_content', 'map_image', 'map_dimensions', 'coordinate_mapping'))

    @property
    def navigation_ready(self):
        return self.map_ready and all(self.status(field) is ResourceStatus.VALID for field in
                                      ('walkable_grid', 'dynamic_obstacles'))

    @property
    def teleport_ready(self):
        # 本批未驗收事件條件／協定；欄位檢查不能授權正式遊戲操作。
        return False


def assess_scene_fields(scenes, references):
    by_id = {row.scene_id: row for row in references}
    if len(by_id) != len(references):
        raise ValueError('scene_reference_identity_required')
    result = []
    for scene in scenes:
        reference = by_id.get(scene['id'])
        if reference is None or reference.model_id != scene['model_id'] or reference.name_id != scene['name_id']:
            raise ValueError('scene_reference_identity_required')
        dimensions = scene['map_width'] > 0 and scene['map_height'] > 0
        fields = (
            SceneField('name', reference.name_status, reference.name_code),
            SceneField('model_manifest', reference.model_manifest_status, reference.model_code),
            SceneField('map_dimensions', ResourceStatus.VALID if dimensions else ResourceStatus.MISSING,
                       'scene_dimensions_definition_only' if dimensions else 'scene_dimensions_unavailable'),
            *(SceneField(field, ResourceStatus.UNKNOWN, code) for field, code in _UNOBSERVED),
        )
        result.append(SceneAssessment(scene['id'], reference.name, scene['model_id'],
                                      scene['map_width'], scene['map_height'], fields))
    return tuple(result)


def scene_field_summary(assessments):
    return {
        'scene_count': len(assessments),
        'fields': {field: dict(Counter(row.status(field).value for row in assessments))
                   for field in ('name', 'model_manifest', 'map_dimensions',
                                 *(field for field, _ in _UNOBSERVED))},
        'label_ready_count': sum(row.label_ready for row in assessments),
        'map_ready_count': sum(row.map_ready for row in assessments),
        'navigation_ready_count': sum(row.navigation_ready for row in assessments),
        'teleport_ready_count': sum(row.teleport_ready for row in assessments),
        'acceptance_scope': 'read_only_scene_field_audit',
    }

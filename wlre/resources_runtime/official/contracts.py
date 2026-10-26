"""功能需要的官方資料契約；不由 Manifest 或快取動態載入程式碼。"""
from dataclasses import dataclass
from enum import Enum

from wlre.core.primitives import identifier
from wlre.resources_runtime.parsers.scenes import PARSER_ID

SCENES_ASSET = 'Assets/ResourcesBuild/Data/ScenesData_C.bytes'


class ResourceStatus(str, Enum):
    UNKNOWN = 'UNKNOWN'
    MISSING = 'MISSING'
    UNSUPPORTED = 'UNSUPPORTED'
    INVALID = 'INVALID'
    VALID = 'VALID'


@dataclass(frozen=True)
class ResourceRequirement:
    index: str
    module: str
    package: str
    asset_path: str
    parser_id: str

    def __post_init__(self):
        identifier(self.index)
        identifier(self.module)
        if self.package not in ('DataPackage', 'MainPackage'):
            raise ValueError('unsupported_resource_package')
        path = self.asset_path
        if (type(path) is not str or not path.startswith('Assets/') or len(path) > 1024
                or '\x00' in path or '\\' in path or any(c in path for c in '*?[]')
                or any(part in ('', '.', '..') for part in path.split('/'))):
            raise ValueError('exact_resource_asset_path_required')
        if type(self.parser_id) is not str or not 1 <= len(self.parser_id) <= 64:
            raise ValueError('invalid_resource_parser_id')

    def finding(self, status, code, *, field=''):
        return ResourceFinding(self.index, self.module, status, code, self.asset_path, field)


SCENE_DEFINITIONS = ResourceRequirement(
    'scene_definitions', 'scene', 'DataPackage', SCENES_ASSET, PARSER_ID)


@dataclass(frozen=True)
class ResourceFinding:
    index: str
    module: str
    status: ResourceStatus
    code: str
    resource: str
    field: str = ''


def validated_requirements(requirements):
    if (type(requirements) is not tuple or not 1 <= len(requirements) <= 32
            or any(not isinstance(item, ResourceRequirement) for item in requirements)
            or len({item.index for item in requirements}) != len(requirements)):
        raise ValueError('bounded_unique_resource_requirements_required')
    return requirements


def supported_requirement(requirement):
    # 程式內審核過的格式／完整路徑配對，不接受資料自行宣告為任意 Parser。
    return (requirement.parser_id == PARSER_ID
            and requirement.package == 'DataPackage'
            and requirement.asset_path == SCENES_ASSET)

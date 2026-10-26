"""只查已驗證 Manifest 的精確需求；不爬站、不猜名稱或 URL。"""
from dataclasses import dataclass

from wlre.resources_runtime.official.contracts import (
    ResourceFinding,
    ResourceStatus,
    supported_requirement,
    validated_requirements,
)
from wlre.services.official_incremental_sync import build_update_plan
from wlre.services.official_manifest_sync import VerifiedManifest


@dataclass(frozen=True)
class ResourceGapReport:
    findings: tuple[ResourceFinding, ...]
    plans: tuple

    @property
    def complete(self):
        return bool(self.findings) and all(
            item.status is ResourceStatus.VALID for item in self.findings)


class ResourceGapAnalyzer:
    def analyze(self, requirements, manifests, *, bundle_cache=None):
        validated_requirements(requirements)
        findings, plans = [], []
        for requirement in requirements:
            status, code = ResourceStatus.VALID, 'exact_resource_identified'
            manifest = manifests.get(requirement.package)
            if manifest is None:
                status, code = ResourceStatus.UNKNOWN, 'package_not_observed'
            elif (not isinstance(manifest, VerifiedManifest)
                  or manifest.spec.package != requirement.package):
                status, code = ResourceStatus.INVALID, 'unverified_manifest'
            elif not supported_requirement(requirement):
                status, code = ResourceStatus.UNSUPPORTED, 'parser_or_asset_binding_unsupported'
            else:
                paths = [row.get('path') for row in manifest.index.get('assets', [])
                         if isinstance(row, dict)]
                if requirement.asset_path not in paths:
                    status, code = ResourceStatus.MISSING, 'exact_asset_missing'
                else:
                    try:
                        plan = build_update_plan(manifest, asset_paths=(requirement.asset_path,),
                                                 cache_root=bundle_cache)
                        selected = {row.spec.name for row in plan.entries}
                        if any(row.get('encrypted') is not False
                               for row in manifest.index['bundles'] if row['name'] in selected):
                            status, code = ResourceStatus.UNSUPPORTED, 'encrypted_bundle_unsupported'
                        else:
                            plans.append(plan)
                    except (ValueError, TypeError, KeyError, RecursionError):
                        status, code = ResourceStatus.INVALID, 'manifest_dependency_invalid'
            findings.append(requirement.finding(status, code))
        # 對整批必要閉包設限，而不是每個 Package 各自重新取得配額。
        unique = {(row.spec.package, row.spec.name): row.spec
                  for plan in plans for row in plan.entries}
        if len(unique) > 24 or sum(row.file_size for row in unique.values()) > 64 * 1024 * 1024:
            findings = [ResourceFinding(item.index, item.module, ResourceStatus.INVALID,
                                        'resource_scope_quota_exceeded', item.resource)
                        for item in findings]
        return ResourceGapReport(tuple(findings), tuple(plans))

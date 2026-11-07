# Desktop unused-code audit (2026-11-07)

## Scope and evidence

Reviewed PR #74 at `c085507ef57c7ddd447fd34c6b24db8240164e48`, then
rebased the cleanup onto `a4f4b48b5ec3ec7eb501a20753b7a762aac6a9e2` (including the single-page emoji changes).
`main` was `f87ea585d1ad41471635e147895a10082131702e` and is an ancestor.
This is a conservative cleanup, not proof that every unused public API can be removed.
No Android, user data, resource contents, runtime permissions or packet guards changed.

The audit covered top-level Python imports, single-reference function/class candidates,
repository references (including tests and string patch targets), compatibility adapters,
dynamic module lookups, application entry points, the resource manifest, and Windows/macOS
build plans. Import candidates were checked against AST name loads in their defining
module. Merely having no static caller was not considered sufficient for deleting a public
function, compatibility facade, CLI tool or fail-closed guard.

## Removed: 30 unused import bindings in 9 modules

- `wlre/network/protocol.py`: `RESOURCE_ROOT`, `json`. Protocol enums now come from code-owned configuration.
- `wlre/storage/defaults.py`: `json`. Defaults use a deep copy of code-owned configuration.
- `wlre/storage/server_lines.py`: `json`. Verified server-list loading is delegated to the official service.
- `wlre/services/expedition/data.py`: `json`, `RESOURCE_ROOT`. Active catalog and binary parsers do not use these imports.
- `wlre/services/items/crafting.py`: `json`, `RESOURCE_ROOT`. Recipes are activated from validated runtime data.
- `wlre/services/world/coordinates.py` and `obstacle_scope.py`: unused `json` imports. Both retain the actual bundled database readers and resource roots.
- `wlre/services/world/npc_interact.py`: `hashlib`, `RESOURCE_ROOT`. Explicit legacy parsing, size/schema checks, constants and active runtime lookup remain intact.
- `wlre/ui/home_map.py`: 18 imports left behind after canvas, navigation, NPC and portal behavior moved to feature mixins: `PROJECT_ROOT`, `math`, `configure_dialog`, `Image`, `ImageTk`, `current_position`, `Repository`, `NavigationError`, `map_label`, `parse_map_id`, `nearest_marker`, `portal_map_pixel`, `destination_problem`, `npc_detail`, `dialogue_text`, `shop_catalog`, `item_catalog`, `sellable`. The mixins retain their own imports and implementations.

## Deliberately retained

- The three navigation seeds inside `resource_catalog_seed.sqlite3`: `navigation_data.zip`, `graph_origins.json`, `stage_coordinates.json`. Coordinates, obstacle scope and legacy navigation still consume them. No seed or standalone asset was deleted.
- All 33 tracked resource files, including artwork and attribution. The shared packaging manifest and nested asset handling still need these resources.
- `home_map.messagebox`: existing NPC/dialogue tests patch this shared Tk module symbol.
- `defaults.RESOURCE_ROOT`: no-seed tests patch this historical symbol. A brief comment now documents why it remains.
- `expedition_ui`, `expedition_data`, `expedition_teams`, `auto_battle_ui` and `ui.minimap` compatibility imports. They intentionally re-export symbols or preserve test/extension hooks; expedition also has dynamic attribute forwarding.
- `formal_candidate_bridge`: retired methods deliberately raise instead of permitting legacy candidate promotion.
- Public metadata loaders, public methods with no direct in-repository caller, standalone diagnostic/research tools and historical audit reports. Lack of a caller alone does not prove these removable.
- Resource integrity checks, size limits, compatibility checks and movement/packet permission gates.

## Validation

All test data and logs were directed to temporary cloud-local directories; no user desktop GUI or installed user profile was used. Dependencies use the repository's pinned UnityPy/crypto requirements and supported Pillow range.

- `python -m unittest discover -s tests -q`: 2,025 tests, OK, 193 skipped (primarily no display/platform-specific prerequisites).
- `python -m compileall -q wlre tools tests WLRE_Client.py`: passed.
- `python -m tools.audit_repository --strict-git`: passed, 257 links checked, no broken links or nonempty duplicate tracked blobs.
- `python WLRE_Client.py --self-test`: passed.
- `python WLRE_Client.py --self-test-unityfs`: passed with UnityPy 1.25.4 and Pillow 12.3.0.
- Windows Nuitka and macOS arm64/x64 dry-run build plans: passed.
- `git diff --check`: passed.

The initial run exposed an existing no-seed patch target (`defaults.RESOURCE_ROOT`), so it was restored before final validation. An initial missing UnityPy dependency and default unwritable home directory were addressed by installing the declared dependencies into a temporary target and setting a fresh temporary `LOCALAPPDATA`; no application behavior was changed to mask those environment issues. Native Windows/macOS compilation and live game behavior are outside this import-only audit. A Linux run without a display skips GUI cases and is not full GUI acceptance.

# v0.4.19 檔案分區說明

啟動入口保留 `WLRE_Client.py`（Nuitka 直接入口）及根目錄 BAT；原始碼啟動程序為 `wlre/launcher.py`（由兩個啟動 BAT 使用）；命令列入口為 `wlre/__main__.py`。
執行期程式歸入六區，建置、維護工具、文件及測試置於程式套件外。
此次是檔案組織調整，尚未將 SessionLogic 與 App 全面拆成獨立服務。

## wlre/ui

- `__init__.py`
- `auto_battle_ui.py`
- `battle_view.py`
- `chat_emoji.py`
- `chat_ui.py`
- `crafting_browser.py`
- `crafting_plan_ui.py`
- `crafting_ui.py`
- `dashboard_layout.py`：主視窗幾何與區域配置
- `window_layout.py`：功能視窗尺寸限制與置中配置
- `overview_ui.py`：狀態摘要與功能入口
- `efficiency_ui.py`
- `gui.py`
- `home_map.py`
- `minimap.py`
- `navigation_gui.py`
- `party_guard_ui.py`
- `recovery_ui.py`
- `resource_view.py`
- `rounded_notebook.py`
- `services_ui.py`
- `theme.py`

## wlre/services/battle

- `__init__.py`
- `auto_battle.py`
- `battle_commands.py`
- `combat.py`
- `party.py`
- `party_guard.py`

## wlre/services/world

- `__init__.py`
- `coordinates.py`
- `display_position.py`
- `map_names.py`
- `movement.py`
- `movement_display.py`
- `navigation.py`
- `obstacle_scope.py`
- `portal_policy.py`
- `portal_travel.py`
- `portals.py`
- `roaming.py`

## wlre/services/items

- `__init__.py`
- `alchemy.py`
- `combat_resources.py`
- `crafting.py`
- `crafting_browser_model.py`
- `crafting_plan.py`
- `field_supply.py`
- `recovery.py`

## wlre/services/social

- `__init__.py`
- `chat.py`
- `chat_names.py`
- `guild.py`

## wlre/core

- `diagnostics.py`：不含使用者內容的介面效能紀錄

- `__init__.py`
- `activity.py`
- `efficiency.py`
- `event_log.py`
- `inventory_updates.py`
- `state.py`

## wlre/network

- `__init__.py`
- `client.py`
- `layouts.py`
- `live_data.py`
- `protocol.py`
- `social_protocol.py`
- `wire.py`

## wlre/storage

- `atomic.py`：跨程序設定檔鎖與原子儲存
- `account_settings.py`：帳號及分流獨立偏好設定

- `__init__.py`
- `defaults.py`
- `login_memory.py`
- `server_lines.py`

## wlre/resources

- `alchemy_catalog.json`
- `assets`
- `combat_catalog.json`
- `crafting_catalog.json`
- `default_profile.json`
- `emoji_catalog.json`
- `emoji_images.zip`
- `enums.json`
- `graph_origins.json`
- `item_icon_coverage.json`
- `item_icon_map.json`
- `item_icons.zip`
- `item_stackable.json`
- `map_names.json`
- `navigation_data.zip`
- `normal_attack_data.json`
- `portals.json`
- `server_list.json`
- `smallmaps.zip`
- `stage_coordinates.json`

## tools/build

- `__init__.py`
- `build_nuitka.py`
- `python_build_support.py`

## tools/resources

- `__init__.py`
- `collect_emoji_resources.py`

## 路徑與維護約定

新增 Python 模組放入對應功能目錄，使用完整套件匯入。唯讀資源經 `wlre.paths.RESOURCE_ROOT` 取得；使用者設定延續原本儲存位置。新增資源請一併更新 `WLRE_Client.self_test()`；Nuitka 會遞迴收錄既有支援副檔名。


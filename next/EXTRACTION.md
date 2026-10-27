# 0-1：參考核心抽取清單（舊 repo commit `2dd6694`）

> 所有數字由 `next/tools-python/analyze_deps.py` 實際執行產生，可重現。
> 「處置」欄是**建議**，屬於判斷而不是量測，已與量測事實分開標示。

## 量測事實

| 項目 | 結果 |
|---|---|
| `wlre` 模組總數 | 240；其中 `network/core/services/storage` 共 144 |
| 非 UI 層引用 `ui/features` | **0 處** |
| 模組層級的 import 循環 | **只有 1 組、26 個模組，全部在 `services/`**（清單見下） |
| 跨層模組邊數 | network→services 60、core→services 20、services→network 40、services→storage 22、services→core 13、network→core 5、storage→services 4、core→network 1、core→storage 1、storage→network 1 |
| 以 fresh interpreter 實際 import `protocol`、`state`、`client` | `tkinter`、`PIL`、`UnityPy` **皆未被載入** |
| 靜態傳遞依賴（含函式內 import） | `protocol` 72 模組、`state` 96、`client` 124；會**參照**到 `tkinter`（`launcher_progress`）、`UnityPy`（`auto_catalog`、`unity_textasset`）、`PIL`（`smallmaps`，僅 client），這些都是函式內的延遲載入 |

**解讀（推論）：** 「套件層」是網狀（network、core、services 互相引用），但「模組層」只有 26 個 services 模組真的成環；
`network/`、`core/`、`storage/` 本身沒有任何模組處在循環內。因此重新分層的難度集中在那 26 個模組，不是整個核心。

### 那 26 個循環模組

- `services.world`（20 個）：`auto_candidate_reader`、`auto_catalog`、`bundle_runtime_1275`、`catalog_adapters`、`catalog_compatibility`、
  `catalog_source_extractor`、`feature_resource_index`、`formal_candidate_bridge`、`launcher_catalog`、`npc_interact`、`npc_item_data`、
  `npc_shop`、`npc_talk`、`official_catalog_pipeline`、`preview_1275`、`resource_gap_diagnostics`、`resource_rebuilder`、`runtime_1275`、
  `unity_textasset`（官方資源管線、目錄與 NPC 資料）
- `services.items`（6 個）：`catalog`、`combat_resources`、`crafting`、`crafting_plan`、`inventory`
- 其他：`services.battle.battle_commands`、`services.expedition.data`

## 抽取建議

| 舊模組 | 量測 | 建議處置 | 狀態 |
|---|---|---|---|
| `network/wire.py` | 0 個依賴 | 規格 + 直接移植 | ✅ P0 golden 12 個 |
| `network/layouts.py` | 只依賴 `wire` | 規格 + 直接移植（`role_list`、`world_player` 已涵蓋；`battle_unit` 未涵蓋） | 🔄 |
| `network/protocol.py` | 傳遞 72 模組；`decode()` 先呼叫 `decode_chat`，再把 8 個子解碼器（instances、storage、expedition、recovery、guild、activity、crafting、tent）以 `or` 串起，之後還有 `decode_social`、`decode_live` 與大量內嵌分支 | 拆成純解碼層，每個封包群一個解碼器，不依賴 services | 🔄 P0 子集已有 golden |
| `network/live_data.py`、`social_protocol.py`、`expedition.py`、`instances.py`、`npc_dialogue.py` | 皆在 `network/` | 逐封包群納入 golden（P1 以後） | ⏳ |
| 解碼函式散在 services 內：`social.chat`、`social.guild`、`items.recovery`、`items.crafting`、`world.tent`、`items.room_storage`、`core.activity` | 解碼與規則混在同一檔 | 先把「解碼」與「規則」分離再移植 | ⏳ |
| `core/state.py`、`state_*_events.py` | `state` 傳遞 96 模組；`State.apply` 會呼叫各 service 的事件套用函式 | 重新設計：單一協程擁有狀態，事件處理器以註冊方式接入，不由核心反向呼叫 | ⏳ |
| `network/client.py`（`SessionLogic`） | 傳遞 124 模組 | **不抽程式**；行為已轉成 scenario | ✅ 9 個 scenario |
| `services/coordination.py` | 0 個依賴 | 下一個最容易的行為規格（互斥與暫停條件表） | ⏳ |
| `services/items/reservations.py` | 只依賴 1 個 network 模組 | 行為規格 + scenario（acquire／consumed／release／uncertain） | ⏳ |
| `network/connection_health.py` | 2 個依賴 | 行為規格 | ⏳ |
| 26 個循環模組中的資源管線與目錄部分 | 見上 | **留在 Python 工具端**產生資料包，Kotlin 只讀資料包（建議；尚未驗證可行） | ⏳ |
| `storage/`（DPAPI、路徑、帳號設定） | — | 不抽取，各平台各自實作 | — |
| `ui/`、`features/` | — | 不抽取，只保留主題與設計規範 | — |

## 尚未量測、不能假設的事

- `decode()` 的子解碼器以 `or` 串接，**順序可能有影響**：是否存在兩個解碼器都宣稱同一個 `(main, sub)` 尚未檢查。
- 各子解碼器的欄位佈局、嚴格程度與容錯行為（目前只有 P0 範圍有 golden）。
- 舊測試哪些可轉成 golden（0-4 尚未開始）。
- 26 個循環模組之中，哪些是「執行期核心規則」、哪些只是「資料來源」，需要逐檔閱讀才能切分，目前的分類只看檔名。

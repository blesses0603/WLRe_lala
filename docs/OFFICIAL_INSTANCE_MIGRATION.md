# 第七階段：官方副本與協力事件

本階段僅本機提交，未推送、未建立新 PR、未合併或發 Release。桌面及 Android 同步實作。`instance_catalog_1262.json` 已從種子 active／BLOB、Manifest、必要封裝清單及 initial_catalog 群組移除並 VACUUM；仍有 **15 項**種子，尚未達成完全無離線資料。

## 來源與資料庫

沿用官方版本前後一致性、Manifest／Bundle 大小與 checksum、精確 TextAsset 路徑及下載上限。兩端同步流程下載 `DungeonData_C`、`CooperateEventData_C`；共用 `instance_runtime` 將兩表與同版 Scenes／Text／Item 五份來源交給規範 SQLite，schema `instances-v1`。每次仍驗證 Bundle；命中後從 SQLite 回傳。原始資料按 hash 保存；僅在完全相同來源下重建損壞的衍生資料並存歷史。新來源解析失敗不覆蓋舊快照，失敗來源保存；不可用的新 Runtime 不會回退舊種子創房。

adapter 保留 `(id, para_kind)` 複合識別碼、16 槽位獎勵及旗標、協力事件資料；驗證重複 ID、場景、名稱、人數範圍與道具獎勵引用。具名協力使用事件 TextID，通用協力允許已驗證的 variant=1／npc_id=0。未知變體僅供查閱，不能創房。既有 Stage parser 未輸出開放旗標，因此 `is_open=None`，不猜測，也不把資料清單當作即時開放證據。

`official_catalog`／`entries_for` 改從當次 Runtime 的 SQLite 結果讀取並拷貝；預設完全不讀歷史 JSON／BLOB。冷啟動無資料時清單為空、創房停止；桌面及 Android 顯示等待同步，資料版本變更清除選擇。創房指令必須包含 catalog key、副本 ID、變體，網路核心重新比對當下資料，拒絕舊視窗選擇。協力 packet builder 支援明確變體，單獨 ID 不唯一時拒絕，不再取第一筆；人數與原有費用確認、待確認／逾時防重送守衛仍生效。既有使用者 DB 不刪除，已移除的活動不再出現在當次清單。

## 實檔驗證（2026-11-05）

官方 `1.3.23`、DataPackage `1296_2026_11_04_13_34_19_13`：29 筆副本、23 個單獨 ID、29 個複合 ID、2 筆協力事件。當前可列出 26 筆一般、2 筆協力、1 筆特殊副本。完整來源 hash：

| 表 | SHA-256 |
| --- | --- |
| DungeonData_C | 9dd32361f8e0c6006f7eff4d695e7b3e8debce1753a4fcca5d10a1b565987788 |
| CooperateEventData_C | 4adb067093d3961436065c1244bdf621e870ce0e320fbe4153f031ae6a37406e |
| ScenesData_C | 8417e6136c445c6a9cf3f1b66a429d2b52794e6c1fcd8424a75ec86ddfbb951c |
| TextData_C | 898876e43da2674a443d7dae13e74f2b8bbc09e6a69499ad2f0b5fe41cbe54db |
| ItemData_C | 5195d5ee8ae201dea55439274914930551176c3fcf50d735e03b09c5d04acbb4 |

兩端用實際官方 Runtime scoped injection 驗證公共讀取與選擇檢查，另以隔離 SQLite 驗證快取命中、衍生損壞修復、兩份副本來源各自截斷後拒絕並保留上一版。原檔保留在工作區 validation，未放入安裝包。沒有登入遊戲或發送正式服封包，沒有手機實機／APK 驗收。原協定實作與實際新版伺服器相容性仍須另行驗收。

## 剩餘 15 項及下一步

- `stage_coordinates.json`、`portals.json`：需全量座標／出口消費者及特殊場景驗證。
- `graph_origins.json`、`navigation_data.zip`：缺完整幾何重建與原點／投影驗證。
- `smallmaps.zip`：需官方圖像解碼入庫、映射及投影驗證。
- `item_icon_map.json`、`item_icon_coverage.json`、`item_icons.zip`：需同版全量圖集、裁切／旋轉映射及 UI DB 讀取。
- `emoji_catalog.json`、`emoji_images.zip`：缺 Emoji 表語意與圖集對應。
- `item_stackable.json`、`alchemy_catalog.json`、`combat_catalog.json`、`normal_attack_data.json`：缺完整欄位語意及跨表 adapter，官方 Lua 封裝尚無可靠解碼證據。
- `npc_battle_talk_1262.json.gz`：缺 NpcTalk 群組與同版文字關聯。

不能以移除尚無替代來源的種子造成功能缺失來宣稱完成。官方 UI PNG／程式圖示仍須另行分類，不包含於這 15 項。Lua 證據缺口及已排除的候選詳見第五階段文件。

## 測試

合成來源覆蓋複合鍵、歧義 ID、未知變體、遺失名稱／道具／場景、截斷來源、SQLite 命中／修復／失敗保留、Runtime 更新失效；真實來源驗證與上述測試分開。既有房間測試改用小型合成 fixture，不再依賴刪除的官方種子。

本機結果：桌面完整回歸 1,683 項（略過 165）無失敗；DISPLAY 副本相關 118 項通過，後續新增更新／冷啟動案例的 UI 檔 11 項及協力 UI 3 項通過。最後來源版本守衛變更後，副本相關 119 項重跑無失敗（無 DISPLAY 略過 25）。

Android 完整隔離回歸 173 個檔案退出碼皆為零，輸出可計數 1,362 項、略過 4；部分 Kivy 測試將 unittest stderr 接至 logger，計數不代表所有已執行案例。Android 副本頁另以 stdout runner 明確驗證 4 項（含冷啟動無選項）通過。兩端實檔驗證皆通過。桌面 repository audit 通過；Android 通用 audit 的既有版本表示限制未更改。本階段沒有遠端 CI。

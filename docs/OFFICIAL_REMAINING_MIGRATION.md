# 第三階段：製作配方與剩餘資源核對

本機分支接續第二階段，尚未發布；不是無離線資料版本。種子由 23 項減至 22 項。未知格式仍拒絕解析，不推測欄位或拿舊資料代替新版本。

## 製作配方完成事項

`crafting_catalog.json` 已自種子 active 和 BLOB 表刪除並 VACUUM，打包清單與來源清單同步移除。啟動時 `RECIPES` 為空；既有完整官方 Runtime 經 Bundle checksum、二進位解析、規範 SQLite 及跨表驗證後，才原地發布配方字典。UI 既有 catalog token 刷新與資料來源提示沿用。測試資料改用明確的合成配方，沒有把舊官方 catalog 搬進測試或程式常數。

2026-11-05 真實來源 `1.3.23` 在沒有舊配方種子的狀態下成功發布 1,019 個成品索引；這是依成品整理後的索引數，與 1,026 筆原始 Smith 配方紀錄不同。使用現有可驗證 Bundle 快取與規範 SQLite，未登入遊戲或送封包。

桌面收藏不再因官方配方暫時缺失而濾掉既有 ID。Android 收藏／方案儲存改以資料結構驗證保留草稿，實際加入執行清單仍經 `validate_rows`、配方可用性及原有封包閘門驗證。來源更新失敗不自動執行或重送。已有 Runtime 更新流程會撤銷 active 指標，舊 snapshot 留存供稽核，不能繞過版本閘門強行啟用。

## 23 項逐項核對

以下官方路徑基於已下載且前階段校驗的 1296 Manifest 再解析；DataPackage 190 assets／22 bundles，MainPackage 21,708 assets／1,733 bundles。`Data/` 表示 `Assets/ResourcesBuild/Data/`。表格中的候選來源不等於已完成目前版本語意驗證，也不表示可用固定 URL 直接下載 TextAsset；必須從 Manifest 解出 Bundle 與依賴後驗證。

| 種子項目 | 官方資產／真實已知格式 | 消費端、缺口與本階段結果 |
| --- | --- | --- |
| crafting_catalog.json | Data/SmithData_C.bytes + ItemData_C.bytes；現有 Smith 與 Item 嚴格 parser | crafting.RECIPES，規範 DB 已接；本階段移除種子完成 |
| expedition_catalog.json | Data/AdventureData_C.bytes、AdventureLvData_C.bytes、NpcData_C.bytes、NpcCareerData_C.bytes、TextData_C.bytes；現有定長／變長欄位 parser | expedition/data.load_active_catalog 已用 Runtime；load_catalog 舊展示／測試入口仍讀種子，尚需取消及冷啟動 UI 遷移 |
| npc_event_index_1262.json.gz | Data/Eve.bytes；Eve 場景／NPC 事件結構已有 parser | NPCIndex 的 1262 分支仍讀舊 gzip JSON；正式 Runtime 已用規範 DB，舊分支與初始化種子組依賴待移除 |
| npc_interact_1262.json.gz | Data/Eve.bytes；互動索引已有 parser | npc_interact 的舊來源與 initial_catalog 組仍依賴種子；需消除整組預載及更新失敗測試 |
| npc_talk_1262.json.gz | Data/TalkData_C.bytes；ID、UTF-16LE 文字與 voice 欄位已有 parser | npc_talk 正式入口走 Runtime，1262 路徑和初始 catalog 仍需遷移 |
| npc_text_1262.json.gz | Data/TextData_C.bytes；ID、UTF-16LE 長度字串已有 parser | Runtime 文字已入 DB；npc_localization.load_text_data 仍可讀舊 gzip，須連同 battle talk 消費端核對 |
| npc_battle_talk_1262.json.gz | Data/NpcTalkData_C.bytes 存在 | npc_localization.load_battle_talk；舊 records 為戰鬥群組，尚未驗證新表等價語意及群組文字關聯 |
| instance_catalog_1262.json | Data/DungeonData_C.bytes、CooperateEventData_C.bytes、ScenesData_C.bytes | instance_catalog 已有 parser，instance_browser.official_catalog 仍鎖定舊 30 筆／分類筆數；需新版本同批解析、名稱與獎勵關聯驗證及 UI 換源 |
| map_names.json | Data/ScenesData_C.bytes + TextData_C.bytes | 已有 scene parser，舊地圖名稱／模型字典與使用者目前地圖版本關聯仍待遷移 |
| stage_coordinates.json | Data/StageMapData_C.bytes、ScenesData_C.bytes | coordinates、obstacle_scope；部分 Runtime 座標不等於所有投影／障礙場景等價，須逐欄核對 |
| portals.json | Data/Eve.bytes、EveDoorLinks.bytes、DoorLinkData_C.bytes | portals 含舊 entities、出口及來源稽核；正式門表已有 parser，特殊出口／舊導航 consumer 未全遷移 |
| graph_origins.json | 來源為場景幾何衍生的模型原點字典；尚無驗證完畢的直接官方表 | coordinates 與導航投影相依，缺目前版本完整重建與座標比對 |
| navigation_data.zip | ZIP 中 catalog.json 和各 Mesh JSON 為衍生資料 | navigation.Mesh；Main Manifest 沒有名稱含 NavMesh 的項目，但不能推論場景 Bundle 不含幾何。缺完整可驗證解碼及導航重建流程 |
| smallmaps.zip | Main 的 Texture/SmallMap2D/SmallMap2D_*.png，562 個路徑 | smallmaps.SmallMaps 仍開 ZIP 的 image_index.json/PNG；需 Unity 圖像解碼、DB 圖像表、模型映射及投影驗證 |
| item_icon_map.json | Main 圖集 + Data/ItemData_C.bytes 候選 | crafting/item_icons import-time 字典；item ID 與 sprite name 的目前版本全量對應未驗證 |
| item_icon_coverage.json | LaLa 對圖集映射產生的 coverage 報告，非獨立官方原始表 | 須由成功匯入的 mapping/image 表重算；不得直接假定舊 fallback ID 仍適用 |
| item_icons.zip | Main Unity sprite／texture 資產；現有 ZIP 是轉出的 PNG | ItemIcons 仍開 ZIP；缺目前版本全量 atlas 座標／旋轉／裁切解碼、image DB 與 UI 消費者遷移 |
| emoji_catalog.json | Data/EmojiData_C.bytes | entries／image mapping 是衍生 JSON；須核對 Emoji ID/token 與 atlas 語意 |
| emoji_images.zip | Main Sprite/Atlas/SpriteAtlas_Emoji/SpriteAtlas_Emoji.spriteatlasv2（另有 Emoji_SC） | 圖像解碼入庫與 token 到 sprite 全量對應尚未驗證；不能用 SC 圖集默認替換 |
| item_stackable.json | Data/ItemData_C.bytes 候選 | core/inventory_updates.STACKABLE import-time；現有 Item parser 不提供經核對的所有堆疊語意，不能猜欄位 |
| alchemy_catalog.json | Data/ItemData_C.bytes 候選；AlchemyTalkData_C 僅名稱相關不能當配方證據 | alchemy.META import-time；缺材料分類／鍊金計算欄位語意驗證 |
| combat_catalog.json | Data/SkillData_C.bytes、SkillMotionData.bytes、NpcData_C.bytes、ItemData_C.bytes 等候選 | items/catalog.CAT 的技能、物品、NPC、角色、元素權重跨功能依賴；目前未有全量等價 adapter |
| normal_attack_data.json | Data/ItemData_C.bytes、NpcData_C.bytes 等候選 | battle/combat.DATA 的武器／NPC／捕捉網欄位須實證，不能從欄位位置或命名推論 |

## 尚需完成

22 項仍保留可用舊資源；已確認有資料表的部分優先取消舊載入，但須一起解決初始 catalog 的成組校驗、UI 冷啟動、版本更新與既有使用者狀態。圖像、導航和戰鬥語意缺口不能靠移除檔案解決。應用圖示與官方 UI PNG 也仍需單獨分類，不包含在上述 22 項計數。

第二／三階段均只在本機。Android 的 seed lock 必須指向含縮減種子的桌面提交；發布順序仍須桌面先、Android 後。未進行實機、APK 或正式服驗收。

## 本機測試結果

- 桌面全套 1,673 項通過（略過 163）；製作 GUI 8 項及刪除種子後冷啟動／GUI 3 項通過。
- Android 隔離執行 170 個檔案，共 1,351 項（略過 4）：初跑兩檔失敗；其中依賴舊配方的 features 測試修正為合成 fixture 後 15 項通過。另一項既有 socket 權限時序測試未改程式，單檔重跑 11 項通過，保留這次偶發失敗紀錄。新增冷啟動與草稿保護測試 4 項通過。
- 共用核心 166 檔來源核對通過；以上均非第三階段遠端 CI 或手機實機結果。

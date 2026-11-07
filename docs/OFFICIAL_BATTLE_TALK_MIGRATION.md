# 第八階段：已知官方戰鬥台詞來源與剩餘資料查證

本階段僅本機，未推送／合併／Release。兩端移除 `npc_battle_talk_1262.json.gz` 種子，剩 **14 項**。`initial_catalog.NAMES` 已為空，舊工具保留空 schema 相容能力，不再封裝該群組遊戲資料。既有使用者 SQLite／明確指定歷史檔案的驗證工具不刪除。

## 可證實的戰鬥台詞遷移

2026-11-05 重新由官方版本、DataPackage Manifest、已校驗 Bundle 及精確 TextAsset 路徑取得 `NpcTalkData_C`，前後官方版本一致。原檔 944 bytes，SHA-256 `9de2f789e7f194148959457e7a1fc4744bf3378d62fdaff54ce51efe28499bb8`，與 repository 先前獨立記錄的 1262／1275 原表指紋完全一致。

使用既有已審核 16 組／94 筆索引作獨立對照：以 little-endian UInt32 筆數、每筆 `<HIBHB>`（群組 UInt16、TextID UInt32、kind UInt8、parameter UInt16、duration UInt8）讀取的所有欄位與 94 筆原索引完全一致；按群組數值排序保留組內順序重編碼後，與官方 944 bytes 逐位元組相同。最初沿 JSON 字典的字串鍵順序重編碼不一致，改以原表的數值群組順序後完整相同；沒有更改原檔或欄位值。這是**已知相同原表的全量比對**，不是推測未知 Lua 封裝。

`npc_battle_catalog` 公開 parser 強制核對上述完整指紋；任何新來源 byte 改變都停止，不因長度或欄位看似合理就放行。解析結果與同版 TextData 關聯驗證後，以 `npc-battle-talk-known-v1` 存入規範 SQLite。兩端官方同步均納入原表下載、Bundle 驗證、raw／derived 保存與交易；`load_battle_talk()` 只讀當次 Runtime DB 結果、回傳深拷貝，未知來源或冷啟動明確失敗，不回退舊種子。桌面新 parser 已註冊自動診斷，官方 parser audit 也納入該表。

兩端實檔測試：1296 Runtime 讀回 **16 組、94 筆，94 個文字引用均可由當次 TextData 解出**；公共讀取、拷貝隔離與來源變動拒絕通過。只以 scoped injection 提供真實 Runtime，沒有登入遊戲、送正式服封包、執行 Lua 或手機驗收。原表與比對結果保留於工作區 `validation/remaining-resources-1296/`，未加入安裝包或 Git。程式只包含已知來源指紋與格式，不搬入舊台詞索引。

## 14 項逐項缺口與可操作下一步

| 保留項目 | 本次已確認來源／消費者 | 還需完成的證據或工作 |
| --- | --- | --- |
| stage_coordinates.json | ScenesData 已有當次模型、尺寸、offset；Coordinates.mapping 仍比對歷史 geometry，使用舊 offset_y | 逐場景核對 offset_y 與模型 geometry 的轉換，包括 65535 sentinel／特殊場景；不可只替換數字讓舊網格通過 |
| graph_origins.json | Coordinates 依各模型原點轉換 packet XY 與 Int3 XZ | 需同版 Scene/NavMesh 解碼與 vertex/bounds 全量重編碼誤差證據 |
| navigation_data.zip | Main Manifest 有 775 個 .unity；Repository/Mesh 仍讀衍生 ZIP | 當次 Scene 相依循環先解決，再建立同版 geometry 解碼及完整可重現路由驗證 |
| portals.json | 當次 Eve／EveDoorLinks／DoorLink 部分已讀 Runtime | 核對全部舊 entities、特殊出口與消費者；缺正式映射時維持原限制，不把顯示目的地當可送封包的事件 |
| smallmaps.zip | Main 明確有 562 個 Texture/SmallMap2D/SmallMap2D_*.png；完整下載計畫為單一 Bundle，43,187,027 bytes | 現行自動同步 32 MiB 上限不足。需要獨立有界圖像同步政策、精確 Texture2D 解碼／像素驗證、DB 圖像表、兩端 UI 讀取與同版 model／投影驗證。這是尚未實作的流程，不是官方沒有提供檔案 |
| item_icon_map.json | 確認 Main 路徑 Assets/ResourcesBuild/Sprite/Sprite_Item/s1000.png 存在 | 仍需同版 Item ID 到 sprite 的完整欄位語意；不能只用檔名或沿用舊 fallback ID |
| item_icon_coverage.json | 衍生的 mapping／image coverage 報告 | 待映射及圖像成功入庫後從 DB 重算，不能把舊報告當新資料 |
| item_icons.zip | Sprite_Item 資產存在，桌面 ItemIcons／Android 對應 UI 尚讀舊圖像 | 完整相依 Bundle、Sprite 裁切／旋轉、圖像 DB 與兩端快取失效驗證尚未完成 |
| emoji_catalog.json | 當次 EmojiData_C 500 bytes，SHA-256 b21c48d487d83463332157e1d56af0a258f26cecf2e906ca518526badcd5a75b；原檔已保存 | 未推測 8-byte 欄位，需核對完整 token 行序、icon ID、mark／show 條件與當次圖集；Lua 仍為未識別封裝 |
| emoji_images.zip | Main 明確有 SpriteAtlas_Emoji.spriteatlasv2，下載計畫被相依循環拒絕 | 確認 YooAsset 2.2.5 循環語意並以真實 Manifest 回歸後，才能實作相依閉包下載與 atlas 解碼；不略過依賴或替換 SC 圖集 |
| item_stackable.json | inventory_updates 使用堆疊布林及 200 上限；Item parser 尚未輸出已核對 CanOverlap | 需要同版 CanOverlap 欄位或可核對來源／測試向量，覆蓋全物品，保留 server_stackable 與未知物品安全處理 |
| alchemy_catalog.json | alchemy.META 依 spares、CAT kind/special/restrict；不僅物品名稱 | 缺目前版本 spares／材料分類完整語意與跨表驗證；AlchemyTalk 不能當配方來源 |
| combat_catalog.json | Skill／SkillMotion／Npc／Item 原表候選存在 | 缺技能、角色、元素權重等全量 adapter 與版本一致性證據；不能以名稱相同推斷欄位 |
| normal_attack_data.json | battle/combat 消費武器、NPC、捕捉網欄位 | 需目前版本相關欄位及戰鬥公式的獨立來源與測試向量，不猜二進位偏移 |

## 相依循環的具體證據

既有 `build_update_plan` 對已驗證 Main Manifest 回傳 `YooAsset dependency cycle`，目前沒有修改其 fail-closed 行為：

- Emoji：`mainpackage_atlas.bundle` → `mainpackage_share_assets_resourcesbuild_sprite_sprite_bricktreasure.bundle` → `mainpackage_atlas.bundle`。
- 場景 `M10001.unity`：`mainpackage_model_10_npc.bundle` → `mainpackage_model_10_npc_static.bundle` → `mainpackage_model_10_npc.bundle`。

下一步應先依 YooAsset 對應版本的原始碼／格式說明確認這是允許的閉包而非解析問題，再用該 Manifest 的確切案例測試有界循環處理；不能為了下載而直接刪除依賴。工作區 `remaining-assets-plans.json` 與 `dependency-cycles.json` 記錄本次計畫及路徑。

Lua 六份實檔依舊缺同版可讀格式／可靠解碼器；所需證據詳見第五階段文件。這個缺口不阻止已知 byte-identical NpcTalk 原表的限定遷移，但不授權一般化解碼。官方 UI PNG／應用圖示也仍須另列分類；沒有宣稱零離線資料或完整正式服相容性完成。

## 小地圖追加實檔查證

使用既有下載器的獨立 64 MiB／4 檔上限作只讀查證（未改應用程式 32 MiB 自動同步預算），取得並校驗 43,187,027-byte Bundle。驗證 UnityFS header、逐一使用 Manifest 精確 AssetPath 尋找物件，562 個資產全部為 Texture2D，全部成功解成 1024×1024 RGBA（原 texture format=10）；逐張像素 SHA-256 保存於工作區 `remaining-resources-1296/smallmap-full-decode.json`。前後官方版本一致，沒有略過 Bundle 相依或校驗。

例如 SmallMap2D_10001 的 RGBA 像素 SHA-256 為 `3ed908481e13682286f0004831d45a0d3f0e84c8884e2f00c580d75fabccf3d2`。目前已消除基本圖像格式／解碼可行性的疑問，但尚未完成圖像 DB 的交易／版本／失敗回滾、兩端 UI 換源與同版場景投影驗證；不能稱 smallmaps.zip 已遷移。此項是具備可靠來源、可接續實作的下一階段，不是外部權限阻擋。

## 本機測試結果

- 桌面完整 1,689 項，略過 165，無失敗；補入新 parser audit 後診斷 14 項通過。
- Android 完整隔離回歸 174 個測試檔退出碼皆為零，可計數 1,368 項、略過 4；另 NPC 相關 62 項通過。Kivy logger 可能接管部分 stderr，因此可計數數字不是全部實際執行案例總數。
- 168 個共用核心來源核對通過；Android 新 parser 與桌面唯有 diagnostics decorator／checkpoint 差異，已在 source lock 明示。
- 桌面 repository audit 通過；Android 通用 audit 既有版本表示限制未改。兩端當次官方原檔及 94 個 TextData 關聯驗證均通過。未執行本階段遠端 CI、APK、手機或正式服驗收。

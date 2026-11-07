# 官方資料規範化與安全復原（第一階段）

最終目標是安裝包不包含離線遊戲資料，首次啟動由官方下載、驗證、解析並寫入本機資料庫。本次只完成共用 Runtime 的規範資料庫與來源主機選擇；**尚未移除種子資料庫，也不能宣稱已完成官方來源全替換**。

## 已接上的資料流

既有啟動／登入前同步 → 官方版本表 → `.hash`／`.bytes` Manifest → 有界 Bundle 下載與 MD5／CRC 驗證 → TextAsset 擷取 → `load_parsed` → SQLite 規範結果 → Runtime 既有跨表檢查 → 既有登入版本閘門。

桌面和 Android 的 NPC、互動、物品、對話、文字、配方、場景、門事件、遠征任務及夥伴資料使用同一規範資料庫程式。桌面每日、組織、方舟可選資料也接入；Android 尚無相同的三組可選功能入口，沒有假裝完成對應移植。

- 儲存在使用者 `official_sync/derived_catalogs/resource_inventory.sqlite3`，新增 `normalized_*` 表，不改動已有 inventory、bundled、帳號表。
- Schema 1 使用帶型別的 JSON，保留整數／tuple key、tuple／list 差異。無 pickle、動態程式載入或執行官方 Lua。
- 每個 snapshot 由完整 catalog identity、feature、parser schema 及來源 SHA-256 綁定；同一身分不能換 bytes。修改解析器語意時必須提升對應 schema ID。
- 首次解析結果經無損 round trip 後，與原始 bytes 在 SQLite 交易中保存；後續讀取規範資料，不重跑該二進位解析器。每次仍先獨立驗證官方 Bundle，規範資料庫不成為來源信任憑證。
- 缺少 snapshot 會建立；規範 JSON 損壞則從當次相同的已驗證來源重建，將舊規範 bytes 記入 history。原始資料庫損壞、未知 schema 或同一 identity 變更都拒絕，不自動修改原始 bytes。
- 解析失敗保留來源、失敗狀態及舊 snapshot；不猜 offset、長度或欄位，不以舊 catalog 靜默替換新版本。多來源 feature 必須全部解析成功才原子發布。不同 feature 的候選 snapshot 不等於 Runtime 啟用，全部既有 Runtime 驗證通過才返回可用物件。
- 舊 catalog／舊 parser schema 的 snapshot 保留；回到經官方驗證的同一舊版本即可讀取舊 snapshot。沒有可繞過當前版本閘門的「強制回滾」開關。
- 開啟未知新資料庫 schema 時拒絕，避免舊程式降版覆寫。現有舊 inventory 於首次使用時增設新表，不刪除資料。

診斷命令（唯讀，不下載、不修復、不啟用遊戲操作）：

```sh
python -m tools.check_resource_database
```

會列出每個 feature 的來源 hash、schema、完整性狀態，以及最近 100 筆 `imported`／`parse_failed`／`repaired_derived`。不輸出解碼文字或原始遊戲資料。修復必須由下一次正常來源驗證流程執行。

## 已實測的官方來源（2026-11-05）

使用者提供的 `https://wlreftpsrc.chinesegamer.net/WLN/TW/` 目錄、PC／Android 版本表均回 HTTP 200。`1.3.23` 含 `ResourcesPC`、`ResourcesAndroid`、`ResourcesIOS`、`LuaScripts`；PC 子目錄含 `ServerList.txt`、`Config.txt`、`VerifyServer.txt`、`AssetBundle`。執行期不靠掃目錄猜 Bundle URL，而從驗證後 Manifest 選擇明確相依項。

兩主機選擇只能是已確認的 `wlreftp.chinesegamer.net` 或 `wlreftpsrc.chinesegamer.net`；保留既有預設，新主機以程序啟動前設定選用：

```sh
WLRE_OFFICIAL_RESOURCE_HOST=wlreftpsrc.chinesegamer.net python -m tools.check_official_manifests
WLRE_OFFICIAL_RESOURCE_HOST=wlreftpsrc.chinesegamer.net python -m wlre.services.world.dynamic_bundle_runtime --sync
```

Windows PowerShell 先設定 `$env:WLRE_OFFICIAL_RESOURCE_HOST='wlreftpsrc.chinesegamer.net'`，再執行同一 Python 模組。主機選擇涵蓋版本表、Manifest、Bundle 和 Lua 清單，不自動跨主機重試。保留 TLS、路徑、回應容量、版本、checksum 和轉址檢查。來源主機以通用 MIME 提供版本／hash，舊版限縮 Accept 會收到 406；此次接受通用 MIME，但仍嚴格解析內容。

真實線上測試：DataPackage `1296_2026_11_04_13_34_19_13`（190 assets／22 bundles，CRC `cd17f38f`）；MainPackage `1296_2026_11_04_13_36_07_72`（21,708 assets／1,733 bundles，CRC `35df8b9a`）。桌面成功以官方 Bundle 建立規範 Runtime：NPC 11,014、商店互動 1,637、物品 11,366、配方 1,026、場景 1,337、遠征任務 260。Android Python Runtime 也成功讀取同一官方版本與規範資料。這是主機上的資料路徑測試，不是 Android 實機／APK 或正式服驗收。

## 27 份種子內容的移除前缺口

| 現有種子內容 | 官方來源／處理狀態 | 移除前仍需完成 |
| --- | --- | --- |
| `crafting_catalog.json`, `expedition_catalog.json` | Smith／Item、Adventure／Npc／Text 已有目前版本 Runtime | 移除 import-time 舊資料載入；冷啟動須先等同步結果 |
| `npc_event_index_1262.json.gz`, `npc_interact_1262.json.gz`, `npc_talk_1262.json.gz`, `npc_text_1262.json.gz` | Eve／Talk／Text 已有目前版本 Runtime | 完全停用舊索引 fallback，測試乾淨安裝與更新失敗 UI |
| `npc_battle_talk_1262.json.gz` | 舊 battle talk 索引 | 確認新 NpcTalk／Eve 對應欄位與 consumer，尚未驗證等價來源 |
| `map_names.json`, `stage_coordinates.json`, `portals.json` | Scenes／Text／Eve／StageMap／DoorLink 已有部分目前版本供應 | 舊座標／出口 consumer 與特殊場景仍需逐項遷移 |
| `graph_origins.json`, `navigation_data.zip` | 場景幾何與衍生導航 | 缺已驗證的完整重建流程；目錄存在不能證明 Unity 內建 Mesh／座標均可重建 |
| `smallmaps.zip` | 1296 MainPackage 列有 562 個 SmallMap 資產 | 目前仍讀隨附 archive；需下載、圖像解析入庫與場景投影驗證 |
| `item_icon_map.json`, `item_icon_coverage.json`, `item_icons.zip` | 官方 MainPackage 圖集 | 尚缺目前版本 atlas／sprite 到 item ID 的全量解析、匯入與 UI 遷移 |
| `emoji_catalog.json`, `emoji_images.zip` | EmojiData 與 SpriteAtlas_Emoji 在 Manifest 中 | 尚缺目前版本 mapping／atlas 規範匯入及 UI 遷移 |
| `item_stackable.json`, `alchemy_catalog.json`, `combat_catalog.json`, `normal_attack_data.json` | Item／Skill／SkillMotion 等表在 Manifest 中 | 現有 Item parser 只保留已審核欄位；缺完整戰鬥、堆疊、鍊金規範 adapter 與語意測試，不能由欄位位置猜值 |
| `server_list.json` | PC `ServerList.txt` 存在 | 尚需 schema、伺服器分組、更新與登入 UI 整合 |
| `default_profile.json`, `enums.json`, `lala_supported_resources.json` | LaLa 預設設定、協定實作／相容性政策 | 應遷為程式設定／常數，不可把官方下載資料當成允許登入或執行封包的政策 |

此外 `wlre/resources/assets` 仍包含官方 UI PNG 與 LaLa 圖示；須區分程式圖示與需改為官方下載的素材。Android 的 `android_resource_seed.py` 仍從固定桌面 Git commit 還原種子，打包與 CI 也仍要求種子；本次未刪除或弱化這些檢查。故本分支是可審查的第一階段，**未達到無離線資料檔安裝包的最終驗收**。

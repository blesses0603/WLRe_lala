# 1275 官方資源更新｜第一階段：唯讀 NPC 索引

基準：桌面版 main 的程式版本 v0.5.17，原遊戲資料基準 1262。

## 已驗證的 1275 表格

| 原始 TextAsset | 1262 筆數 | 1275 筆數 | 1275 原始 SHA-256 |
|---|---:|---:|---|
| TalkData_C | 29,873 | 29,890 | e111fe662cb6909aa9df650c4a9735a828440cbed3c6c5794381bd1721e2fbbb |
| TextData_C | 39,901 | 39,947 | 5c61277ec3044616938db58750cba116e623f66e01f33aef4f98a72d88204ea4 |
| ItemData_C | 11,287 | 11,304 | 98a9b90494c1ba20d9b29a5bd4d453bab7540c7a8529551717719d4fc8ee73e8 |

資料來自使用者提供的 1275 FullDiff，已依 1262 Lua 欄位規格逐筆解析、確認唯一 ID 及 EOF。筆數成長不代表相同數量的純新增資料；原有 ID 也可能異動。

1275 NpcTalkData_C 的原始 SHA-256 與已核對的 1262 原始表相同，不重新生成該來源索引。

## 1275 獨立資源

由離線分析工具另行提供 WLRE_1275_索引包.zip，內含：

- npc_talk_1275.json.gz（29,890 筆）
- npc_text_1275.json.gz（39,947 筆）
- npc_item_data_1275.json.gz（11,304 筆）

資源包不提交至公開 GitHub 倉庫，不會取代 1262 索引。

## 先驗證、再手動安裝

在已取得這個 PR 程式碼的 LaLa 專案根目錄執行：

~~~powershell
py -m wlre.services.world.npc_1275_assets "C:\下載路徑\WLRE_1275_索引包.zip"
~~~

預設只檢驗 SHA-256、檔案大小、版本、來源 SHA、筆數及欄位型別，不寫入。

~~~powershell
py -m wlre.services.world.npc_1275_assets "C:\下載路徑\WLRE_1275_索引包.zip" --destination ".\wlre\resources" --install
~~~

須明確帶入 --install 與資源目錄才會安裝；不覆寫任何已存在的 1275 索引，更不修改舊版 1262 索引。對已安裝檔案可透過 load_read_only 單獨讀取，並不會對 NPC 發送封包。

## 必須暫緩的功能

1275 Eve Bundle 已異動，但尚未逐筆重建 EventData.NewNpc、EventData.NewInteract 的事件索引，因此第一階段不能安全切換 NPC 的 C20-1/C20-9 互動，不會開啟真實 NPC 買賣。1275 檔案安裝完成也不代表桌面版 LaLa 已啟用新資料版本。

下一階段將依序核對 NPC 事件、每日任務、傳點、物品及商店資料，再決定是否切換對應的執行期讀取器。正式伺服器 E2E 尚未驗收。

## 測試

~~~powershell
py -m unittest discover -s tests -p test_npc_1275_assets.py -v
~~~

先前已在隔離 Python 測試環境實際執行四項校驗測試；GitHub CI 與 Windows/macOS 真正遊戲環境仍須另外驗收。此 PR 只新增驗證與安裝工具、測試、文件，沿用 v0.5.17，沒有發布版本。

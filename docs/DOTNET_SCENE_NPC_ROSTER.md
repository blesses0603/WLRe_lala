# ver 8.0.77 當前場景 NPC 名單接線

盤點：表情正式流程仍受必要表／表情 owned-source 聯集上限限制，需要獨立分階段解碼，不能直接增加額度。另一個可獨立驗證的缺口是 NPC 名單：已驗證 Eve／NpcData 已可取得，Avalonia 地圖 NPC 頁卻仍顯示等待。本批完成後者，不改變表情限制或一般遊戲操作權限。

## Python 語意與 Core

對照 `wlre/services/world/npc_catalog.py` 的 `scene_npcs`／`display_name`：只採當前 Eve 的 `EventData.NewNpc` 名單，不載入歷史地圖 marker，也不藉名稱、NPC ID 或列序猜事件索引。保留原列順序、ushort index（含 0）、uint NPC ID／座標及所有 byte event IDs（含重複）。同 NPC ID／名稱可有不同索引，不能合併。

名稱只讀同次 publication 的 ReviewedNpcs（已通過固定原文 SHA 與完整 layout 驗證）；無名稱時為 `NPC #id`，空白不 trim，依 Python `[:100]` 以 Unicode code point 截斷。Eve 目前投影沒有事件名稱／buy_kind／base_define 欄位，本批不猜測補入。原生座標僅是資料表參考，不是即時 NPC 位置，也不畫成地圖上的即時實體。

`SceneNpcRosterRequest` 只可由當前資源／帳號流程取得；讀取前後核對 activation、帳號快照、接收 attempt、場景及同一 catalog reference。資源撤銷、停止、帳號或場景變更即拒絕。回傳 immutable rows 仍是歷史觀察，CanSendPackets／CanInteract 永遠 false。單場景 4096 列，重複索引、ID 0、未初始化或超過 255 個事件欄位拒絕整份名單；已知空名單和來源不可用分開。

activation 只快取一個場景的 immutable rows，換場景替換；不逐次 UI 刷新重建名稱／列。桌面讀取還綁定同一 ServiceStateSnapshot。相同 identity 保留 ItemsSource 與選取；不同來源、200 ms 撤銷檢查、視窗關閉清除列與選取並停止 timer。NPC 詳情標示索引、ID、座標參考和事件數；既有互動／接續／更多操作仍停用。

## 驗證與限制

新增 Core 測試涵蓋順序、同 ID 不同索引、uint 極值、事件重複與空值、名稱 fallback／空白／Unicode、容量與整份拒絕、空名單與讀取中撤銷。既有 synthetic loopback 整合增加目前／其他場景、資源撤銷及未啟用資源的檢查；white-box admission seam 明示只是接線測試，不證明官方來源。

原生 NPC UI 8 項涵蓋未就緒／已知空名單區分、保留不同索引、10 次刷新重用同一 ItemsSource 與選取、撤銷清除、晚到讀取及關閉後拒絕。沒有模擬成已完成 NPC 對話、選單、商店、移動或怪物分布。正式帳號及遊戲畫面仍待使用者手動驗收；本批不連遊戲服務、不使用真帳密。

## 官方資源唯讀比對

2026-11-09T23:44:27Z，以未注入 source／信任旗標的 production owner 在既有私有資源目錄刷新，DataVer 1.3.23，ResourceAdmitted／SourcesRechecked=true，小地圖新增下載 0；讀取現有官方 Data／Main 1296 套件。為 Stage 表中的 1,337 個場景取得名單，共 10,676 列，其中 216 場景為已知空名單；每個場景重取時 immutable rows 相同。owner Dispose 後保留 request 拒絕讀取。沒有帳號、遊戲 socket 或命令。

獨立 Python `eve_v115.derive_eve_index` 從同一 SQLite 內原始 Eve bytes 重新解析（SHA `74a59b7905c743411a314f4af744980a28f843025a278aa76fe813d3c8c8f522`），NpcData 先通過 Python 固定 SHA／layout 驗證，再依 `combat_catalog.build_catalog` 的 Reader 欄位取得名稱，最後執行真實 `npc_catalog.scene_npcs(scene, [], index)`。全部 10,676 列的順序、索引、ID、名稱、x/y、事件 ID、事件數及來源完全一致；CanInteract 均 false。

完整 Eve 索引自身有 1,262 個場景／11,014 列；本入口只為當前 Stage 表存在的場景提供名單，不把其他 Eve 場景猜成副本別名，因此沒有宣稱呈現所有 Eve 列。官方 raw／名單 JSON 僅在私有診斷目錄，repo 只記錄數量、方法與來源雜湊。這是正式資源層的正向比對，不代表正式帳號場景接收或 NPC 對話已驗收。

最終強制重建零警告／錯誤，完整 Core **45,914**（新增 13 項）通過。Desktop Release 零警告／錯誤、離線 **81**，原生主流程 **198** 加 NPC **8**、小地圖 **10**、頭像 **13**、表情 **24**、catalog **10**／資源確認 **6**／登入 loopback **11** 通過；公用 Core consumer 與 Python 倉庫／UnityPy 包裝 **9** 通過。

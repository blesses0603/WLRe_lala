# ver 8.0.76 小地圖座標映射與正式資源驗證

## 固定來源工廠

`SmallMapReceiptBatch` 只接受已解析 MainPackage manifest、固定受審查版本、cache reader 及精確相符的 receipt 集合。工廠自己衍生完整每圖閉包、根 Bundle、來源與 manifest 指紋，沒有接受 caller pixels、serialized object bytes、任意 decoder 或自稱來源指紋的 production overload。

新的 `CreateStagedSmallMaps` 是磁碟 receipt 計畫，最多 4 檔／64 MiB。既有 `CreateSmallMaps` 的 32 MiB owned-source 額度完全不變，原有 production 額度不變；新增明確獨立的 4 檔／64 MiB 磁碟階段。receipt 必須含有效小寫 SHA256，不能以 null 觸發 optional SHA 跳過。所有來源在消費前後重新核對，範圍讀取仍核對同次完整掃描捕獲的 64 KiB 區塊 hash。

每個 root 最多一個 SerializedFile，保留 16 MiB serialized slice 限制；完整驗證 type tree、metadata、物件索引／跨度與 container，再投影此 root 所需的精確小地圖路徑。只接受本檔且 class 28 的 Texture2D 指標；不猜外部指標、名稱 fallback、場景座標。必要 Texture descriptor 保留既有格式驗證，像素使用精確 owner 的 `.resS` 路徑與範圍讀取。舊一般 SerializedFile／Texture 入口仍驗證完整物件。

`UnityImageObjects.TextureAsync` 與同步入口共用 descriptor 解析；載入前先核對尺寸、mip、格式、完整 payload 長度及 stream span。小地圖只接受 1024×1024、sRGB、RGBA32／DXT1／DXT5，沿用既有翻轉與區塊像素解碼。PNG 有界且私有複製，candidate 仍為 `HasVerifiedProvenance=false`。

## 整批 SQLite

`ConsumeAsync` 按 root 分組，重用同一已驗證來源／索引／metadata，逐張解碼交付 PNG。若同一 root 有兩張地圖，整批只開三次來源（前查、消費、後查），不是逐圖重開；測試實測此開啟次數。這是 I/O 次數驗證，不宣稱時間或應用程式 heap 改善數字。

`SmallMapPngStore` 原子交易中逐張寫入並回讀，或獨立由固定工廠重新解碼並比對既有 cache。嚴格核對唯一 schema、model、source、asset、pixel SHA、PNG SHA、完整 PNG bytes 及總列數；不解壓不可信 stored PNG，也不將資料庫 hash 當像素真相。每張 PNG 最多 4 MiB，整批最多 96 MiB、2048 張，一般寫入／檢查逐張消費不保留整批 PNG／RGBA；發布專用回讀只保留最多 96 MiB 的私有 PNG，不保留整批 RGBA。整批指紋由來源與每個 model／path／像素／PNG hash 順序計算。

來源／像素／cache 失敗、最終撤銷或取消使交易回滾；沿用 ResourceInventoryDatabase 的 committed／not-committed／unknown 及 cleanup 語意。一般回讀結果只含來源、整批指紋與數量；發布專用回讀捕獲重新建立並核對過的 PNG，只有清理完成與 owner 最終重查後才加入 publication，不能提供帳號或封包准入。

## 驗證與限制

`generate_smallmaps.py` 產生自有重複像素的 UnityFS／SerializedFile／Texture2D／resS，使用固定 UnityPy 1.25.4 的真實 Texture2D.image 核對整張 RGBA SHA。六個 fixture 涵蓋三種受支援格式、1023 寬度拒絕、linear 色域拒絕及同 root 兩個 model。未納入官方 payload。C# 比對完整 RGBA SHA，獨立解開輸出的 PNG 核對像素，並測試來源竄改、未知 model、取消、owner／路徑越界、關閉後讀取、SQLite 欄位／PNG／型別／容量竄改、缺列／多列與撤銷／取消回滾。

v8.0.73 `1cdd473ccc4882212423bcfd8e8e5371f241ac09`：.NET run 42706007943 四平台、Python run 42706007753 三平台均成功。

## production 協調與桌面顯示

`SmallMapSourceAcquisition` 單次使用，先探查完整來源計畫；只讀缺檔不下載、不寫入。bootstrap 保留缺檔數量／總 bytes 後逐檔使用 typed HTTP 入口，檢查來源、狀態、Content-Length，完整 checksum 串流寫入後回開。既有任意 URL 入口仍限 32 MiB。失敗／取消會清理 response 與暫存；失敗後已完成的合法快取可保留，不宣稱整批檔案交易。

準備階段在取得前後及 owner 發布前重新觀察版本／manifest。SQLite 發布回讀逐圖重新解碼、比較後捕獲私有 PNG；後續 cache 變更不改變已捕獲 bytes。owner 必須完成 source batch 清理並確認仍為目前 attempt 才發布。新準備、停止、帳號替換或目前場景改變均使讀圖要求失效。

桌面依當前接收場景與 Stage model 選圖，在背景驗證 PNG hash／1024 尺寸並解碼。相同 identity 重用 Bitmap，200 ms 檢查撤銷，關閉取消並等待既有讀取／解碼，晚到結果不重新顯示。底圖上新增目前場景已確認位置標記，位置變更不重新解碼圖片；不提供目的地選取或導航發送。

**未完成**：正式帳號／桌面遊戲畫面正向驗收及完整圖資。production 資源 owner 與當前場景投影的後續驗證見 v8.0.76 段落。下述 v8.0.74 官方資料診斷不等於新整合路徑驗收；本批測試使用自有 fixture／合成畫面，不連正式遊戲服務。


## v8.0.74 官方來源正向診斷及 CI 修正

2026-11-09T22:14:52Z 與 22:15:35Z 的官方版本觀察均為 DataVer 1.3.23、DataPackage 1296_2026_11_04_13_34_19_13、MainPackage 1296_2026_11_04_13_36_07_72；前後重新取得 manifest hash 並核對相同內容 SHA `faaab749110cf9e68be784e613e94579d51e92015ad8ef21e68de4aebbb5ba98`。只取得精確閉包的一個 `mainpackage_texture_s.bundle`，43,187,027 bytes，MD5／CRC 符合 manifest，SHA `730375010bded66594948ecb572dab3a1c22ae688d90f7df37e5727214201d1c`。官方 payload 與派生 PNG／SQLite 僅留在私有診斷目錄，不提交儲存庫。

Core 的虛擬 archive 索引確認邏輯大小 362,827,948 bytes，其中 SerializedFile 2,962,492 bytes、resS 359,865,456 bytes；按需路徑未配置完整展開陣列。獨立 UnityPy 1.25.4 解碼全部 562 個精確 manifest 路徑，均為 1024×1024、DXT1、單 mip、sRGB。Core 固定 receipt 工廠產生的 562 個完整 RGBA SHA 全部相符，PNG 合計 37,462,128 bytes，低於既有 96 MiB 上限。

隨後 SQLite 寫入與獨立重新解碼回讀均得到 562 列，來源指紋 `34f38e603ffb16cb01f8e8b95c3b099e2545680ef7600b3d0e3b8b7e616276c5`、整批指紋 `ec75468af9ddadf7a9beb22d0c98fe51f163ebbeb645acb293a7175b5a80d13b`。解碼與 SQLite 回讀後，2026-11-09T22:21:01Z 再次觀察官方版本並取得 manifest hash，仍與前述完全一致。這是雲端固定工廠／像素／SQLite 的正向診斷；沒有 account owner、production 下載協調或 UI activation，因此不能據此宣稱完整桌面驗收。Python oracle 為獨立對照，不能拿它的整檔展開記憶體用量當作 Core 按需路徑的效能數字。

原提交 `5902418` 的 Python 三平台及 .NET Linux／macOS／Android 均成功；Windows job 129473416158 為 45,869 通過、1 失敗。失敗在 `Integrated_account_whitebox_trust_bit_projects_current_catalogs_into_real_receive_then_revokes(false)` 的對端收尾：測試已 Stop 並確認 ResourcesReleased，仍要求正常 peer-led FIN，Windows 回報 ConnectionReset。僅此明確退休後的收尾改用既有 `ExpectClosedAfterRetirement`；正常 `CloseSendAndExpectEof` 完全不變，仍拒絕任何多餘 byte、已排隊封包、不完整 frame、timeout／取消及非退休錯誤。相關兩種 includeInstances 情況與既有退休關閉邊界合計 8 項通過。此為同批 CI 修正，不重複升版；新提交 CI 另行追蹤。

## v8.0.75 回歸證據

沿用上節已驗證私有官方快取，未重新下載：562 張完整 RGBA 再次符合獨立 oracle；SQLite 寫入及新增發布專用回讀均為 562 張、來源／批次指紋與 v8.0.74 相同。逐圖建立讀圖 request 並取得複本，全部 PNG SHA 相符。這是固定工廠／快照診斷，沒有當前官方版本再觀察或 production owner／帳號綁定，因此仍不代表正式整合驗收。

新增離線下載／來源／長度／checksum／取消／晚到撤銷、單次 quota、快取重用、HTTP 舊新上限、PNG 複本與讀取中撤銷測試。owner 測試確認自有必要表不能通過 1296 固定來源雜湊，且尚未進入小地圖下載／寫入；不放寬 parser 以製造成功案例。原生小地圖 7 項驗證一次解碼、10 次相同更新及縮放不追加解碼、原生 render、撤銷清圖、錯 hash 拒絕與關閉等待；主流程 198 項及既有頭像／表情／登入測試通過，皆合成／loopback。

最終本機強制重建零警告／錯誤，完整 Core **45,883** 通過；公用 Core consumer、Python 倉庫／UnityPy 包裝 **9**、Desktop Release 零警告／錯誤及離線 **81** 通過。原生 UI 主流程 **198**，另小地圖 **7**、頭像 **13**、表情 **24**、catalog **10**／資源確認 **6**／登入 loopback **11** 全通過；無正式登入或遊戲指令。

## v8.0.76 場景投影

對照 `wlre/services/world/smallmaps.py` 的正式 `SmallMaps.projection` 與 `Projection.packet_to_pixel`：width／height 為 65535 時取 6992，rate=100×(1024−24)/max(width,height)，u=x×0.01×rate+small_offset_x，v=1024−((height−y)×0.01×rate+small_offset_y)。使用同次 publication 的 Stage row，不套用歷史導航 origin，也不再次乘 PosXRatio／PosYRatio。尺寸零、偏移超過 1024、無 model、非有限值、封包範圍外或畫布外結果不顯示標記。

讀圖 request 的投影和 PNG 一樣在操作前後檢查當前性；場景替換、帳號或資源撤銷後失效。桌面讀圖前後還檢查同一 `ServiceStateSnapshot`，避免跨帳號的同 scene id 混用位置。標記只用 `ConfirmedIsCurrent` 且 scene 相同的已確認座標；目前沒有本機預測、路徑、傳點或 NPC 標記，也沒有導航發送。縮放採與底圖相同的置中等比例 square；位置更新只刷新標記。

六組數值直接由 repo Python Projection 執行取得，涵蓋長寬比、雙／單邊 sentinel、最小尺寸及邊界；另測無效幾何、NaN／Infinity／負值／封包與畫布越界、缺投影及操作中撤銷。這些是純座標數學，不構成遊戲移動權限。

## v8.0.76 正式資源 owner 診斷

使用原本 `ResourceRuntimeOwner.Create`，無注入 source／decoder／假信任旗標，在新的私有資料目錄執行 production BootstrapAndRefresh。結果 WasPublished=true、SourcesRechecked=true、SmallMapStorageOutcome=Committed、SmallMapDownloadCount=1、SmallMapDownloadBytes=43,187,027、562 張、ResourceAdmitted=true、Failure=null；activation 成功，Dispose 後 activation 失效並完成清理。這是官方 HTTPS 資源流程，沒有 AccountRuntime、帳密、遊戲 socket 或遊戲命令。官方 payload、PNG／SQLite 不提交 repo。

2026-11-09T23:21:59Z，以相同私有目錄走 production `RefreshWithResultAsync`：WasPublished／SourcesRechecked／ResourceAdmitted 均 true、Failure=null，小地圖下載 0 檔／0 bytes，寫入 NotAttempted，562 張。刷新前後小地圖 SQLite 整檔 SHA 相同。DataVer 1.3.23，DataPackage 1296_2026_11_04_13_34_19_13，manifest SHA `1dc1c74a9c9824085c91fe5504d1190b40e4b619751625a44e95c7d9a1adc358`；MainPackage 1296_2026_11_04_13_36_07_72，manifest SHA `faaab749110cf9e68be784e613e94579d51e92015ad8ef21e68de4aebbb5ba98`。小地圖 source／batch 指紋與前批相同。

由 owner-issued activation 為 799 個有圖場景取得 request，採各場景測試中心點；真實 repo Python Projection 對照全部 799 結果相符。這些是合成位置，不是真實玩家位置；至少一個 request 的 PNG 複本 SHA 通過，owner Dispose 後 activation、PNG 讀取及位置投影全部失效。正式帳號接收／遊戲畫面仍未驗收，沒有任何遊戲 socket／命令。

本批最終強制重建零警告／錯誤，Core **45,901** 全通過（新增 18 項）；Desktop Release 零警告／錯誤、離線 **81**，原生主流程 **198** 加小地圖 **10**、頭像 **13**、表情 **24**、catalog **10**／資源確認 **6**／登入 loopback **11** 通過。公用 Core consumer 與 Python 倉庫／UnityPy 包裝 **9** 通過。正式資源診斷與合成 UI 證據分開，沒有以合成位置宣稱正式玩家位置驗收。

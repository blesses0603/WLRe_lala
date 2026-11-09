# ver 8.0.74 小地圖按需像素與整批快取驗證

## 固定來源工廠

`SmallMapReceiptBatch` 只接受已解析 MainPackage manifest、固定受審查版本、cache reader 及精確相符的 receipt 集合。工廠自己衍生完整每圖閉包、根 Bundle、來源與 manifest 指紋，沒有接受 caller pixels、serialized object bytes、任意 decoder 或自稱來源指紋的 production overload。

新的 `CreateStagedSmallMaps` 是磁碟 receipt 計畫，最多 4 檔／64 MiB。既有 `CreateSmallMaps` 的 32 MiB owned-source 額度完全不變，亦未增加 production 下載額度。receipt 必須含有效小寫 SHA256，不能以 null 觸發 optional SHA 跳過。所有來源在消費前後重新核對，範圍讀取仍核對同次完整掃描捕獲的 64 KiB 區塊 hash。

每個 root 最多一個 SerializedFile，保留 16 MiB serialized slice 限制；完整驗證 type tree、metadata、物件索引／跨度與 container，再投影此 root 所需的精確小地圖路徑。只接受本檔且 class 28 的 Texture2D 指標；不猜外部指標、名稱 fallback、場景座標。必要 Texture descriptor 保留既有格式驗證，像素使用精確 owner 的 `.resS` 路徑與範圍讀取。舊一般 SerializedFile／Texture 入口仍驗證完整物件。

`UnityImageObjects.TextureAsync` 與同步入口共用 descriptor 解析；載入前先核對尺寸、mip、格式、完整 payload 長度及 stream span。小地圖只接受 1024×1024、sRGB、RGBA32／DXT1／DXT5，沿用既有翻轉與區塊像素解碼。PNG 有界且私有複製，candidate 仍為 `HasVerifiedProvenance=false`。

## 整批 SQLite

`ConsumeAsync` 按 root 分組，重用同一已驗證來源／索引／metadata，逐張解碼交付 PNG。若同一 root 有兩張地圖，整批只開三次來源（前查、消費、後查），不是逐圖重開；測試實測此開啟次數。這是 I/O 次數驗證，不宣稱時間或應用程式 heap 改善數字。

`SmallMapPngStore` 原子交易中逐張寫入並回讀，或獨立由固定工廠重新解碼並比對既有 cache。嚴格核對唯一 schema、model、source、asset、pixel SHA、PNG SHA、完整 PNG bytes 及總列數；不解壓不可信 stored PNG，也不將資料庫 hash 當像素真相。每張 PNG 最多 4 MiB，整批最多 96 MiB、2048 張，逐張消費不保留整批 PNG／RGBA。整批指紋由來源與每個 model／path／像素／PNG hash 順序計算。

來源／像素／cache 失敗、最終撤銷或取消使交易回滾；沿用 ResourceInventoryDatabase 的 committed／not-committed／unknown 及 cleanup 語意。回讀結果只含來源、整批指紋與數量，不能直接變成 UI 或帳號准入。

## 驗證與限制

`generate_smallmaps.py` 產生自有重複像素的 UnityFS／SerializedFile／Texture2D／resS，使用固定 UnityPy 1.25.4 的真實 Texture2D.image 核對整張 RGBA SHA。六個 fixture 涵蓋三種受支援格式、1023 寬度拒絕、linear 色域拒絕及同 root 兩個 model。未納入官方 payload。C# 比對完整 RGBA SHA，獨立解開輸出的 PNG 核對像素，並測試來源竄改、未知 model、取消、owner／路徑越界、關閉後讀取、SQLite 欄位／PNG／型別／容量竄改、缺列／多列與撤銷／取消回滾。

v8.0.73 `1cdd473ccc4882212423bcfd8e8e5371f241ac09`：.NET run 42706007943 四平台、Python run 42706007753 三平台均成功。

**未完成**：production 下載與必要表階段的真正組合、當前版本／manifest 再觀察、owner 的可撤銷發布、獨立視窗／小地圖顯示及場景座標映射。原有下載與準備路徑仍保持容量阻擋。本批不連正式遊戲服務，不宣稱完整登入前圖資或桌面發布驗收；不能只因磁碟 stage／SQLite 成功就啟用畫面。

## v8.0.74 官方來源正向診斷及 CI 修正

2026-11-09T22:14:52Z 與 22:15:35Z 的官方版本觀察均為 DataVer 1.3.23、DataPackage 1296_2026_11_04_13_34_19_13、MainPackage 1296_2026_11_04_13_36_07_72；前後重新取得 manifest hash 並核對相同內容 SHA `faaab749110cf9e68be784e613e94579d51e92015ad8ef21e68de4aebbb5ba98`。只取得精確閉包的一個 `mainpackage_texture_s.bundle`，43,187,027 bytes，MD5／CRC 符合 manifest，SHA `730375010bded66594948ecb572dab3a1c22ae688d90f7df37e5727214201d1c`。官方 payload 與派生 PNG／SQLite 僅留在私有診斷目錄，不提交儲存庫。

Core 的虛擬 archive 索引確認邏輯大小 362,827,948 bytes，其中 SerializedFile 2,962,492 bytes、resS 359,865,456 bytes；按需路徑未配置完整展開陣列。獨立 UnityPy 1.25.4 解碼全部 562 個精確 manifest 路徑，均為 1024×1024、DXT1、單 mip、sRGB。Core 固定 receipt 工廠產生的 562 個完整 RGBA SHA 全部相符，PNG 合計 37,462,128 bytes，低於既有 96 MiB 上限。

隨後 SQLite 寫入與獨立重新解碼回讀均得到 562 列，來源指紋 `34f38e603ffb16cb01f8e8b95c3b099e2545680ef7600b3d0e3b8b7e616276c5`、整批指紋 `ec75468af9ddadf7a9beb22d0c98fe51f163ebbeb645acb293a7175b5a80d13b`。解碼與 SQLite 回讀後，2026-11-09T22:21:01Z 再次觀察官方版本並取得 manifest hash，仍與前述完全一致。這是雲端固定工廠／像素／SQLite 的正向診斷；沒有 account owner、production 下載協調或 UI activation，因此不能據此宣稱完整桌面驗收。Python oracle 為獨立對照，不能拿它的整檔展開記憶體用量當作 Core 按需路徑的效能數字。

原提交 `5902418` 的 Python 三平台及 .NET Linux／macOS／Android 均成功；Windows job 129473416158 為 45,869 通過、1 失敗。失敗在 `Integrated_account_whitebox_trust_bit_projects_current_catalogs_into_real_receive_then_revokes(false)` 的對端收尾：測試已 Stop 並確認 ResourcesReleased，仍要求正常 peer-led FIN，Windows 回報 ConnectionReset。僅此明確退休後的收尾改用既有 `ExpectClosedAfterRetirement`；正常 `CloseSendAndExpectEof` 完全不變，仍拒絕任何多餘 byte、已排隊封包、不完整 frame、timeout／取消及非退休錯誤。相關兩種 includeInstances 情況與既有退休關閉邊界合計 8 項通過。此為同批 CI 修正，不重複升版；新提交 CI 另行追蹤。

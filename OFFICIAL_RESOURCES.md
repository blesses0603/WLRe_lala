# 官方資源來源與遷移

唯一權威來源：<https://wlreftpsrc.chinesegamer.net/WLN/TW/>。本工程不引入第三方遊戲資料庫。P2 第一批已將既有版本、Manifest、Bundle 與 Lua 清單服務接到 `resources_runtime/official/source.py` 的統一來源；舊網域不再通過正式版本來源驗證。現有固定版本 Runtime 仍待後續替換，不因此放行未知遊戲協定。

## P2 第一批實作與真實來源驗證

- `resources_runtime/parsers/yooasset.py` 為唯一共用完整 Manifest 解析器，保留 Reader／ParseError／fingerprint 舊 API；工具 CLI 只保留相容匯出與私人索引功能。正式 `wlre` 程式不再反向匯入 `tools.resources.lala_manifest_full_index`。
- 解析器實作版本 1、格式 2.2.5。此格式號是 Parser Adapter 身分，不是將遊戲版號鎖死；未知格式、尾段、重複及越界安全拒絕，輸入上限 8 MiB。
- VersionDetector 明確接收客戶端 ExeVer，讀取當次官方映射與兩套 Package 版本；兩輪觀測一致才回傳不可變結果。記錄 LaLa 版本、要求／觀測的遊戲版本、DataVer、兩套 Package、來源、時間與原始映射／SHA，**沒有啟用 Runtime 或核准登入的 API**。
- 2026-10-26T14:49Z 實際以新介面取得 1.3.0 → 1.3.21、兩套 1275 Manifest，CRC、完整索引及版本核對成功；受控證據見 [共用管線觀測](docs/rebuild/official_pipeline_probe.json)。使用一般啟動的 cache-buster 版本查詢另回報 `same_resources`。
- 此官方 IIS 來源回傳 Content-Type `*/*`；受控比較證明 `Accept: text/plain, application/json` 為 406、`*/*`／無 Accept 為 200。版本及 Lua 清單改用 `*/*`，內容仍交由嚴格解析／hash／大小檢查，未以 MIME 放寬資料驗證。
- 舊 Manifest 收據若來源 URL 不符新權威來源，不能假冒成新來源收據；依原機制重新取得、驗證再更新私有快取。沒有刪除舊使用者檔案或改寫其來源紀錄來繞過核對。

第一批沒有取代所有歷史靜態資料，也未建立完整 OfficialResourceManager／新快照切換。共用下載器見下一節；未知資源隔離、完整相容性與功能欄位缺口仍屬後續批次。不得將「Manifest 驗證」視為 Bundle／官方世界資料或正式遊戲驗收。

## P2 共用下載器批次

`resources_runtime/downloader` 已由四個既有官方服務共同使用，沒有再保留四份 HTTP 讀取／Bundle 串流的實作。既有 Manifest／Bundle／Lua／版本公開 API 與錯誤類別保留；版本服務對同一檔案的 cache-buster 相容回退仍維持一次。

- 只允許識別過的官方端點；拒絕轉址並釋放回應，不提供目錄爬取或第三方來源。TLS／Proxy／CA 使用標準環境設定。
- 記憶體讀取上限 8 MiB，單檔上限 256 MiB；總時限及每次 I/O 逾時分開。以 `read1` 檢查慢速串流總時限，重試預設最多兩次、指數退避；4xx（含 429）不自動重試。
- 取消在請求、讀取、退避及發佈前檢查；不靠終止執行緒。下載／完整性失敗清除本次 partial，既有成品不變。
- 檔案大小、Manifest MD5／CRC32 LE 全部符合後，才 fsync 並原子更名。快取仍重新核對三項，不將快取命中等同官方版本最新。
- 分段為明確可選，最多 4 段、順序請求。必須先確認 HEAD 長度、Accept-Ranges 與強 ETag，再使用 If-Range 及精確 Content-Range；不支援時單次 GET，異常不拼接混合資料。
- 結構化診斷僅固定代碼／數值，進度為不可變資料；不輸出回應內容、例外文字或敏感請求。Downloader 不關閉借用的應用程式診斷服務。
- 本批只自動清除自己未完成的 partial；**未實作會刪除舊快照／使用者檔案的 LRU 清理**。正式快照引用與安全快取清理仍待後續批次。

2026-10-26T15:30Z，針對 Manifest 中精確 `ScenesData_C.bytes` 所在的 `datapackage_data_s.bundle`（430,359 bytes）進行一次受控實測：HEAD 200、兩段 GET 206，大小／MD5／CRC 通過；UnityFS header 與完整 AssetPath 核對後擷取 101,616-byte 原始表，現有已審核的 `instance_catalog.parse_stages` 讀出 **1,337 筆場景定義**。證據見 [下載與場景表觀測](docs/rebuild/official_download_probe.json)。原始 Bundle／TextAsset 只留私人輸出，沒有啟用新 Runtime、建立遊戲資料庫或宣稱所有地圖／導航已驗收。

## P0 實際觀測

2026-10-26T13:36Z，以受控單一順序請求取得根目錄、1.3.21 目錄、`ResourcePath_PC.dat`、兩份 `.version`／`.hash`／`.bytes`。沒有遞迴爬站或下載完整 Bundle。版本對照提供 ExeVer 1.1.3、1.1.4、1.2.0、1.3.0，皆映射 DataVer 1.3.21；不能僅選字串最大值當作目前執行程式相容版本。

| Package | 版本 | Manifest bytes | 格式 | 資產／Bundle | CRC32 LE |
|---|---|---:|---|---|---|
| MainPackage | 1275_2026_10_21_18_29_38_49 | 2,564,950 | YooAsset 2.2.5 | 21,577／1,732 | b4e21f83 |
| DataPackage | 1275_2026_10_21_18_27_33_84 | 16,830 | YooAsset 2.2.5 | 190／22 | dcace626 |

兩份 `.hash` 與 Manifest CRC 一致，完整既有解析器讀到 EOF，Package 版本與 `.version` 一致。SHA-256 及觀測時間見 [來源收據](docs/rebuild/official_probe.json)。這是完整性及格式證據；CRC 不是數位簽章，不能據此自動放行未審核協定。原始 Manifest 保留於工作區外的私人輸出，不提交遊戲資源。

## P2 目標管線與驗收順序

1. VersionDetector：經核准 HTTPS 取得實際版本映射，選擇明確的 ExeVer；記錄 LaLa、遊戲、DataPackage、MainPackage 四種版本。
2. Downloader：來源白名單、拒絕未核准轉址、逾時、有限重試／退避、串流大小上限、取消、原子寫入。只有來源實際支援且可驗證 Range 時才用分段；不假裝支援續傳。
3. Manifest adapter：依簽名／格式選解析器，驗證 CRC、版本及完整引用；將目前 runtime 依賴 `tools.resources` 的解析器移入正式共享層並保留舊 API。
4. Bundle：依 Manifest 精確閉包下載必要資源，核對大小、hash、CRC、加密狀態；Unity container 完整 AssetPath 對應，不以檔名猜測 TextAsset。
5. Parser adapter：版本化格式識別、結構／邊界檢查；Eve v115、Scene size mismatch、未知欄位保留來源 offset 與失敗理由，不錯位補值。
6. CompatibilityValidator：必要索引、跨來源關聯、座標範圍、重複身分及未知欄位報告；格式相符不等於資料完整或協定核准。
7. ResourceGapAnalyzer：從功能欄位需求推導精確缺口，僅查同一 Manifest 中可識別的資產及相依，不掃描猜測 URL。
8. OfficialResourceManager／OfficialDataService：候選快照完成所有必要驗收後原子切換，禁止混版；失敗保留上一個快照供診斷並標為過期。預設不能把過期快取視為當前官方資料。

每份快照記錄來源 URL、官方與 Package 版本、Manifest 身分、下載時間、大小及完整性、解析器／schema 版本、驗收狀態、缺口與受影響功能。正式索引只允許經官方來源驗證的衍生資料。未知格式安全拒絕，不能永久鎖死特定遊戲版號，也不能移除格式驗證來假裝支援新版。

## 舊資源處置

`resource_manifest.REQUIRED_RESOURCES` 仍包含歷史 JSON／ZIP／圖像；`smallmaps.zip`、`stage_coordinates.json`、`graph_origins.json`、`navigation_data.zip`、副本／物品／戰鬥參考仍有使用者。新版場景解析、傳點與 NPC 已有不同程度官方 Runtime，但不代表全部可替代。PR #57 已確認的傳點安全規則與 NPC 不繪圖行為必須保留。

每批記錄「來源等價、資料完整、所有消費者遷移、測試通過」四項；缺任一項不刪舊檔。歷史來源只可作測試／遷移參考，不能覆蓋已驗證新版欄位。官方掃描網格、動態障礙及正式遊戲位置仍需獨立證據，CI 不能替代。

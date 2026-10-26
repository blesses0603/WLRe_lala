# 官方資源來源與遷移

唯一權威來源：<https://wlreftpsrc.chinesegamer.net/WLN/TW/>。本工程不引入第三方遊戲資料庫，也不要求使用者手動準備 ZIP。現有程式使用的 `wlreftp` 網域及固定版本是待遷移項目，**尚未因本文件而切換**。

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

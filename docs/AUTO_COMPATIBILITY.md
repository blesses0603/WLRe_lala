# LaLa Launcher：官方資源自動相容性判定（PR #56）

## 功能與權限界線

Launcher 在官方 DataPackage／MainPackage Manifest、Bundle 驗證後，
自動解析 NPC、商店、製作、場景四類來源，接著再次執行獨立的
**資料相容性檢查**。

**資料格式相容不等於遊戲協定相容，也不等於可以登入。**
本機報告永遠不能取代 game_version_gate 與 runtime_1275 的正式版本閘門。

## 更新與檢查順序

1. 確認官方 DataVer、兩包完整版本和各自 Manifest SHA。
2. 驗證必要 Bundle 的檔案大小、MD5、CRC 及精確 AssetPath 與依賴。
3. 以已審核的 Eve／ItemData／Smith／Scenes Adapter 解出四類來源。
4. 再次以獨立相容性判定器檢查每類來源的完整官方版本身分、
   schema、來源名稱、AssetPath、SHA-256、長度、筆數及可解析性。
5. 所有四類均正確才能回傳 data_compatibility=compatible；
   protocol_compatibility 一律 unverified；approved、assets_ready、
   can_send_packets 均為 false。
6. 私有版本化目錄內儲存 candidate.zip 與 compatibility_report.json；
   報告包含當次候選 ZIP SHA-256，不能挪用舊報告到不同檔案。
7. Launcher 重用候選時，仍重新核對官方 Bundle 與候選格式，
   而不是只相信上次的 SHA。失敗就重新走已驗證的資源準備程序。

## 判定狀態

| 情況 | 資料判定 | 運作方式 |
| --- | --- | --- |
| 四類格式、來源、版本全部符合 | compatible | 候選可保存；遊戲協定仍須驗收 |
| Bundle 不完整、來源不符、Schema 變更 | 拒絕或 unverified | 不啟用未知資料 |
| 官方資源查詢不完整 | unverified | 不把舊快取當作新版本 |
| 登入／戰鬥／交易協定變更 | protocol_compatibility=unverified | 不自動解鎖 |

使用原始碼 Launcher 可直接執行，無需自建 bindings.json：

~~~powershell
py -m wlre.launcher
~~~

開發者需要詳細輸出時：

~~~powershell
py -m tools.plan_official_catalog --download --parse
~~~

成功時的 JSON *格式範例*，不是對目前官方版本的驗收承諾：

~~~json
{
  "status": "review_required",
  "data_compatibility": "compatible",
  "protocol_compatibility": "unverified",
  "approved": false,
  "assets_ready": false,
  "can_send_packets": false
}
~~~

結果位置：
%LOCALAPPDATA%\WLRE_LaLa\official_sync\derived_catalogs\<catalog_key>\
以及 %LOCALAPPDATA%\WLRE_LaLa\official_sync\launcher_catalog_status.json。

原始碼回歸測試：

~~~powershell
py -m unittest discover -s tests -p "test_catalog_compatibility.py" -v
py -m unittest discover -s tests -p "test_auto_catalog.py" -v
py -m unittest discover -s tests -p "test_launcher_catalog.py" -v
~~~

## 限制

- 只支援已審核的 YooAsset／UnityFS、Eve、ItemData、Smith、
  Scenes 格式，不能解讀任意未知欄位或未支援的官方加密方式。
- 本機算出的 SHA-256 與 CRC 無法單獨證明伺服器封包協定相容。
- **相容報告是唯讀診斷，不是權限憑證。** 登入、NPC 互動、
  買賣及移動安全閘門完全維持現況。
- 官方 1275 Eve Bundle 已做實檔測試；另外的 ItemData、Smith、
  Scenes Bundle 及實際伺服器 E2E 仍需驗收。
- 本階段不打包 EXE／APP、不合併 main、不建立 Release。

## 正式 1275 Runtime 的候選資料安全銜接

**四類候選 ≠ 完整正式 Runtime。** 現有 runtime_1275 仍需要兩份來源獨立固定 SHA-256 的 ZIP：
- 1275_DataCatalog.zip：160 張原始表與 3 份經審核的對話、文字、完整物品資料索引。
- 1275_EveNpcIndex.zip：已核對的 NPC 與互動事件索引。

由於自動候選只有 NPC、商店、製作、場景四份衍生來源，不能直接改名成正式 ZIP，更不能自造固定 SHA 來解鎖。

Launcher 完成四類解析與相容報告後，會查看私人 reviewed_full_1275 資料夾是否備有上述完整雙 ZIP。若無，保留候選相容報告，但正式登入閘門仍阻擋缺少的全量資源。

若完整雙 ZIP 到齊：先用原有 load_preview 驗證全部正式來源，再以 formal_candidate_bridge 重新檢查候選的版本身分、相容報告、來源 SHA 與 NPC/互動事件、製作配方、場景的實際內容是否和正式來源相同。不同則拒絕。確認兩份正式檔案尚未安裝後，先把檔案複製到同磁碟暫存區並重新完整驗證，才透過原有無覆寫的雙檔安裝器發布。

Runtime 啟動前依舊只載入經既有固定 SHA 認證的正式資料。若 Launcher 已有同版相容收據，runtime_1275.ready 還會再次交叉驗證，只有全部符合才能更新共用製作資料；格式相容不代表 NPC 交易或任何伺服器封包已通過 E2E。

私人路徑：%LOCALAPPDATA%\WLRE_LaLa\official_sync\reviewed_full_1275\

手動確認狀態（預設唯讀）：

~~~powershell
py -m tools.reviewed_1275_handoff
~~~

兩份完整正式 ZIP 均已備妥時，可顯式執行安全安裝：

~~~powershell
py -m tools.reviewed_1275_handoff --install
~~~

請勿把 DataPackage_1275.zip 或 MainPackage_1275.zip 的 Manifest-only 壓縮包放成上述正式 ZIP，它們不含完整遊戲表格且無法通過固定 SHA 驗證。既有正式 ZIP 不覆寫；只有部分已安裝時直接安全拒絕。官方未來版本若改動格式或封包協定仍需獨立開發與驗收。

## Launcher 自動盤點 LaLa 缺少的正式資料

使用者不需要自行猜測是哪個 ZIP 或哪張表缺失。每次真實 Launcher 執行官方資源準備後，會唯讀檢查本機 official_resources_1275，輸出正式資源缺口報告至 official_sync/resource_gap_report.json。登入前畫面以簡短文字顯示實際缺哪一份 ZIP；完整清單則可用診斷工具查看。

**資料類型與檢查方式：**

| 正式來源 | 必要內容 | 缺失或損毀判定 |
| --- | --- | --- |
| 1275_DataCatalog.zip | 160 張原始表、TalkData_C／TextData_C／ItemData_C 索引 | 必須通過專案既有固定 manifest SHA-256、163 個內部檔案與逐檔 SHA-256 |
| 1275_EveNpcIndex.zip | NPC 事件、互動事件的兩份索引 | 固定 SHA-256、總筆數、場景與欄位 Schema 校驗 |

若整包不存在，列出實際缺少的 ZIP 與必要資料類型；若內部 manifest 可通過固定雜湊驗證，進一步列出缺失的 `tables/.../*.bytes` 與 `indexes/...`；若來源存在但遭修改，明確標示校驗失敗，不誤認成整包缺失。報告完全不包含使用者磁碟絕對路徑、不會解壓或修改任何遊戲檔案，`assets_ready`、`can_send_packets` 永遠為 false。

可在專案目錄執行一鍵唯讀檢測：

~~~powershell
py -m tools.diagnose_lala_resources
~~~

要取得逐檔缺口 JSON：

~~~powershell
py -m tools.diagnose_lala_resources --json
~~~

目前官方 Manifest／Bundle 的**增量下載**仍由 Launcher 原有流程負責；但是**無法只靠四類候選自動合成**固定 SHA 的正式雙 ZIP。若缺少對話文字、全量物品或表格，診斷會指出，取得後還必須依正式來源的固定指紋和相容性檢查通過，才可能使用。資源缺口報告本身絕對不是登入權限。

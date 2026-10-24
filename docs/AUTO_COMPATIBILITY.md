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

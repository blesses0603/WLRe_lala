# P2 場景定義快照批次紀錄

【開發階段】P2b／P2c，限定場景定義，其他 Parser 與跨資源功能仍待續。

【完成項目】

- 新 Manager 串接動態版本、兩套 Manifest、精確需求閉包、共用下載、TextAsset、場景 Parser、再次官方版本／hash 核對與原子發佈。
- 新缺口狀態／相容性介面、唯讀查詢、快照收據與原始來源保存。快照 CAS 拒絕晚到的工作，離線失敗只提供診斷。
- 舊場景及 Unity 擷取入口保留 API、buffer、例外及地圖稽核 helper；正式資源層不依賴 UI 或 Windows。

【修改檔案】

新增：

- `wlre/resources_runtime/official/contracts.py`
- `wlre/resources_runtime/official/gaps.py`
- `wlre/resources_runtime/official/compatibility.py`
- `wlre/resources_runtime/official/snapshots.py`
- `wlre/resources_runtime/official/manager.py`
- `wlre/resources_runtime/parsers/scenes.py`
- `wlre/resources_runtime/parsers/unity_textasset.py`
- `tests/test_official_resource_manager.py`
- `tools/check_official_resource_snapshot.py`
- `docs/rebuild/official_snapshot_probe.json`
- 本批紀錄 `docs/rebuild/P2_SNAPSHOT_REPORT.md`

修改：

- `wlre/services/instance_catalog.py`
- `wlre/services/world/unity_textasset.py`
- `wlre/services/official_manifest_sync.py`
- `.github/workflows/official-resources.yml`
- `ARCHITECTURE.md`、`MODULES.md`、`OFFICIAL_RESOURCES.md`、`MIGRATION_PLAN.md`、`TESTING.md`、`CHANGELOG.md`

【影響範圍】官方共享管線、舊場景定義／Unity API 與資源 CI。GUI 操作、即時角色狀態、封包與自動化尚未切到新資料服務。

【測試結果】新 28 項及官方 120 項通過；完整回歸與實際時長見根目錄 TESTING。真實官方管線取得 1,337 筆場景；此為靜態資料觀測，正式遊戲 E2E 未執行。

【CI 狀態】場景提交 `34b7866` 的九個三平台工作成功；共用核心 `84d3bb1` 另修復 Mac 原生 GUI 驗收，九個工作成功後正常合入本分支。合入後本地 1,303 項通過（跳過 2）；最終 merge 的三平台整合 CI 依 PR #59 Checks，不引用較早提交代替。

【尚未完成】場景名稱／模型跨表、其他功能 adapter、GUI／舊 Runtime 消費者遷移、舊快取引用清理及 P3～P7。

【風險】Mac CI 仍有兩項大 viewport 情境因螢幕不足而未執行。場景定義不代表地圖圖像／傳點／導航可用；未解讀欄位保留但不推測。UnityPy 同步解壓無強制中斷或記憶體隔離。本批沒有刪除歷史檔案；版本維持 0.6.1，未合併 main、未發行／打包。

【下一批工作】CI 通過後，擴充已審核官方資料需求與跨表驗證，再以 P1 生命週期及 WorkerGroup 接入資源服務；不讓未知格式或不完整資料進入下游遊戲功能。

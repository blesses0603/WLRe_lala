# 官方動態 Runtime 接線與驗收（PR #63）

## 實作範圍

- Launcher 以當次官方 DataPackage／MainPackage 完整版本與 CRC 校驗 Manifest，動態計算 SHA-256；依精確 AssetPath 與依賴關係同步十張必要原始表及選用傳點來源。
- `dynamic_bundle_runtime.prepare_dynamic_runtime()` 重用完整 Bundle 解碼器；筆數來自實際解析，不固定為 1275、1,032 配方或 10,975 NPC。33／35-byte Smith 格式依表頭筆數與完整長度辨識，未知格式拒絕使用。
- `activate_for_official()` 在登入前核對官方身分後，一次切換 NPC、互動／商店、物品、製作、場景與遠征資料。`runtime_1275.active_runtime()` 保留相容入口，正式來源優先使用本次完整動態 Runtime。
- 物品獨立加入第五類 Catalog 來源，必須完整解析 ItemData_C、拒絕重複 ID／截斷／多餘 bytes；與商店商品及配方材料交叉核對。SQLite 舊四類版本表於交易內升級，保留歷史紀錄；筆數或 SQLite 收據不作為 Runtime 信任來源。
- UI、NPC 互動、對話、物品名稱／價格、場景投影及遠征讀取同版資料；切換版本時重綁 UI 快照並清除舊快取。失敗或較新的檢查取代舊工作時，不得發布過時資料或回退到 1262／1275。
- 新版製作保留每個 recipe_id；同一產品多配方不互相覆蓋。舊產品選單無法安全選擇的配方保留在完整 `recipe_catalog`，不臆測選擇。動態製作／傳點維持未核准協定狀態，不因資料通過便開放封包。

## 官方資源實測

2026-11-02（台灣時間），實際從官方版本來源下載及驗證 Manifest／Bundle，完整 Runtime 建立成功：

| 項目 | 實際結果 |
| --- | --- |
| DataVer / ExeVer | 1.3.22.1 / 1.3.0 |
| DataPackage | 1286_2026_10_29_13_42_37_94 |
| MainPackage | 1284_2026_10_28_19_50_04_11 |
| DataPackage Manifest SHA-256 | 5b62b7d8937dced4ab058d8f857c664b44f3f3841daddaf06e39267959e47a76 |
| MainPackage Manifest SHA-256 | 3f78ec72b2f504b808a2d0991e2ea0e025bef54ebd8d8e59dcfa02bd71d58bb2 |
| NPC 事件 | 11,009 |
| 互動索引（包含對話／商店） | 1,636 |
| 物品 | 11,326 |
| 完整配方紀錄 | 1,026 |
| 場景 | 1,337 |
| 遠征任務 | 260 |

這是本次實測結果，不是後續版本的固定驗證常數。官方原始遊戲資源未加入 Git。

## 重現方式

```bat
py -3 -m wlre.services.world.dynamic_bundle_runtime --sync
py -3 -m unittest discover -s tests -v
```

第一個指令會核對當次官方版本、下載必要來源並輸出身分、SHA-256 與各類筆數；不含 `--sync` 時只驗證現存 Bundle（仍查詢官方版本及 Manifest）。成功回傳 0、JSON `status=verified_runtime`；缺少來源、格式不符或版本中途變動則回傳 1。

## 驗收邊界與版本

- 本機 Linux 回歸：1,256 項測試，無失敗／錯誤，127 項因環境條件略過。GUI／Windows 原生檢查交由 GitHub Actions 三平台執行；CI 結果以本次提交對應的 workflow run 為準。
- 本文件的官方驗證屬於資源下載、完整解析與模組讀取；沒有使用測試帳號登入正式遊戲伺服器，沒有執行正式服交易、製作、換圖或戰鬥 E2E。
- 既有獨立登入／協定基準仍保留；新版本資料可載入不等於支援的協定版本已更新。資料層接線完成不能宣稱所有遊戲功能已通過正式服驗收。
- main 與程式常數維持 v0.6.1；本 PR 預計 v0.7.0，尚未完成正式服驗收，不升格為正式發布，不合併 main，不建立 Release／Tag。

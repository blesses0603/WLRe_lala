# 移除隨附舊導航資料

PR 評估分支，尚未合併或發布。依使用者要求，移除發行包中的三份舊導航資料，不刪除使用者既有資料。

## 移除範圍

`resource_catalog_seed.sqlite3`原本僅有`navigation_data.zip`、`graph_origins.json`、`stage_coordinates.json`三項。整個隨附seed已移除，減少12,050,432 bytes（約11.49 MiB）；沒有建立空殼seed代替。

- `SOURCE_MANIFEST`為空，三項及seed檔名列為退役資源。
- 桌面Windows／macOS包裝只收錄仍需的資產，不包含退役資料。即使舊checkout留有seed，也不打包、不讀取、不刪除它。
- `require_resources`與完整自檢仍驗證目前需要的圖像資產；不再強制要求離線導航seed。官方資料的Manifest、Bundle、hash與版本化DB完整性檢查各自保留，並非用移除seed放鬆官方驗證。
- 舊`build_seed`／`provision_seed`／`read_config`／`verify_seed`API明確拒絕退役操作，不開啟或修改使用者資料。
- `load_bundled_bytes`對三份舊導航名稱在讀檔／開DB之前就拒絕。既有有效或損壞的歷史DB都不被拿來補導航，也不自動刪除或清空。
- 空的新版資產目錄執行舊migration時回傳0，不建立空使用者DB。

## 消費者分類

- 正常官方導航、官方小地圖、CLI及受限Movement／Roaming：使用目前官方Runtime與同版衍生DB，缺資料安全停止。
- `navigation.Mesh`／`NavigationError`／`finite`及funnel、surface、motion幾何算法：官方預覽和移動仍使用，必須保留。它們本身不需要seed。
- 歷史`Coordinates`／`Repository`的預設資料載入：退役並明確失敗。合成幾何單元測試改成顯式fixture，不再倚賴發行包的舊導航資料。
- 明示歷史檔案的研究／比較工具：不能自行恢復發行seed；缺歷史輸入時報unavailable。舊隔離實驗的quarantine還原功能仍保留checksum及不覆寫保護，只作用於原實驗副本；新版原本無seed的實驗不假造還原資料。
- 舊導航UI入口已由官方預覽相容入口取代；未建立目前官方Runtime時明確要求同步。

## 驗證與界限

新增回歸核對：包裝清單無退役檔、保留現有使用者DB及檔案位元組、有效歷史資料也不回退、舊API不讀寫資料、全新子程序僅程式與圖像可通過自檢、Tk冷啟動測試必須確認實際資源目錄無seed。

雲端本機沒有可用顯示器，GUI測試由三平台CI實際執行後才能宣稱通過。刪除包內資料不代表所有官方場景／動態碰撞／真實角色移動皆已驗收；4個退化模型及受限執行不支援的坡面、多層歧義等仍安全停止。使用者既有資料、帳號、官方下載快取與官方衍生DB沒有清除。

## 最新本機整合結果

- 移除後的全新隔離副本實際沒有seed：程式自檢通過；558官方模型入庫／重讀，795場景三模式2,385項預覽檢查（1,636成功、749安全停止），558次錯誤版本拒絕，正常舊seed存取0次。
- 正式App GUI冷啟動已嘗試，但環境缺DISPLAY；獨立dummy Xorg也無法建立Unix socket。這是未通過／環境阻擋，不是GUI成功。新加入的跨平台回歸會以真正App入口、全新副本及空私人資料目錄驗證，並禁止讀三份舊檔／seed及遊戲連線。
- 整合完整回歸2,123項，OK、210 skipped；compileall、strict-git audit、資源／UnityFS自檢、Windows及macOS兩架構build dry-run通過。這些是本機結果，未推送版本的CI尚未執行。

[移除後隔離回執](official_navigation_removed_seed_check.json)；[受限移動與真cache抽樣](OFFICIAL_BOUNDED_MOVEMENT.md)。使用者資料沒有刪除或重寫，既有seed即使仍在舊安裝目錄也不讀取、不打包。

## 整合後追加驗證

導航與背景版檢整合至本機 `d4f2c3e` 後，使用獨立雲端 Xvfb（TCP display）及 Tk 8.6，真正無seed App冷啟動測試1項通過、0跳過（1.281秒）。測試建立全新程式副本及私人資料目錄，實際啟動App，確認啟動檢查完成、主面板顯示、缺Runtime時預覽停止、舊導航讀取0次、未登入遊戲。上文缺DISPLAY為先前嘗試結果，已由本次隔離驗證補齊；仍未驗收正式服移動或原生安裝包。

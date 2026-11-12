# 當前場景傳點觀察（ver 8.0.79）

Python `wlre/services/world/portals.py` 區分 EventData 格座標、投影座標、目的地候選及衝突，不能由列序或座標猜出可移動傳點。現有 Core `OfflineRuntimeCandidate` 已從同版 Eve／ScenesData 建立 event-only `PortalObservations`，但缺少當前帳號的可撤銷入口。

本批新增 `AccountRuntime.TryGetScenePortalObservations`，只交付同一 publication、接收 attempt 與目前場景的資料。保留位置、目的地及 issue-only tombstone 的聯集，以事件索引排序；保留未知與衝突，不合成位置或目的地。最多 4096 筆，身份不符或超額整批拒絕。activation 僅快取一個場景；讀取前後重查撤銷。回傳資料是歷史觀察，不是操作授權。

`UnavailableOptionalSources` 明示 StageMapData_C／EveDoorLinks／DoorLinkData_C 缺失；空觀察不代表場景沒有傳點。尚未接桌面傳點清單、完整可選來源、路線執行或正式場景驗收。沒有新增下載、帳密使用或遊戲命令。

登入前確認保留官方來源與實際寫入範圍，資源由程式自動管理且不顯示儲存路徑；進階驗證可展開；取消與確認留在捲動內容外。沒有修改 PrepareAsync、版本驗證或登入 gate。

新增測試交由既有 GitHub CI 執行；本機未跑完整測試。正向帳號整合仍沿用明示合成 white-box fixture，不等同正式驗收。

## 同批補充：進度與 Windows CI

Core 以不可變快照回報實際階段；必要資源完成一個 Bundle 的取得及雜湊驗證後才增加檔數，包含快取命中，比例只屬於該階段。未知總量的其他下載／驗證／回讀階段只顯示進行中。終止狀態不接受遲來更新；UI 200ms 輪詢並在 finally 停止，不跨取消或替換的 preparation 更新。完成準備後仍重查登入清單，進度本身不授權登入。

Windows aff72bc run 42738434990/job 129573290086 的失敗是空角色清單拒絕後的 FIN／RST 平台差異。測試改用既有嚴格 RetiredPeerClosure（檢查佇列與 frame 未殘留，再接受關閉），仍斷言 selector 未呼叫與資源釋放。沒有放寬產品協定。

同批後續提交維持 v8.0.79；完整測試及平台 UI 交 CI。workflow concurrency 僅取消同一 PR 的舊執行，保留其他 PR、main 和已完成結果。

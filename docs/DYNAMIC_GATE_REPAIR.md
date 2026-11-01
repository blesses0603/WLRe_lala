# 官方資料一致即可登入

## 登入條件

依專案要求，移除「協定尚未完成正式服驗收就禁止登入」的限制。一般啟動核對以下資料，一致即開放「進入登入畫面」，既有 App.connect 也接受相同結果：

- 當次官方 DataVer、實際選定的 ExeVer，以及獨立 MainPackage／DataPackage 完整版本。
- 由當次官方 Manifest、Bundle 與原始表解析取得的完整 Runtime。
- LaLa 活躍資料庫的完整 Catalog identity（含兩個 Manifest SHA-256），以及十份必要原始表的實際內容 SHA-256。

成功狀態為 database_matches_official，blocked=false、login_allowed=true。protocol_compatibility 保留為事實紀錄，無論是否已驗收，都不參與登入封鎖判斷。官方發布新版客戶端亦不因「新版」字樣被單獨封鎖，仍以該版本的 Runtime 與資料庫核對結果決定。

資料庫缺少、落後、Manifest 重新發布或原始表損壞時顯示資料不一致；僅版本字串相同不足以代表資料一致。所有資料庫核對均唯讀，不修改使用者設定、帳號或資源。既有官方查詢失敗、Runtime 無法解析與版本檢測過期處理保留。

## 製作解析與進度

SmithData_C 使用共用的已審核 33／35 bytes 解析器，保留不同 recipe_id 的同產物配方；寫入版本化 smith_v1 解析紀錄及新增／異動／移除比對。未知格式保留原始表並標記 parse_failed，不影響其他表解析。七項進度統一按實際 status=parsed 計數，修正原先製作未寫入而卡在 6／7 的問題。

快取在下一輪 Launcher 同步由原始資料重解析；不需要清空使用者資料庫或全部重新下載。版本畫面不再混入舊式 ZIP 診斷或固定 1275 不相容提示。

## 驗證邊界

回歸涵蓋配方解析、七項進度、不同雙包版本、新客戶端、資料庫實際 BLOB 校驗、重新計算本機雜湊後的偽造資料、Manifest 重發身分、缺表、GUI 開放登入與真實 connect 前的狀態檢查。CI 會重新執行；未完成的 CI 不標記為通過。允許登入不等於宣稱正式服所有操作已實測成功。

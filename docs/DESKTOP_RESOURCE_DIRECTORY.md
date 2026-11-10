# ver 8.0.78 系統管理資源資料目錄

桌面資源位置由作業系統 LocalApplicationData 加上固定 LaLa/Resources 子目錄決定。Windows 為使用者 AppData\Local\LaLa\Resources；Linux/macOS 沿用 .NET 對 LocalApplicationData 的對應，不硬編碼使用者名稱、磁碟機或安裝位置。資源不放在漫遊設定目錄，不提供 UI 選擇或修改路徑。

啟動和重新查詢自動唯讀檢查資源。位置解析不建立目錄；確認準備後，由原有 Core 資源流程建立 Bundle／SQLite 目錄及寫入資料。既有來源、大小、雜湊、SQLite 回讀及版本重查保持不變。登入前／後獨立驗證、下載與寫入確認、帳密逐次確認及一般遊戲操作 Held 也不改變。停止後再次查詢會重新決定同一固定位置，不保留登入准入。

系統位置為空、相對路徑或解析失敗時不退回工作目錄、安裝位置或共用暫存目錄。錯誤不暴露底層例外細節。舊手選資料不移動、不刪除，也不自動作為可信來源；必要時由既有流程重新準備。

## 驗證

完整 Core **45,914** 通過（零失敗／跳過）；本批沒有 Core 產品邏輯變動。

- Desktop Release 零警告／錯誤；離線 inspector 9、presentation 77（新增 5）通過。
- 公開 Core consumer、Android lifecycle 76、cloud acceptance 合成 36、Python repository hygiene／UnityPy packaging 9 通過。
- UI 增加啟動自動位置、沒有資料夾選取、拒絕寫入、停止後恢復與無效系統位置測試；本機 Xvfb 無法建立顯示 socket（正式升權重試亦失敗），因此原生 UI 本批未執行，不沿用前批數字。待精確提交 Linux CI 驗證。
- 未使用使用者電腦、真帳密或正式遊戲 socket；未變更 PR 標題／內文，維持 Draft，未合併或發版。

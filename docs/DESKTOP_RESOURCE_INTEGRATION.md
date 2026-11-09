# Desktop 資源準備接線 — PR #79 ver 8.0.44

本批把桌面選定資料目錄接到現有 `AccountRuntime.CreatePrepared`，不自行重作 downloader、
SQLite writer 或 runtime admission。沒有選資源目錄時仍可使用原受控登入／唯讀接收流程。
這不是正式服驗收，也不是 Python 的完整登入前資源 gate。

## 實際流程

1. 在版本視窗選擇資料根目錄，唯讀檢查仍只讀固定 SQLite，不會下載或修復。
2. 按「使用此目錄準備登入資源」只記住本次程式生命週期的路徑；不寫設定、不做 I/O。
   「取消資源準備選擇」只影響下次登入；已啟動的登入須使用中斷停止。
3. 選伺服器／分流並自行輸入帳密，按登入後凍結本次 profile 與資料路徑。
4. 獨立確認框列出 `AccountRuntimeDisclosure.Resources` 的官方 HTTPS 前綴、版本入口、
   Bundle 快取與 SQLite 完整位置；明示建立目錄／暫存檔／journal，以及停止不撤銷既有寫入。
   取消時只有 inert runtime 被釋放，不啟動 socket、HTTP 或寫入。
5. 同意資源範圍仍不等於同意帳密傳送。`AccountRuntime.CreatePrepared` 現在將可選
   `IAccountLoginSendConfirmation` 傳入內部準備器；Desktop 必定傳入，驗證／正式 TCP
   各自顯示目的地與無 TLS／可逆 XOR 風險。手動選角不變，沒有自動重試。
6. 登入協定完成後，Core 自動執行必要 Bundle 取得／驗證、十表解析、SQLite bootstrap、
   獨立回讀及來源版本／Manifest 重查；只有既有 Core 准入通過才有當前帳號目錄綁定。
7. Desktop 從同一 `PublicationSnapshot` 取得接收狀態與目錄，呈現物品／場景名稱；目錄
   撤銷時清除名稱映射。Core 同版 observation inputs 仍由整合 runtime 提供，不由 UI 重建。
8. 中斷／關閉同時停止登入、資源工作與回呼並等待整體釋放。Committed／Unknown 寫入
   不會自動回復或由 UI 重試，必須重新觀察；歷史 WasBound 不當成當前可用性。

## 邊界與 Python 差異

- 官方 host、版本／Manifest／Bundle 驗證、大小限制、cache／SQLite 路徑及讀回規則沿用 Core，
  沒有開放任意 URL、handler、資料來源或聲稱來源可信的 UI 輸入。
- Core 綁定表示當前帳號的唯讀目錄可用；`ResourceHeld`／`CanSendCommands=false` 保持不變。
  候選本身的 `HasVerifiedProvenance=false` 等旗標不被改寫成授權。
- Python 啟動前完整資源準備／ZIP 重建流程未照搬：此路徑在登入協定完成後執行。
  尚未實作完整圖片／技能效果、全部可選目錄正向驗收、背景版本 observer、程式更新器，
  也不代表全桌面 UI 已完成。
- 本次資源確認計入既有 prepared login 一分鐘有效期；逾期須重新開始，不重用確認。
- 根目錄只在記憶體中保存；路徑正規化及固定子路徑沿用 Core，並非防禦惡意 symlink／
  外部替換的檔案系統 sandbox。使用者應選擇自己管理的應用程式資料目錄。

## 驗證

- Core 資源整合／bootstrap 201 通過；既有 prepared-account 正向測試新增驗證兩次
  recipient 確認均經過整合 runtime。其正向綁定是既有 **white-box 合成來源** fixture，
  明示不證明官方 provenance 或 live acceptance。
- 真正 Avalonia → public AccountRuntime → loopback：6 項資源確認斷言通過，涵蓋拒絕
  資源無副作用、同意資源仍等待帳密確認、拒絕帳密不下載／不寫入。未讓此測試走到
  production HTTP 下載階段。
- 原生 UI 226（29 張截圖）、catalog UI 9、原登入 loopback 11、Desktop 離線 63、
  公開 Core consumer 與 Python 倉庫／發行 15 通過。沒有實際連官方 HTTP／遊戲伺服器。
- 資料目錄選擇與取消只影響下一次登入，測試確認這一步不建立目錄。

完整官方資料成功組合與各平台真實資源準備仍需另行驗收，不以合成測試冒稱完成。

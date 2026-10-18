# 連線狀態與長時間運行診斷

## 本次觀察

使用者提供的 2026-10-18 紀錄在 08:25:36 出現 `ui_callback_error count=1`，之後沒有新的 health 紀錄。前面的 backlog 大多為 0，沒有證據可據此判定是記憶體不足或角色斷線；視窗仍可操作也不代表畫面資料持續更新。

已重現的程式問題：原生 ttk 下拉選單的焦點路徑如 `.!combobox.popdown.f.l` 不在 Tkinter 的 Python widget 字典中，`focus_displayof()` 會拋出 `KeyError('popdown')`。舊的 `poll()` 只在正常結束時安排下一次更新，所以單次例外會讓角色畫面永久停止更新、Tk 主視窗卻繼續回應。因原始 health 檔只記計數，不能斷言這就是使用者當時的具體例外。

## 修正

- 背景判斷改讀取原始 Tcl 焦點，不將原生下拉選單解析成 Python widget。
- 更新排程在 finally 中繼續安排；失敗後緩退一秒，拋棄該次失敗快照，後續新資料可繼續更新。
- 角色快照與連線證據分開顯示。主頁右上及登入窗顯示最近伺服器回應與經過秒數。
- 超過 120 秒沒有完整伺服器資料只標為「連線待確認」，不冒稱已斷線、不強制登出／重登；收到資料即恢復。即使接收執行緒停止更新，畫面仍按本機單調時鐘計算資料年齡。
- 桌面連線啟用 OS TCP keepalive；支援時使用 idle 60 秒、interval 15 秒及 count 4。這是 OS TCP 探測，不發送未驗證的遊戲封包。最終斷線時區分遠端關閉、網路錯誤、手動停止及資料處理異常，最後狀態明確為 disconnected。
- 顯示佇列保留最新快照與最新連線證據，舊的普通顯示事件最多 1,024 筆；核心先處理遊戲資料，顯示事件淘汰不會丟棄網路封包或遊戲指令。因顯示事件過多略過的數量會記錄。
- 玩家座標快取在離開事件／換圖時清理，歷史快取最多 2,048 筆並保留本機角色；本機權威位置仍獨立保存，不受快取淘汰影響。這不是帳號數或隊員數上限。

## LOG 位置

Windows：`%LOCALAPPDATA%\WLRE_LaLa\diagnostics\health-程序ID.log`。本檔仍採每檔 1 MiB、兩份輪替；舊版已有此資料夾，不代表舊版已記錄連線證據。

新增欄位示例：

```text
connection=receiving reason=none age_s=0.1 packets=300 errno=none keepalive=1
connection=quiet reason=none age_s=121.0 packets=300 errno=none keepalive=1
connection=closed reason=network_error age_s=150.0 packets=300 errno=10054 keepalive=1
ui_callback_error count=1 type=KeyError frames=gui.py:行號:函數
```

同一狀態每五分鐘最多一筆；變更時立即記錄。同一錯誤位置每分鐘最多記一次詳細位置，錯誤總計數仍持續累計。health 不記帳號、密碼、聊天、封包內容、例外文字、區域變數或使用者目錄完整路徑。

封裝的無主控台 EXE 若有建立 stderr 錯誤紀錄，另在 `%LOCALAPPDATA%\WLRE_Client\error.log`；直接執行 Python 時，完整 traceback 通常顯示在主控台。請勿傳送 `login_memory.json` 等登入資料檔。

## 驗證範圍

- 原生 ttk 下拉選單焦點實際重現舊 KeyError，新背景判斷正常。
- 人為注入單次畫面更新例外後，下一輪排程仍存在，並能處理新快照。
- 假時鐘模擬 12 小時持續收資料、兩分鐘沉默、恢復及系統日期變更；沉默不觸發自動登出。
- 模擬接收逾時、恢復及 EOF，最後連線狀態與結束原因正確。
- 10 萬筆顯示洪流下佇列仍有界，保留最新狀態與終止通知。
- 11 萬筆不同角色座標更新後仍為 2,048 筆；Linux／Python 3.11 tracemalloc 的座標快取在 1 萬筆後約 342,695 bytes、11 萬筆後約 346,819 bytes，增量 4,124 bytes。這是該元件的加速壓力測試，不是整個 Windows 程式的實際 10 小時記憶體／網路驗收。

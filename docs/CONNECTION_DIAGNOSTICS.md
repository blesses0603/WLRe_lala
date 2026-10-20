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


## 每兩小時清理

使用單調時鐘，每個連線從建立開始每 7,200 秒清空遠端歷史座標快取，保留自身座標及獨立的權威位置、導航與遊戲狀態。後續收到遠端位置會重新加入快取。此清理在網路執行緒完成；沒有新增背景執行緒或強制垃圾回收。

桌面顯示佇列從視窗建立開始，每 7,200 秒移除排隊超過 120 秒的 walk、position_snapshot、attribute_set 顯示事件。保留最新狀態／連線資訊、錯誤、終止通知、聊天、邀請及其他事件；不清空已顯示內容或遊戲指令佇列。這不改變既有滿載時的容量淘汰規則。容量上限（一般顯示事件 1,024 筆、歷史座標 2,048 筆）在兩次清理之間仍然生效。

health 記錄 `periodic_cleanup display_events_removed=N` 與 `periodic_cleanup positions_removed=N`，只含清理數量。電腦休眠期間不喚醒；恢復後到期時執行一次，不補跑多次清理。Python 釋放資料後，作業系統顯示的程序記憶體不一定立即下降。

假時鐘測試確認 7,199 秒不清、7,200 秒清理及下一週期再清理，並確認自身位置、近期顯示事件、聊天與重要通知保留；不是實際等待兩小時的 Windows 驗收。

## 2026-10-19：跨日 client_error 追查補強（獨立修復 PR）

2026-10-18 至 10-19 的使用者 Log 曾多次出現 `connection=closed reason=client_error`，但舊 Log 未保存造成錯誤的 Python 例外位置，**無法只靠舊 Log 判斷根因**。這次只補齊診斷資料，不推測特定遊戲封包，也不變更遊戲協定、斷線重連、登入、遠征或副本行為。

- `connection_exception type=ValueError frames=client.py:行號:函式 > ...`：網路執行緒在 `client_error` 或 `network_error` 結束時，安全記下原始例外類型及最後六個程式位置。
- `worker_exception count=N type=ValueError frames=...`：網路工作執行緒發生異常時會記錄；也涵蓋開始主連線前的登入驗證、連線清理階段等錯誤。
- 舊版 `connection=...`、`ui_callback_error`、效能統計格式與原本每檔 **1 MiB、兩份輪替** 不變；存放於相同的 `%LOCALAPPDATA%\\WLRE_LaLa\\diagnostics` 目錄。
- 僅從 Python traceback 的程式碼物件提取 **檔案 basename、行號、函式名**；**不存放**例外訊息、原始 traceback 字串、source code、frame locals、使用者絕對路徑、帳密、遊戲封包、聊天內容。
- Log 僅在修正後的新版本重新啟動並發生異常時提供新欄位，無法逆向補全 10 月 18～19 日既有 Log。
- 這次變更是**精準定位所需的記錄修復**，不是聲稱已找到或排除全部既存 `client_error` 根因。驗收應先跑測試，並於之後實機遇到問題時對照新 Log。

## 2026-10-19：領獎後封包診斷補強

- 若網路執行緒處理單一伺服器封包時出錯，健康 Log 的 `connection_exception` 追加純數值 `packet_main=31 packet_sub=19` 及固定處理階段 `packet_stage=decode`（也可能是 `state_apply` 或 `event_handling`）。保留 PR #24 的錯誤型別及程式位置記錄。
- 只在已知封包並已確認拋例外時加入此資訊；連線讀取失敗、一般逾時、正常停止或未有可辨識封包的錯誤不會推測封包 ID。
- 仍不記錄封包位元組、欄位、聊天、帳密、例外文字與完整路徑，沿用 `%LOCALAPPDATA%\\WLRE_LaLa\\diagnostics` 的每檔 1 MiB／兩份輪替。
- 配合修正官方 1262 S31-19 任務更新封包（50 組資料加末尾 Boolean）的解析缺漏；測試涵蓋領獎結果接任務更新、截斷資料拒絕、精確錯誤封包定位及隱私防護。**無法由舊 Log 確認先前錯誤必然是 S31-19，也不代表真實伺服器已驗收。**

## 2026-10-19：新 Log 之 S31-15 解析錯誤

新增 `health-23484.log` 於 19:01:16 顯示 `connection_exception type=ProtocolError ... packet_main=31 packet_sub=15 packet_stage=decode`。這確認 PR #25 的安全封包定位已在使用者端生效，也指出一處有別於 S31-19 的問題：官方 Lua `RevExpeditionStart` 不讀取 S31-15 本文，而原解析器 `r.end()` 拒絕非空本文。

本項只放寬 S31-15 官方未解析本文的消耗方式（只保留數字長度，不保存資料本體）；其餘封包維持嚴格欄位讀取／結尾檢查，並加入模擬實際 TCP 接收的回歸案例。此修正不影響 PR #24／#25 的隱私保護，且不代表實服派遣、領獎、重新派遣等端到端結果已通過實機驗收。


## 2026-10-20：S51-1 戰鬥屬性封包容錯與診斷

- 依官方 1262 `FightManager.RevChangeAttrib`，`S51-1` 每筆資料固定 7 bytes（`col:u8`、`row:u8`、`kind:u8`、`value:u32`）。空封包為合法無操作，完整封包仍按原規則更新戰鬥屬性。
- 當 payload 長度不是 7 的倍數時，不把任何前綴筆數套用至戰鬥單位／HP／SP，也不讓此種單一異常封包觸發 `ProtocolError` 結束連線。此處僅對 `S51-1` 做局部容錯，其他封包仍維持嚴格解碼、傳輸框架驗證與原有錯誤處理。
- 異常封包會由連線工作執行緒送出 `battle_attribute_invalid` 事件（僅 `main/sub`、`payload_bytes`、`complete_records`、`trailing_bytes`），桌面診斷寫入 `protocol_warning packet_main=51 packet_sub=1 reason=invalid_record_length payload_bytes=8 complete_records=1 trailing_bytes=1 count=1` 形式的紀錄。相同類型在 60 秒內合併記錄，累計數持續增加。這不是網路斷線診斷，正常結束仍會紀錄原先的連線狀態。
- 診斷採數字欄位白名單與界限驗證；不記封包原文、帳密、聊天、角色名稱、例外文字或絕對檔案路徑。保留原本 1 MiB／兩份輪替設定。
- **限制**：本次只容錯「封包已完整到達、但 S51-1 本文長度非 7 倍數」的狀況；若實際官方伺服器使用尚未辨識的擴充格式，需取得去識別化證據再確認。不得將略過資料當作已同步成功，也不因此自動補送、重連或開始協力。正式服實機驗收仍待執行。

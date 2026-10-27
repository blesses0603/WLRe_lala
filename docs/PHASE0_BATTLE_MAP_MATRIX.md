# Phase 0：Battle／Map 跨平台行為與驗收矩陣（初稿）

> 本文件定義新 LaLa 應保證的行為與測試案例 ID；它不是封包真值表，也不宣稱所有現有功能已驗收。
> 本階段不填入未核實的封包編號、位元組或伺服器回應碼。個案必須在來源等級核實後，才可轉成正式 golden packet。

## 1. 證據等級

| 標籤 | 意義 | 可以支持什麼 |
|---|---|---|
| `static_code` | 由現有原始碼／測試讀出的行為 | 定位目前責任與既有防護；不能證明服務端接受 |
| `reference_impl` | 由舊版參考實作產生的結果 | 比對相容性；可能繼承舊版錯誤 |
| `official_lua` | 已逐項對照官方 Lua 定義 | 支持對應協定欄位／操作規則；仍不等於正式服 E2E |
| `live_capture` | 脫敏的真實遊戲封包／事件 | 支持觀察到的線上行為；需保留擷取背景 |
| `synthetic` | 人工產生的邊界／負面案例 | 驗證拒絕、不完整資料與錯誤復原 |

所有案例應記錄：case ID、前置狀態、操作／輸入事件、期望狀態與指令數、證據等級、來源連結／雜湊、平台覆蓋、測試層級，以及尚未核實的事項。案例未標記可信來源前，不得用於啟用高風險操作。

## 2. Battle（戰鬥）共用案例

| ID | 前置條件／事件 | 新版預期行為 | 最低測試 | 初始證據／備註 |
|---|---|---|---|---|
| B-001 | 尚未進入戰鬥，或伺服器尚未提供有效回合 | 自動戰鬥不送出行動；UI 顯示等待有效戰鬥狀態 | Domain unit | `static_code`：舊版 `AutoBattle.tick` 有等待回合閘門；新增新版測試 |
| B-002 | 有效回合、玩家／夥伴單位存在且可行動 | 每個合法單位只產生符合策略的一個本回合決策 | Domain unit | 目標指派規則需另由已核實來源定義 |
| B-003 | 同一回合的狀態事件／輪詢重複到達 | 不重送已提交單位的命令；保持同一回合決策狀態 | Domain unit + adapter integration | `static_code`：舊版使用 round key、已決定單位與伺服器命令狀態 |
| B-004 | 單位資料截斷、角色身分未知、目標不存在或目標不合法 | 拒絕產生指令，記錄精簡原因，不猜 ID／技能／目標 | Parser/Domain unit | `synthetic`；不得把不完整資料填成預設有效值 |
| B-005 | 技能／補品資料缺失或耗材數量、格位不可信 | 不送出消耗物品的指令；釋放本次未送出決策的預留，保留其他操作的預留 | Domain unit + reservation regression | `static_code`：舊版戰鬥服務依賴物品資料及 reservation |
| B-006 | 戰後修理／整理、煉金或補給仍有未確認操作 | 自動戰鬥／徘徊依協調規則暫停，不與另一操作競爭同一物品 | Integration | `static_code`：舊版有跨服務 coordination；需寫入新版 contract |
| B-007 | 特殊戰鬥類型未被策略明確支援 | 停止自動下令並顯示「此戰鬥類型未支援」，不採用普通戰鬥 fallback | Domain unit | `static_code`：舊版對部分特殊 war style 採 pause；精確種類需來源核實 |
| B-008 | 指令送出後斷線、逾時或回覆遺失 | 顯示「結果未知／等待重新同步」；不得盲目重送消耗型或戰鬥指令 | Adapter integration | `synthetic` + 後續 `live_capture`；命令已送不等於伺服器已接受 |
| B-009 | 在戰場點選角色／敵方格位 | 選取只改變 UI 的選取狀態；只有明確執行動作才可提交命令 | UI unit + integration | `static_code`：舊版 `BattleView` 宣告 selection only；新版需保留明確分離 |
| B-010 | 收到戰鬥結束、換角、登出或 session 重建事件 | 清理舊回合的 pending／selection；舊 session 的延遲事件不得更動新角色狀態 | State reducer + integration | `synthetic`；必須防止跨角色／跨 session 汙染 |
| B-011 | 玩家連按同一動作、或手動操作與 AI 同時提交 | 以單一 command arbiter / pending key 去重；回覆前不重複接受相同操作 | Domain + adapter integration | 新版規格要求；鍵的範圍需定義（session、round、actor、action） |
| B-012 | 伺服器拒絕行動或回傳無效狀態 | UI 呈現拒絕／未知的不同狀態；只在權威狀態更新後解除相關鎖定 | Reducer + integration | 回覆與狀態事件的優先次序需核實 |

## 3. Map（地圖／移動／傳點）共用案例

| ID | 前置條件／事件 | 新版預期行為 | 最低測試 | 初始證據／備註 |
|---|---|---|---|---|
| M-001 | 登入／進場後尚無可信的伺服器場景與座標 | 顯示未知／同步中；不使用舊快取假裝目前位置已確認 | Domain unit | `static_code` 可定位現有狀態來源；新版需明確標示可信度 |
| M-002 | 地圖圖片、投影參數、場景 ID 或座標資料缺漏／不匹配 | 可展示可用的靜態資訊，但禁用依賴無效座標的點選移動與傳點操作 | Unit + resource fixture | `synthetic`；資源檔存在不等於資料相容 |
| M-003 | 使用者點選地圖上的座標 | 只建立選取／預覽狀態，不隱式發出移動指令 | UI unit | 新版 UX contract；移動應有清楚且可取消的執行入口 |
| M-004 | 開始移動時，session 非 `world_ready`、正在戰鬥或資料未同步 | 拒絕發出命令，顯示可理解原因 | Domain unit + adapter integration | `static_code`：既有服務有 session、戰鬥與事件閘門；新版本仍需明確規格 |
| M-005 | 使用者按停止、離開地圖頁或 session 中止 | 取消當前路徑工作及本模組持有的 pending；不得解除其他服務的戰鬥／事件鎖 | Integration | `static_code`：舊版傳點服務只解除自己持有的 request wait；需回歸驗證 |
| M-006 | 選取傳點目的地 | 只有來源、座標、目的地及直接使用資格均通過驗證時才顯示可執行；否則只可檢視原因 | Domain unit + resource fixture | `static_code`：舊版 1275 policy 需要 `destination_verified`、`direct_eligible` 等條件 |
| M-007 | 移動／傳點請求已 pending 時再次按下 | 不產生重複指令；顯示原本操作的等待狀態 | Domain unit | `static_code`：既有 PortalTravel 有 pending guard；新版須定義 idempotency key |
| M-008 | 傳點請求後未收到可確認的場景切換／回應 | 結果標為未知，不自動再次傳點；繼續等待權威狀態或請使用者重新同步 | Adapter integration | `synthetic` + 後續 `live_capture`；不推測服務端已換圖 |
| M-009 | 場景 ID 改變 | 以新的伺服器場景／座標更新 UI；清除上一場景的選取目的地、路徑與不再有效的傳點 | State reducer + integration | `synthetic`；避免舊場景路徑誤用 |
| M-010 | 路徑不存在、導航圖來源未核實或路線中途失效 | 不偽造可行路徑；停止自動移動並回報具體阻擋原因 | Domain unit + resource fixture | `static_code`：舊版曾對未驗證導航來源維持安全封鎖 |
| M-011 | 座標來回投影換算 | 以固定且來源可信的座標 fixture 驗證正反向換算及邊界；超界值拒絕，不默默裁切 | Geometry unit | 需建立經來源核對的 fixture；不可虛構座標預期值 |
| M-012 | 地圖資源版本／雜湊／schema 驗證失敗 | 不將該資源用於正式移動／傳點；回報缺失或校驗錯誤 | Resource unit | `static_code`：現有資源驗證可作為參考，來源清單需逐項維護 |

## 4. Android 專屬生命週期案例

| ID | 情境 | 新版預期行為 | 最低測試 |
|---|---|---|---|
| A-001 | Activity 暫停／恢復、畫面旋轉或頁面重建 | UI 從 session/service 快照重新綁定；不因重建重送任何遊戲命令 | Android UI／lifecycle test |
| A-002 | App 在背景時遊戲服務仍運作 | 顯示資料標記最後更新時間／連線狀態；服務未回報時不可把過期值當成即時值 | Adapter integration + device test |
| A-003 | IPC timeout、socket 關閉或回應格式錯誤 | 將操作分為 rejected／uncertain；釋放 UI 無限等待，但不自動重送可能有副作用的命令 | IPC unit + integration |
| A-004 | 權限撤銷、通知停用或 Overlay 權限不存在 | 清楚引導權限復原；不可因此偷偷重啟連線或改變戰鬥／移動狀態 | Android device test |
| A-005 | 程序被系統回收後重新開啟 | 不自動續送上一程序的 pending 指令；敏感資料不可從診斷／IPC log 還原 | Integration + security test |
| A-006 | 前景服務停止、帳號登出或 session 移除 | 取消對應 session 的背景任務並隔離其他帳號；舊事件不可寫入已移除 session | Service integration + multi-account regression |
| A-007 | Android 返回鍵／切換頁籤／關閉 Overlay | UI 導覽與連線生命週期分離；除非明確停止，關閉畫面不應隱式提交或取消遊戲操作 | UI + device test |

## 5. 規格化與驗收門檻

- 以上案例是**需求／驗收候選**，不是已通過測試的結果。正式測試應把每列拆成可重現 fixture 或 integration scenario。
- wire framing、login、session 的既有 golden specs 可從桌面 PR #60 參照；將來應由單一規格資料供桌面與 Android 的測試執行。
- 有線上副作用的命令（戰鬥行動、消耗道具、移動、傳點）在其來源未核實前，只允許測試使用合成資料驗證「正確拒絕」；不得用推測的協定資料進行正式服試送。
- 由來源驗證、資源 schema、領域規則、平台 adapter 到 UI 的每一層都需可單獨測試。UI callback 執行成功不是伺服器操作成功。
- Phase 0 結案前：需由每個 case 指定負責模組、證據等級、測試檔案及通過條件，並確認桌面／Android 對共用案例的語義一致。

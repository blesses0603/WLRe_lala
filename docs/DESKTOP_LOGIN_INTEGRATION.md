# Desktop login integration — overall PR 8.0.45

## 2026-11-11 接收與自動化整體核對

接續整合已加入同回合多單位規劃、戰後 2.5／5 秒單次接續、依保存設定執行的修理／整理／補給協調、斜坡分步移動，以及小地圖左鍵雙擊尋路。詳細行為及驗收邊界見 [封包與自動化核對](DESKTOP_PACKET_AUTOMATION_AUDIT.md) 最上方章節。

後續修正主畫面事件洗版：一般伺服器事件同步已從戰鬥 AI 移至帳號生命週期工作；一段接續更新同一筆摘要，一般操作的三階段也合併成一筆。接收端證據仍完整處理，手動 NPC、真正拒絕與未確認錯誤不隱藏、不自動重送。詳見下方核對文件的事件同步修正。

目前版本以 [封包與自動化核對](DESKTOP_PACKET_AUTOMATION_AUDIT.md) 為準：補上換圖確認、接收端操作回覆追蹤、整批下令邊界、場次／回合／格位寫入防重送、固定四點徘徊與一般場景 NPC 動態狀態。先前依重複內容與 32 次接續判定迴圈的保護已移除；真正的伺服器新許可可以繼續，已使用的許可仍不得重用。

## 2026-11-10 角色事件紀錄與場景 NPC 封包核對

使用者錄影顯示大量 S22-2。對照官方 1.3.23 Lua 後確認：S22-2 是場景 NPC 移動（U16 索引、U16 X、U16 Y、U8 速度）；S22-3／10 是 NPC 隱藏、S22-11 是顯示（U16 索引、U16 時間；65535 表示永久）。它們不是玩家位置，也不授予 C20-6 接續許可。相同代碼可包含不同 NPC 的正常場景變化，不能單靠代碼重複斷定自動化循環；修正先前尚未核對內容時的推論。

- 新增上述唯讀型別解碼，驗證完整欄位長度；不推算速度單位、時間換算、動態導航幾何或完整 NPC 動畫。
- 收包端維持原本的狀態處理及 500 筆操作回覆緩衝，另保留最近 200 筆明確屬於目前角色的顯示紀錄。場景流量不會擠掉角色歷史，亦不會因 UI 篩選而停收或改變遊戲狀態。
- 角色紀錄保留自身位置、屬性、背包、金幣、直接操作回覆、事件接續及自身參與的戰鬥；排除場景 NPC、附近角色及歸屬未知的封包。帳號／角色切換會清除舊角色紀錄。操作紀錄仍屬同一帳號執行通道；沒有新增全場景顯示開關或磁碟封包側錄。
- 主畫面移除全部封包的累計總數及全域序號，只顯示目前角色與角色事件。

證據：官方 [Lua 清單](https://wlreftpsrc.chinesegamer.net/WLN/TW/1.3.23/LuaScripts/LuaScriptPathList.txt) 與 `Lua/Logic/Protocols/Protocols_022.lua`、`Lua/Logic/Stage.lua`。下載的加密檔逐一核對清單 MD5，使用既有已獨立釘選的官方 APK metadata SHA256 解碼；該 metadata 為 `5a71da3a4b37486b056b9873655e42d7d7a583eae6ebfe2efdd18ebe66a23260`。解碼後 Protocols_022 SHA256 為 `6a29ba64b10da01bf3cc79ce9d9bb93afc20e0a68f588bfec744d21a0cd7e9a5`，Stage 為 `784b5098241463159112b29fa81ca23dfa9a2cc24dd3fe20ec29f1a05df52605`。官方原始 Lua 及金鑰未加入儲存庫。

## 2026-11-10 自動事件接續保護

- 新增帳號所屬的事件循環保護，在實際傳送通道核對並消耗接續許可；相同許可不重複使用，新許可會使排隊的舊意圖失效。
- 內部操作回覆只為 S20 與 NPC 顯示／隱藏指令加入內容 SHA256；不保留原始 payload，也不將聊天或登入內容加入指紋。
- ~~依重複內容或 32 次無角色進展停止接續~~：已於 2026-11-11 移除。相同代碼與內容可以是合法事件步驟；現在以接收端真實許可、整批完成及單次消耗核對，不能自行設立官方沒有的步數限制。
- 不再因代碼／內容重複而停止 AI；保留真實事件阻擋狀態，不偽造結束或新增 S22 回覆。同一正式連線不重用已消耗許可；新的正式連線使用獨立序號。
- 接續操作改為要求實際收到事件回覆，單憑本機旗標變化不報成功；角色重新定位及進入戰鬥時撤銷舊許可。手動 NPC 選項及其單次接續維持原本流程。

以上驗證包含離線解析、收包緩衝及本機模擬伺服器；不代表正式服完整自動化驗收。徘徊已於 2026-11-11 加入途中遇戰及補給中斷；完整戰後維護／排程協調仍需另行核對，不能宣稱所有封包代碼已分析完成。

## 2026-11-10 接續檢查點：野外自動補給

本批接通原先只保存草稿的野外 HP／SP 補給與藥水儲存槽。設定入口為主畫面補給設定／AI 設定的「補給設定」頁；總開關預設關閉，保存不啟動，須自行啟動戰鬥 AI 或徘徊才會按門檻執行。套用會更新這兩項已啟動功能，不會把已停止功能重新啟動。

- 角色及目前出戰夥伴各自使用 HP／SP 門檻，嚴格低於百分比才回復；沒有確認 HP、最大值或存活狀態的對象不推算，也不進行復活。
- 每種資源保留 10 格指定物品優先序，接上背包補品選擇、搜尋及清除；僅列出同版官方資料已核對的回復效果，排除鎖定、限時、保留及帶負面 HP／SP 效果的物品。匯入的指定 ID 仍需通過核心效果驗證。
- 接通「儲存槽優先／指定補品之後／停用」及其他背包補品選項。儲存槽依已同步餘額、實際缺少量及單次 65,535 上限規劃 C23-147，不會自行補滿未知數值。
- 每次補給均經帳號操作佇列，寫入前核對角色、同版資源、背包、補給餘額、夥伴及事件狀態。物品扣除須維持同格物品 ID、序號與序號版本，並確認原對象 HP／SP 回升。
- 儲存槽要求同資源及同對象的 S23-208 使用回覆，加上同對象回復。若伺服器餘額已扣除不再重扣；僅收到使用回覆時，在核對回復後依該回覆扣帳一次。餘額變動無法關聯、對象更換、拒絕或逾時都不視為成功，也不自動重送。
- 每輪新徘徊前先檢查補給，不足時不啟動下一輪；路途中遇戰後的接續與補給協調仍需加強。已送出補給即使按下暫停仍等待確認，沒有因取消而重複消耗。資源投影依同一候選資料快取，退休後可回收，避免自動輪詢反覆重建整份物品／特技索引。

本批沒有登入正式服或消耗實際道具。來源為既有 Python `recovery.py`／`field_supply.py` 及已核對的 C# 補給候選器。核心回歸與本機 loopback 驗證了優先順序、門檻、出戰夥伴身分、格位替換、錯誤回覆及暫停後確認；桌面補品選擇也使用實際原生視窗驗證。

驗證紀錄：Debug 建置 0 警告／0 錯誤；補給與相關物品／自動化回歸 2,862 項通過；桌面離線檢查 9＋100 項、原生 UI 310 項通過，輸出 36 張畫面並檢查新增補品選擇視窗；Android 生命週期相容性 79 項通過。操作回覆的起點也移到實際取得傳送通道時，排除排隊期間已抵達的舊回覆。

剩餘待辦：維護／修理／清理、C# 發行更新、副本及製作排程回覆關聯加強、方舟完整自動流程，以及海上／飛行／斜坡導航與正式服操作驗收；先前一次連線結束原因仍待追查。下方舊檢查點的野外補給待辦已由本節接續。

## 2026-11-10 接續檢查點：製作、助手與互動

本節接續下方暫停檢查點；這一批新增功能已接到桌面與共用核心，仍不能視為全部 Python 功能完成或正式服驗收通過。下方較早的唯讀／Held 說明保留歷史脈絡，以本節及實際操作守衛為準。

- 自訂製作清單：搜尋官方配方、編輯批數、排序及分帳號保存；開始後透過既有製作操作等待入列回覆及材料扣除，再前進清單。同次連線可暫停及繼續，重新登入只載入草稿，不推算已完成進度；重新執行整份清單須明確按下獨立按鈕。
- 每日助手：整合魔方／每日獎勵、組織簽到／有預算捐獻，以及方舟派遣／問答／戰鬥選項。保存不啟動，全部自動選項預設關閉；開始僅啟動勾選的功能，方舟戰鬥還要求實際戰鬥 AI 已啟用。
- 必要隊員：可輸入角色 ID 或唯一且已同步的附近角色名稱，匯入目前隊伍、驗證重複／自家角色後套用。AI 設定與隊員條件可更新正在運作的戰鬥 AI；核心序列化設定切換，停止中的 AI 不會被較晚的更新重新啟動。
- 經驗效率：角色／已確認夥伴、全部／最近 10／30 場、分／時／日單位、升級估時與重設已接線；重設只清除本次連線的效率樣本，不修改角色經驗或發送遊戲操作，資料不足時不顯示推算數值。
- NPC 更多互動：獨立對話視窗顯示伺服器對話、經官方事件資料核對的一般選項、繼續及分開的選單關閉。選項綁定精確場景、互動與提示序號；新提示會撤銷舊選項，選擇後僅消耗一次接續授權。修正繼續封包的來源相符 payload。商店交易及未識別的特殊選單不因此啟用。
- 帳篷離開：主畫面新增入口，僅使用座標與來源關聯均已核對的唯一官方出口；標記式出口另要求已知戶外返回場景及已驗證文字。缺少或衝突資料會阻擋，必須收到伺服器戶外位置才算離開。
- 設定改以帳號與伺服器群組的穩定不透明雜湊識別保存，重新登入可保留各自草稿，換帳會關閉舊功能視窗及撤銷舊回呼。原有隨機識別設定不刪除，也不猜測遷移歸屬。
- 登入頁顯示清單逾時不再直接使完整登入表單失效；實際 TCP 連線及每次帳密送出前仍重新取得官方資料，核對端點、分流、支援版本及已準備資源，沒有跳過驗證或重新下載資源。

仍待完成：野外自動補給與儲存槽、維護／修理／清理、C# 發行更新；副本及製作排程的回覆關聯仍需加強，方舟完整自動流程與正式服操作仍待驗收，先前一次連線結束原因仍待追查。導航的海上、飛行及斜坡執行也尚未完成。

本批驗證：桌面 Debug 建置 0 警告／0 錯誤；核心相關回歸 2,186 項通過；桌面離線檢查 9＋99 項、原生 UI 檢查 303 項通過，輸出並檢查 35 張畫面中的新增功能畫面；Android 生命週期相容性 79 項通過。Windows loopback 的斷線測試現在接受正常 EOF 或 TCP reset，仍要求連線確實結束。

本批以合成資料、原生視窗及本機 loopback 驗證，沒有使用正式帳號消耗道具、金幣、星力或屬性點；尚未提交或發布。

## 2026-11-10 暫停檢查點：桌面遊戲功能接線

本批仍在開發，不能解讀為 Python 功能已全部移植或全部通過正式服驗收。
使用者要求「到一個段落先暫停」；接續工作應從本節待辦開始，保留目前所有未提交變更。

- 已新增帳號所屬的語意操作入口與序列化傳送，實際寫入前核對角色、場景及資源生命週期；需要回覆的操作等待指定狀態，逾時或結果不明不自動重送。
- 已接線：組隊、夥伴出戰／休息、配點、背包補給及儲藏存取、副本房間、魔方／每日獎勵、組織簽到／捐獻、遠征派遣／領取／好友度恢復、有限次煉金、製作配方及伺服器排程、方舟派遣／問答。功能各自保留資料與容量守衛，尚未逐項完成正式服驗收。
- 導航新增原生 C# 同版 Bundle／A* 快取讀取、路線及步伐檢查、受控移動與停止、遇戰暫停，以及僅沿入口及目的地均已核對的出口規劃跨圖行程。跨圖與實際移動仍待正式服驗收；海上、飛行及斜坡執行尚未完成。
- 方舟戰鬥已有送出與結果／入包核對程式；戰鬥 AI 協調、待處理事件及獎勵種類仍需補測，不能視為完成。
- 已依使用者明確授權，以已儲存帳號實測登入及選角：主畫面顯示「已連線｜資源已就緒」，角色／夥伴頭像、小地圖及即時座標載入；登入沒有重跑整套資源準備。沒有實測消耗道具、金幣或星力。
- 官方來源的獨立唯讀解析測試讀得：86 個消費方案、512 個公式、10 個組織等級、20 個星球、20 個情報員、352 個方舟戰鬥定義；導航 11016 解出 201 個三角形、73 個可行走節點及有效預覽路線。這些測試不等同正式服操作成功。

待接續：自訂製作清單與保存／繼續、每日助手整合、必要隊員名單編輯器套用、野外自動補給與儲存槽、維護／修理／清理、經驗效率完整視窗與重設、NPC 選項／更多互動、帳篷離開、C# 發行更新。另需強化副本及製作排程回覆關聯、執行中 AI 設定更新、方舟自動流程，並追查實測出現過一次的連線結束原因。

登入結束原因現會保留在主畫面狀態，避免清理後只顯示「尚未連線」。所有新自動功能預設不啟動；本次尚未提交或發布。

暫停前驗證：Debug 建置成功（0 警告、0 錯誤）；本批核心／loopback 回歸 51 項通過；原生桌面 UI smoke 269 項通過並輸出 32 張畫面。UI 檢查修正了未登入時導航同步／開始仍可按的守衛，並把舊有「全部尚未接通」文字斷言更新為實際的離線登入守衛斷言。這些合成／loopback 測試不代表所有正式服操作均已完成驗收。

目前正式桌面路由先自動完成 [登入前必要資源準備及精確同版 gate](DESKTOP_RESOURCE_INTEGRATION.md)，才允許登入。按「登入」後自動連線，不再顯示資源寫入或逐次帳密傳送確認視窗；每次帳密傳送前仍自動核對選定端點、官方分流與資源版本，角色由使用者選取。下文保留核心接線與歷史驗證。

The Avalonia login and role controls use shared Core preparation. The Python-compatible
server/line dropdowns now load official HTTPS metadata through `OfficialServerDiscovery`.
Protocol bytes and the verification endpoint come from the reviewed Python release profile,
never editable text fields or downloaded rows. Unknown executable versions/groups, failed or
stale target revalidation and no selection block transport admission. An expired displayed list may request a new revalidation. See [the full parity inventory](DESKTOP_PYTHON_PARITY.md)
for provenance, limitations and the remaining UI work. Account preferences can be remembered;
on Windows an opted-in password is protected with current-user DPAPI. Portable settings never include passwords.

## Saved accounts

Role selection uses clickable cards with server-provided name, level, element, HP/SP and
locked status. Element badges use the original official MainPackage sprites; provenance is
recorded in `wlre/resources/assets/elements/SOURCE.md`. Role portraits use the server role's
sex/head and palette fields with the existing reviewed character mapping and verified prelogin
portrait readback. No WorldPlayer is fabricated to render a role. Missing mappings or pixels
leave the portrait slot empty. The portrait request checks resource activation throughout rendering;
the UI separately binds display to the exact current role-selection request and disposes its
portrait workers when selection ends. These visuals do not grant login or game-command authority.

The login page supports new, save, select and delete account profiles, remembering a server
group and official line ID. Profiles do not contain endpoints or protocol parameters, and a
saved line must still exist in the current official catalog. Missing lines require explicit
selection. Selecting a profile never initiates a connection. Enter submits a complete login
form or the selected unlocked role. Profile controls are frozen during a connection attempt.

Local preferences are stored in `LocalApplicationData/LaLa/Desktop/Login/accounts.json`.
Remembering a password also remembers the account; unchecking the password option removes
the stored encrypted password, and deleting an account removes its saved password as well.
Windows DPAPI binds protected passwords to the current OS user; other platforms support
account preferences without password persistence. Decryption failures require password input.
The Load/Save settings buttons import/export a versioned account-only JSON file using native
file pickers. Imports merge accounts and validate schema, size, duplicates and line identifiers;
imports cannot supply passwords, resource paths, endpoints or connection permissions.

## User flow and transport risk

0. Startup opens the separate version/resource window. It inspects the managed local resource
   root, queries official metadata and automatically prepares verified resources. Local
   self-consistency cannot admit login. Continue requires fresh supported metadata and matching resources.
1. Select a server and line from the verified current catalog, then enter credentials locally.
   Changing the server/line or refreshing clears both credential fields.
2. Press Login. The controls freeze for this attempt; input transfers into Core-owned
   transient buffers and both credential text fields clear. Profile changes require a new attempt.
3. The Login click authorizes this single connection attempt. Before each credential send,
   the Desktop callback checks the selected recipient endpoint and revalidates the official
   target and resource version without a modal. Raw TCP has no TLS and fixed XOR is reversible;
   this remains disclosed on the login page. Both admissions must occur within the preparation's
   one-minute validity. Stop or close cancels the attempt.
4. Select an unlocked server-provided role explicitly, then press Confirm role. That action
   authorizes this request's role-selection send and continuation of the disclosed world-login
   ACK/heartbeat protocol. Core's two-minute login deadline still applies; no default is sent.
5. The dashboard opens only after Core reports completed login protocol and publishes a player.
   The integrated runtime binds the startup preparation's existing verified activation in memory.
   Login does not download, decode, revalidate or write those resources again. Disconnect revokes
   only the account binding; the startup preparation retains ownership for later logins. Stopping
   or replacing that preparation revokes every borrowed binding, without an automatic retry.
   Official target metadata is still checked before credential sends. General game commands follow the current checkpoint's per-feature admission and acknowledgement rules.
6. Disconnect, close, or application quit cancels and awaits Core cleanup and pending callbacks.
   The presentation snapshot is reset; another attempt needs fresh input and a new Login click.

No plaintext password is written to settings, exports, logs or process arguments. Core clears owned byte
buffers; clearing Avalonia text cannot promise immediate erasure of immutable .NET strings.
Exceptions are rendered as fixed generic status text rather than copying arbitrary exception
messages. Account runtime uses a fresh opaque identity; desktop preference scopes use an opaque hash of the account and server group, without storing the account name in those feature files.

## Boundary and review

`IAccountLoginSendConfirmation` is optional for existing host compatibility. Desktop always
installs it. The callback runs outside lifecycle locks, before each actual credential-write
admission. Core rechecks cancellation, generation, expiry, recipient and leg after callback
completion. A late approval cannot revive an ended attempt; disposal awaits even a late
callback. The existing credential leases and transport retirement retain ownership of packet
cleanup. The selector remains bound to one server request and disallows locked roles.

Source review covered duplicate click prevention, disabled profile edits, credential clearing,
per-leg target revalidation, cancelled/late replies, manual role choice, UI-thread callbacks,
awaited close/stop, stale publication rejection and held game-command state. No independent
reviewer or production acceptance is claimed.

## Previous 8.0.41 validation (historical)

- Complete Core: 45,096 passed; login-focused subset: 78 passed (including seven new
  decline/failure and late-approval retirement cases).
- Public Core consumer: passed. Android lifecycle: 76 passed. Python release/preflight: 31 passed.
- Desktop offline: inspector 9 + presentation 54 passed.
- Real Avalonia Linux UI under Xvfb: 142 existing/adapted checks, plus 11 loopback login
  assertions; 16 screenshots rendered and login layout inspected.
- Loopback UI drives actual buttons and dialogs through verification, formal login, manual
  role selection, world ACKs, Core publication, stop, and closing a pending confirmation.
  Only explicitly synthetic credentials and ephemeral 127.0.0.1 listeners are used.
- CI now runs the UI/loopback suite on Linux in the existing .NET workflow. Cross-platform
  CI and native Windows/macOS/official-server acceptance are separate evidence.

No real-server connection or general game instruction was sent during this work. Do not
interpret offline/loopback success as secure transport, resource readiness, official endpoint
verification, successful live authentication, or complete game-state support.

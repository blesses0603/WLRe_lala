# Desktop login integration — overall PR 8.0.45

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
stale catalogs and no selection block admission. See [the full parity inventory](DESKTOP_PYTHON_PARITY.md)
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
   Official target metadata is still checked before credential sends. Every general game command remains unavailable.
6. Disconnect, close, or application quit cancels and awaits Core cleanup and pending callbacks.
   The presentation snapshot is reset; another attempt needs fresh input and a new Login click.

No plaintext password is written to settings, exports, logs or process arguments. Core clears owned byte
buffers; clearing Avalonia text cannot promise immediate erasure of immutable .NET strings.
Exceptions are rendered as fixed generic status text rather than copying arbitrary exception
messages. Account presentation uses a fresh opaque identity, not a stored account name.

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

# LaLa Android 連線生命週期（v0.2.0 開發候選）

本專案是 PR79 的 C#／Avalonia Android host，沿用同一份 `Lala.Core`。已建立可接入核心的連線生命週期與 Android 系統整合；**共用核心的登入、TCP transport、正式服操作仍未完成**。預設 `UnavailableConnectionAdapterFactory` 明確回報未接入，不開 socket、不假造登入成功、不保留空白前景服務。本版不能取代既有 Python Android 客戶端。

Android 版本獨立由 `0.1.0` 提升為 `0.2.0`，`ApplicationVersion` 由 1 提升為 2。桌面 Python 版本維持 main 的 `7.3.1`；沒有建立 Release／Tag。見 [CHANGELOG](CHANGELOG.md)。

## 所有權與分工

| 檔案 | 責任 |
| --- | --- |
| `Lifecycle/ConnectionCoordinator.cs` | 純 C# 狀態機、單一選定帳號、會話世代、連線／清理逾時、有限重試、取消與舊回覆隔離。 |
| `Lifecycle/ConnectionContracts.cs` | 不含 Android 物件的 adapter、目標、快照及時間策略。 |
| `Platform/ConnectionService.cs` | 前景服務與程序內唯一 runtime；舊服務仍在清理時，新服務沿用同一 coordinator，不能另建 socket。 |
| `Platform/ConnectionServiceClient.cs` | Activity 的綁定與命令入口。重新開啟只取得快照，不重新登入。 |
| `Platform/ServiceCommandState.cs` | 啟動 epoch 與原子 owner lease；舊停止命令、清理完成與通知動作不能干擾新會話。 |
| `Platform/AndroidNetworkMonitor.cs`、`NetworkAvailability.cs` | API24+ default network callback、API23 多網路相容；過期網路回呼不能覆蓋新網路。 |
| `Platform/ConnectionNotification.cs` | 私密、低重要性的連線通知及停止按鈕；不顯示帳號、端點、帳密或原始例外。 |
| `AndroidApp.cs`、`AndroidMainView.cs`、`MainActivity.cs` | Android 狀態頁與通知設定；保留共用離線封包檢視器，畫面停止只取消離線解析及解除綁定。 |

正式產品仍為 Core／Desktop／Android 三個專案。`Lala.Android.Lifecycle.Tests` 是測試專案，以 `Compile Include` 測相同來源，不增加另一份 runtime 或核心。

## 生命週期行為

| 情境 | 行為 |
| --- | --- |
| 開啟 App、返回畫面、Activity 重建 | 只 bind／訂閱目前快照；不建立連線、不自動申請通知、不自動登入。 |
| 使用者手動開始 | 核心未接入則拒絕；核心接入後，必須從 resumed Activity 且通知已允許的狀態開始。 |
| 通知拒絕／頻道關閉 | 暫緩啟動，顯示固定原因。這是產品政策；Android 本身不以通知拒絕直接禁止所有 FGS。 |
| 通知被永久拒絕 | 記錄非敏感的「已請求」狀態，改開啟系統通知設定，不反覆呼叫已不會顯示的權限對話框。 |
| 授權通知後 | 回到狀態頁；不自動接續開始，需再次明確操作。 |
| 相同帳號重複開始 | 不新增第二條會話。 |
| 切換帳號 | 先取消並釋放舊 adapter，再建立新會話；舊世代成功回呼無效。 |
| Home、鎖屏、切換 App | 已啟動的 Service 持有會話，Activity 不停止連線。Doze／省電／程序回收仍可能中斷，沒有永遠在線保證。 |
| 網路失去／尚未驗證 | 取消目前 attempt，清理後等待網路；不宣稱伺服器已登出。 |
| 網路恢復 | 只能排程有限重試；是否 Active 由核心 adapter 確認。 |
| 連線超過 30 秒仍未 Active | 取消並清理後，依同一重試預算退避；Active 後取消此 watchdog。 |
| 明確可重試的失敗 | 預設最多 5 次重試，一次手動開始共最多 6 次 attempt；短暫 Active 不重置預算。 |
| 登入拒絕、資源 hold、未知錯誤、核心缺席 | 不自動重試。 |
| 停止／登出 | 取消 attempt、等待與重試；確認清理後移除通知並結束 started service。 |
| 清理超過 5 秒 | 顯示 `CleanupBlocked`；不把逾時視為資源已釋放，不另開第二條連線。 |
| 最近工作清單滑除 | `stopWithTask=false`；已啟動會話由通知提供停止操作，不用 alarm 復活。 |
| Android timeout／Task Manager 停止／程序死亡 | 停止服務；`NotSticky`、沒有 boot receiver、沒有帳號／Intent 還原，不自動重新登入。 |

**本階段只有一個選定帳號的 lifecycle slot。** 舊 Android 的多帳號集合、Keystore、套件簽章驗證、懸浮球、wake lock 與完整資料驗證流程仍待移植；不標示為功能等價完成。切換帳號測試只驗證所有權與清理邊界。

## 接入尚在建立的共用核心

1. 在 Android 平台層提供 `IConnectionAdapterFactory`，接到 `ConnectionRuntime.Factory`；無需更動 Core 現有 `AccountSession` API。
2. `Create(ConnectionTarget)` 只建立擁有者，不做同步網路 IO。`ConnectionTarget` 是不含密碼／token 的不透明帳號參照；安全憑證取得由受審查的核心 adapter 處理。
3. `RunAsync(onActive, cancellationToken)` 持有該次會話直到結束；核心確認登入／會話可用後才能呼叫 `onActive`。`AccountSession.Verified` 只代表資源 gate，不能當登入成功；`ConnectionHealth.Quiet` 不等於斷線。
4. 取消後結束工作，`DisposeAsync()` 確實關閉資源。回傳固定 `ConnectionEndReason`；只有已確認的暫時失敗適合重試。不得透過例外字串、通知、Intent 或 Log 傳出敏感資料。
5. 登入畫面完成資料／帳號前置檢查後，於手動操作呼叫 `ConnectionServiceClient.StartFromUser(target)`。它回傳的是啟動請求已送出，畫面仍需以後續 snapshot 判定狀態。
6. 不重播未確認的遊戲指令。重連後的重新驗證、狀態同步、憑證及協定安全由 Core 負責。

`RemoteClosed` 預設是終止原因，避免伺服器踢線或明確拒絕後持續重登。只有 adapter 能確認為可重試的 transport 中斷，並排除認證、資源與明確伺服器終止時，才回傳 `TransientNetworkFailure`。

Service 使用不對外開放的 local Binder；Android 啟動 Intent 僅含一次性記憶體 ticket，不含帳號或端點。程序死亡後 ticket 失效。綁定成功本身不啟動 FGS。

## Android 平台決策

- 最低 API23，target `net10.0-android36.0`，Avalonia.Android 12.1.5。
- 前景服務採 `specialUse` 並聲明 subtype：使用者手動啟動、可持續於背景、附可見狀態及停止按鈕的遊戲連線。這是用途判斷，**不代表 Google Play 已核准**。
- 不使用 `dataSync` 承諾無限常駐。官方對 target Android15+ 的 `dataSync` 背景執行設有每 24 小時合計 6 小時限制。
- 只宣告 INTERNET、ACCESS_NETWORK_STATE、FOREGROUND_SERVICE、FOREGROUND_SERVICE_SPECIAL_USE、POST_NOTIFICATIONS；沒有新增懸浮窗、儲存、開機啟動或 wake-lock 權限。
- `INTERNET && VALIDATED` 只代表 Android 網路條件，不代表特定遊戲伺服器可達。

官方依據：[FGS 類型](https://developer.android.com/develop/background-work/services/fgs/service-types)、[啟動限制](https://developer.android.com/develop/background-work/services/fgs/launch)、[通知權限](https://developer.android.com/develop/ui/compose/notifications/notification-permission)、[網路狀態](https://developer.android.com/develop/connectivity/network-ops/reading-network-state)、[使用者停止 FGS](https://developer.android.com/develop/background-work/services/fgs/handle-user-stopping)。

## 建置與驗證

```sh
dotnet test dotnet/Lala.Android.Lifecycle.Tests/Lala.Android.Lifecycle.Tests.csproj -c Release
dotnet test dotnet/Lala.Core.Tests/Lala.Core.Tests.csproj -c Release
dotnet workload install android
dotnet build dotnet/Lala.Android/Lala.Android.csproj -c Debug -p:EmbedAssembliesIntoApk=true
```

Android 建置需完整 JDK21、Android API36／build-tools36 與 .NET10 Android workload。`EmbedAssembliesIntoApk=true` 讓 Debug APK 包含 managed 程式，不依賴 IDE 的 Fast Deployment。CI 同時執行 Windows／macOS／Linux 的純生命週期測試，以及 Android 真正 APK 建置；debug APK 只供檢查，不是正式版。結果依 PR79 最新提交與 Actions 記錄判讀。

### 本次本機驗證紀錄

整合基準為 PR79 `d67f54e` 加上本次 Android 增量；沒有改動該基準的 Core 程式或測試。

- 純生命週期測試：**59 通過、0 失敗、0 跳過**（coordinator 40、網路狀態 12、服務命令／owner lease 7）。
- 最新 Core 回歸：**8,201 通過、0 失敗、0 跳過**；數量包含既有合成 parity／邊界案例，不代表 8,201 項完整遊戲功能。
- Desktop Release build：**0 warnings／errors**；離線檢視器 self-test **9 項通過**。
- 既有 Python 文件／發行稽核 **5 項通過**；strict repository audit 通過。保留根 README 的桌面發行摘要在第一段，Android 增量說明置於其後。
- Android Debug APK：實際編譯／打包與簽章檢查通過；內容包含 ARM64／x64 的 `Lala.Android`、`Lala.Core` managed DLL。Debug 簽章不是正式發行簽章。
- aapt2／merged manifest：versionName `0.2.0`、versionCode `2`、min23／target36；唯一連線服務未 exported、`stopWithTask=false`、`specialUse` 與 subtype，五項必要權限正確。
- 本機受限環境的多 RID 平行 MSBuild 曾失敗；以 `-m:1 -p:_AndroidBuildRuntimeIdentifiersInParallel=false` 完成相同 ARM64／x64 目標，沒有減少打包內容。CI 使用一般建置。
- Android 安裝／實機／正式服驗收：**未執行**。以下分層清單仍須逐項完成。

| 驗收層級 | 本階段可證明的範圍 |
| --- | --- |
| 純 .NET 測試 | 以可控制完成時間的測試 adapter／delay 檢查競態、停止、切帳、重試預算、清理失敗與網路事件；不是正式伺服器測試。 |
| Android build／APK | 平台 API、manifest 與封裝可編譯；不是手機安裝、鎖屏或 Doze 證明。 |
| 手機／模擬器 | 預設 adapter 不可用；可先驗收狀態頁、通知授權、前背景與不自動登入。真正 FGS 會話持續需接入核心或獨立受控測試 host 後驗收。 |
| 正式服 | 等待 Core transport／登入完成及可用測試帳號；本階段未執行。 |

### 核心接入後的實機清單

至少分層驗證 API23、31、33、34、36：通知允許／拒絕／關閉頻道、快速開始→停止→開始、Home／鎖屏／旋轉／返回、Wi-Fi→行動網路、飛航→恢復、captive portal、切換帳號、服務停止及程序死亡。每案同時記錄服務是否存活、attempt 是否唯一、通知是否清除、舊回覆是否復活，不能只以畫面狀態驗收 socket。

```sh
# Android13+ Task Manager 等效停止；重開後不得自動登入
adb shell cmd activity stop-app io.lala.migration
# Android13+ 通知拒絕路徑
adb shell pm revoke io.lala.migration android.permission.POST_NOTIFICATIONS
```

完整登入、正式服連線、多帳號等價、實機前景服務、簽章／安全儲存及舊資料遷移全部保留未驗收狀態。

### Opt-in Core lifecycle adapter (cloud integration)

`CoreConnectionAdapterFactory` now bridges the lifecycle coordinator to the public
`AccountConnectionRuntime`. `Create` is inert. A caller-supplied
`ICoreConnectionSelectionResolver` resolves opaque selection keys only during Run,
providing an explicit endpoint/profile and a caller-owned credential source. The
adapter never disposes that source; Core disposes each transferred credential object.
No credentials belong in targets, Intent extras, environment variables, files or logs.

Each lifecycle attempt uses exactly one Core attempt, regardless of supplied Core
retry options. Only Core's typed retry eligibility permits a lifecycle retry; unknown
or uncertain write outcomes are terminal. Cleanup must finish before replacement.
Protocol login reports `ReceivingHeld`, cancels the connect watchdog and **does not**
report gameplay `Active`, bootstrap resources, or authorize commands. Network loss and
stop drain that same owner; late callbacks cannot revive an obsolete generation.
Natural Core retirement also starts the cleanup watchdog, without overwriting Core's
final failure/retry evidence or pretending that a timeout proves resource release.

The service's production default remains `UnavailableConnectionAdapterFactory` until
secure selection/provider integration exists. Synthetic loopback tests cover real Core
verification/login/receive and lifecycle cleanup, not official service login, Android
hardware, database bootstrap, or release readiness. Existing verification totals above
are historical and are not totals for this increment.

Cloud checks for this increment: lifecycle **76 passed, 0 failed, 0 skipped**;
focused public Core connection-runtime and optional-skill projection tests **14 passed,
0 failed, 0 skipped**. These are focused checks, not a full Core suite or an Android APK,
phone, official-server or release acceptance run.

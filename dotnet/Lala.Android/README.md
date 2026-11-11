# LaLa Android 連線生命週期（v0.2.0 開發候選）

## 2026-11-10：Android 官方連線與模擬器預覽

共用 Core 已優化啟動圖資快取驗證：有效快取不再整批重寫，小地圖建立後省去第二次解碼，並顯示實際處理張數；下載改用精確大小緩衝以減少複製。版本、完整性及容量檢查保留，詳見 [資源效能說明](../../docs/DESKTOP_RESOURCE_INTEGRATION.md#2026-11-10-啟動驗證與快取效能)。重新建置並安裝預覽後套用，不代表目前已安裝的 App 已更新。

Android 現在預設開啟官方模式，第一個畫面是「資料／資源」檢查：取得官方 HTTPS 版本及分流清單，使用共用核心驗證資源，就緒後按「進入登入」，再由首頁手動登入、選角及接收資料。登入使用啟動前準備好的同版資源，不再次下載、驗證整套資料。分流清單即使超過五分鐘，仍可提出單次登入請求；adapter 會在建立 TCP 前及每次傳送帳密前，重新取得官方清單，核對所選分流與資源版本。若官方版本或分流實際改變，才停止並提示重新檢查。

`Platform/OfficialAndroidClient.cs` 將既有 `AccountRuntime` 接入單一帳號的前景連線服務；密碼只交付當次登入，不放進 Intent、設定檔或日誌。Android 不讀取 Windows 加密保存的密碼。通知允許且服務綁定後才接受登入；不自動重試或重播帳密。TCP 遊戲登入沿用官方既有協定，沒有宣稱支援 TLS；官方資源清單使用 HTTPS。

本機拒絕登入請求時會保留表單供修正；請求已接受後才清空帳密。系統通知狀態在 Activity／服務／權限事件更新，實際啟動服務仍獨立即時檢查；輸入及畫面輪詢不再反覆呼叫系統通知服務。

五分鐘清單逾時修正另加入三項離線測試：允許用新觀測重新確認較舊的選擇、拒絕過期的新觀測，以及拒絕分流或版本改變；生命週期測試目前共 79 項通過。表單另驗證本機拒絕時保留輸入、接受請求後才清空。模擬器的官方驗證 TCP 連接探測成功，沒有傳送帳密；尚待使用者重試真實登入，不能將探測成功當成帳號驗證成功。

正式模式的角色、背包、夥伴、聊天、組隊、製作排程、遠征及地圖均只讀取伺服器快照；可用操作由核心的實際連線與資源狀態決定。聊天送出、組隊、補給、配點、夥伴出戰、帳篷、製作排程、遠征領取、自動化與步行導航會呼叫共用核心，按下操作才送出；核心可因資料不足、未同步或不支援而拒絕。角色圖片只使用已驗證的官方資料，缺少時顯示待同步。

仍有限制：目前只有一個正式帳號連線；完整副本管理、煉金材料選取、NPC／儲藏／福利的手機操作介面尚未接齊；正式自動化目前使用核心預設規則，示範設定不會套用。沒有以範例內容代替正式資料或宣稱所有功能已完成。下列設計示範可在停止連線及資源準備後，從首頁「切換介面示範」進入，並可隨時返回官方模式。

官方接線驗證：Android Debug 建置無警告或錯誤；既有生命週期 76 項測試及啟動資源重用／遊戲操作的 6 項核心測試通過。連結實際控制項的離線檢查確認資源、通知及服務准入條件、單次帳密交付後清空輸入、正式頁面不顯示範例帳號、切頁不送出遊戲操作，以及啟動資源頁與四個底部分頁。模擬器實際取得官方 1.3.0／1.3.23 清單，並完成主要資料、頭像及小地圖 SQLite 寫入。尚未以真實帳號驗證 Android 登入／選角與世界同步，不將以上檢查視為認證成功。

手機預覽依使用者提供的五張參考圖改為深藍夜空、青色發光卡片與城堡橫幅，底部固定「首頁／包包與特技／運行紀錄／工具箱」四個入口，不再放置資料／資源分頁。首頁有登入排版與多帳號範例卡；角色功能進入角色概況、HP／SP、自動化選項與帳篷預覽，角色頁及工具箱均可開啟小地圖。

第二組五張參考圖已加入同一預覽：首頁及角色頁的功能列可開啟「聊天組隊／夥伴配點／遠征副本／煉金製作」，工具箱改為完整設定工具中心，共 11 個介面。聊天提供頻道、回覆、表情與本機訊息；組隊提供邀請／申請、跟隨守護樣式及隊伍上限。夥伴可切換出戰／休息，配點會檢查點數預算並可確認或重置。

遠征可選任務、儲存本次預覽選擇、開始／停止示範，副本可建立與加入範例房間。煉金提供材料槽、次數與進度示範；製作可搜尋／收藏配方、加入佇列、排序、移除、播放／暫停與循環。切頁、畫面停止或背景化時會停下示範計時器。

工具中心包含一般／規則／恢復／補給／守衛／維護／交換分頁，可調整門檻、規則順序與啟用狀態；保存僅作用於本次程序記憶體。匯入／匯出以畫面中的 JSON 編輯器處理，不讀寫正式設定檔，也不含帳號或密碼。匯入先完整驗證再套用，格式或規則無效時不會部分修改。NPC 對話、儲藏與福利入口均有可展開的範例內容。

可操作角色切換、道具搜尋／類型及稀有度篩選、道具選取與詳情、特技分頁、資源檢查進度示範、地圖點選目的地／座標輸入／縮放與路線示意。操作紀錄只保留本次程序內的預覽動作。小螢幕的帳號與角色操作會改成上下排列，避免重疊；畫面支援安全區域與旋轉，切頁或退到背景會停止示範計時器。工具頁保留原本的連線生命週期診斷及離線封包檢查。

獨立美術素材與產生提示詞見 [Preview/Assets/SOURCE.md](Preview/Assets/SOURCE.md)。頭像、城鎮及道具皆為設計示意素材，非官方資料；按鈕、文字、圖示與地圖標記均由介面程式碼繪製。

**只有「介面示範」模式使用離線資料。** 示範模式的帳密不會傳送或儲存，角色卡與版本數字不是同步結果；官方模式的登入按鈕則會將當次輸入交給官方連線核心。兩種模式明確標示且不能在正式登入中切換為示範。

在 Windows 倉庫根目錄：

1. 首次執行 `setup_android_preview.bat`，安裝使用者目錄內的 .NET Android 開發工具、Android API36、build-tools、模擬器及 x86_64 系統映像，建立 `LALA_Preview_API36` 裝置。需要網路、JDK21 與數 GB 空間；不修改全域 PATH 或 Windows 虛擬化設定。
2. 執行 `run_android_preview.bat`，開啟專用模擬器，建置 Debug 測試版、安裝並顯示 App。腳本只對 `emulator-5580` 的指定預覽裝置操作，不會選到已連接的實體手機。
3. 修改 `Preview` 資料夾內的介面來源，儲存後腳本會重新編譯、部署並重啟預覽。`MobilePreviewView.cs` 為共用外觀與導覽，帳號／角色、資源、背包與地圖各有獨立檔案。修改涉及重新啟動，並非所有變更都能即時 Hot Reload。`Ctrl+C` 停止監看，模擬器可手動關閉。

啟動視窗會保留錯誤訊息；每次執行的紀錄會存到 `%LOCALAPPDATA%\LaLa\AndroidPreview\Logs`。若模擬器啟動失敗，同目錄也有該次模擬器的輸出及錯誤紀錄。

`setup_android_preview.bat` 僅用於安裝工具，完成後會停留並提示改開 `run_android_preview.bat`；安裝檔不會啟動模擬器或 App。日常預覽直接執行 `run_android_preview.bat` 即可，不需要事先手動開模擬器。

啟動腳本會在專用預覽裝置開啟「有實體鍵盤時仍顯示螢幕鍵盤」，避免帳密欄取得焦點後卻看不到 Android 鍵盤；不更動 Windows 或其他裝置的輸入設定。

預設工具位置：`%USERPROFILE%\.lala-dev\dotnet`、`%LOCALAPPDATA%\Android\Sdk`；若設定了 `ANDROID_SDK_ROOT`／`ANDROID_HOME`，則採用該 SDK 路徑。進度示範與表單為畫面狀態，重建程序後會重設，避免保存預覽密碼。

只會產生模擬器所需的 **Debug 測試包**；不執行 Release publish、不建立正式簽署金鑰、不上架或發布 APK。

若硬體加速不可用，可先查看模擬器錯誤；腳本另支援 `powershell -File tools/android/Run-AndroidPreview.ps1 -SoftwareEmulation`，但軟體模擬速度取決於本機環境。不自動啟用 Windows 功能或要求重開機。

本機驗證：Android API36 x86_64 Debug 建置成功（0 警告、0 錯誤），生命週期測試 76 項通過。已實際安裝到 `LALA_Preview_API36` 並確認啟動畫面、中文字體、分頁、角色選取及進度示範；儲存來源檔後也已確認自動重建、重新安裝及啟動。系統列安全區域由 Android host 處理，避免重複留白。

新版視覺驗證：320／412 寬度的十一個介面已檢查，另核對橫向及長頁底部排版；最新 Android Debug 版本已安裝並啟動。模擬器實測角色入口與模式切換、道具選取詳情、無結果搜尋及清空恢復 24 項、地圖點選更新座標與縮放、路線示意、資源檢查示範完成及時間更新。時間以台灣時間顯示；沒有傳送遊戲指令。模擬器截圖留於忽略提交的 `bin/preview-screenshots/neon-*.png`。

新增功能頁另通過連結實際預覽控制項的 16 項行為檢查，包含配點預算／確認／重置、本機訊息輸入、隊伍人數上限、空任務拒絕啟動、遠征開始停止、範例房間、製作佇列加入／排序／刪除／進度與背景暫停，以及設定匯入的完整驗證與匯出。Android 模擬器已實測輸入本機訊息與五個新頁面的入口、顯示和導覽；新增截圖為 `bin/preview-screenshots/feature-*.png`。這些檢查不代表正式遊戲連線或操作已接入。

---

以下保留初建生命週期的設計記錄；目前預設 factory 已替換為 `OfficialAndroidClient`，登入核心及正式連線狀態以本文開頭為準。本專案是 PR79 的 C#／Avalonia Android host，沿用同一份 `Lala.Core`；本版仍未與既有 Python Android 客戶端功能等價。

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
| 網路恢復 | 已開始登入後中斷不會重播帳密；需重新輸入並手動登入。尚未取得 adapter 的初始網路等待仍受單次待處理輸入期限限制。 |
| 登入超過 3 分鐘仍未完成 | 取消並清理；進入接收階段後取消此 watchdog。 |
| 明確可重試的失敗 | Android 正式登入設定為 0 次重試；失敗後需重新輸入並操作，不重播帳密。 |
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

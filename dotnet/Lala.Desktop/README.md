# LaLa Desktop 桌面介面移植

啟動驗證已優化：有效的物品圖、頭像、表情及小地圖快取通過完整比對後直接沿用；小地圖建立後省去第二次解碼，進度顯示實際張數。必要十表及官方版本檢查保留，詳見 [資源效能說明](../../docs/DESKTOP_RESOURCE_INTEGRATION.md#2026-11-10-啟動驗證與快取效能)。

2026-11-10：目前遊戲功能進度請以 [最新檢查點](../../docs/DESKTOP_LOGIN_INTEGRATION.md#2026-11-10-接續檢查點野外自動補給) 為準。已接上野外 HP／SP 自動補給與儲存槽、背包補品選擇、自訂製作清單、每日助手、必要隊員套用、運作中 AI 設定更新、經驗效率與重設、NPC 一般選項與帳篷離開。各操作保留資料核對及伺服器回覆守衛，尚未逐項完成正式服驗收；下方較早的唯讀描述保留歷史背景。

PR #79 的 C#／Avalonia 桌面宿主加入登入、主畫面、背包、特技、戰場陣形、地圖、遠征及自動戰鬥設定介面。版面、原圖、色彩與操作入口以 Python 桌面版 v7.3.1 的實際程式為基準。

**依本次新要求，「包包」改名「背包」，背包與特技各自使用獨立視窗、搜尋與選取狀態。** 超空間袋仍在背包視窗內，分為儲藏室與雜物櫃。

目前可操作介面、顯示 Core 不可變快照、搜尋／分頁／檢視細節、編輯及保存本機設定草稿。**登入與選角已接入共用核心的單次受控流程；登入前完成資源準備及版本比對，登入後直接綁定該批已驗證資源，不重跑下載與驗證，完整圖資及一般遊戲操作尚未完成**；這個宿主還不能取代 Python 客戶端。沒有用假登入切換畫面，也不以離線 `world_ready`／`Ready` 旗標啟用送出權限。

Windows 可雙擊倉庫根目錄的 `run_desktop.bat` 啟動 C# Desktop。需 .NET 10 SDK；缺少時只顯示手動安裝提示，不自動安裝。首次啟動由 dotnet 還原 NuGet 套件並建置。原有 run_client.bat 仍啟動 Python 版本。

## 開啟與檢查

### 小地圖與自動接續

登入且目前地圖的圖片、座標投影及導航資料就緒後，左鍵雙擊小地圖位置即可自動尋路前往；再次雙擊可改換目的地，「停止導航」可停止目前移動。圖片周圍留白不接受目的地。遇戰與戰後事件會暫停移動；收到完整事件結束，並按已保存設定完成修理／整理／補給後，才恢復自動徘徊。修理與整理預設關閉，於 AI 設定中啟用。

連續斜坡已接入地面移動，仍會檢查整數步伐、三角形連接與其他樓層；重疊樓層或失效圖資不會強制通過。畫面的移動推算不當作伺服器已確認到達。最新 Debug 修正版可用根目錄 `run_desktop_packet_preview.bat` 建置啟動；關閉舊預覽後再啟動，避免同帳號同時登入。

### 修改版面時自動預覽

在倉庫根目錄雙擊 `run_desktop_preview.bat`，保留命令視窗，編輯並儲存
`dotnet/Lala.Desktop/Views/VersionWindow.cs` 即會自動編譯、重新啟動桌面視窗。
此頁使用 C# 建構函式建立控件，因此預覽關閉 Hot Reload，以重啟確保版面修改套用。
編譯失敗時可在命令視窗查看錯誤，修正後再次存檔；按 `Ctrl+C` 停止監看。
使用 Debug 輸出，與 `run_desktop.bat` 的 Release 輸出分開。
此模式執行正常桌面流程，啟動會查詢官方公開版本，隨後自動驗證、下載並寫入 LALA資料庫；按登入後自動連線，登入完成後直接沿用啟動時準備的資源，不再顯示下載或帳密傳送確認視窗。

```powershell
dotnet watch --project dotnet/Lala.Desktop/Lala.Desktop.csproj --no-hot-reload --configuration Debug
```

```bash
dotnet build dotnet/Lala.Desktop/Lala.Desktop.csproj -c Release
dotnet run --project dotnet/Lala.Desktop -c Release --no-build
```

啟動先顯示「資源準備與官方線上版本檢測」，左側以卡片顯示官方版本，觀測時間使用 UTC+8；右側「LALA資料庫」在取得新鮮且支援的官方清單後，自動開始 Core 資源驗證、下載與寫入，完成精確同版核對後才可進入登入。失敗或停止後不會循環重試，可按 **重新驗證、下載** 手動重啟完整檢查；停止不會回復已完成或結果不明的磁碟寫入。完整圖資仍未啟用。程式自動使用系統 LocalApplicationData 下的 LaLa/Resources，不提供選擇或更改資料夾，自洽不代表資源啟用。登入頁可按 **檢視桌面介面** 開啟未連線主畫面。登入的版本檢測與主畫面的官方版本／資源檢查可返回同一入口。角色卡有獨立的 **背包** 與 **特技** 入口；右側可切換 **事件紀錄／戰場陣形**，小地圖下方開啟導航預覽；遠征圖示與 AI 齒輪開啟原有獨立設定視窗。

登入頁已接通帳號清單、新增、儲存及刪除、記住帳號、Windows 加密記住密碼，以及帳號設定匯入／匯出。設定檔不含密碼，匯入不接受連線端點或協定參數；帳號與分流仍須核對當前官方清單。記住密碼使用 Windows 目前使用者 DPAPI，其他平台可記住帳號。取得登入輸入、切換身分或關閉視窗時清除密碼文字框。施放、補給、儲藏存取、實際移動、派遣與聊天送出等一般遊戲操作仍保持原有接線範圍。從自動載入的官方伺服器／分流選單選擇後按登入，自動接續驗證端及正式端連線，每次傳送帳密前仍會核對本次選定端點、最新官方分流與資源版本；協定參數沿用已知 Python 發行設定，未知或過期資料阻擋；角色不預選。官方 TCP 沒有 TLS、XOR 可逆；登入準備一分鐘內有效，角色選擇在登入期限內完成。詳見[接線與限制](../../docs/DESKTOP_LOGIN_INTEGRATION.md)。

```bash
# 不需要圖形環境：原封包自測＋桌面設定與資料邊界自測。
dotnet run --project dotnet/Lala.Desktop -c Release --no-build -- --self-test

# 需要實際原生顯示環境，或 Linux Xvfb。
dotnet run --project dotnet/Lala.Desktop -c Release --no-build -- --ui-self-test --screenshots /tmp/lala-desktop-ui
```

UI 自測使用獨立臨時設定目錄，合成資料名稱標示「介面測試」，結束後清除設定與快照，僅對 loopback 合成伺服器測試登入，不連線正式遊戲。截圖是實際 Avalonia 控件渲染；原生 Windows／macOS 安裝包、裝置縮放與正式伺服器驗收需另外執行。

## 架構與整合

- `DesktopApplication` 是 Desktop 專用入口，集中管理主視窗、登入與功能視窗的關閉／隱藏行為。
- `Shared/App.cs`、`Shared/ProtocolInspectorView.cs` 與 Android 的連線生命週期保留原路徑；登入頁仍可開啟原有離線封包檢查器。
- `DesktopSession.ReadView()` 一次取得 generation、publication sequence、快照與文字標籤；過期／重複 publication 被拒絕，切換身分後清除舊資料與選取。
- `ServiceStateSnapshot` 是顯示來源；UI 不建立第二套戰鬥、背包、遠征 reducer，不直接操作 socket、封包或 Core 可變狀態。
- 設定沿用 Python JSON 的欄位、列數及預設值；只檢查草稿結構，不代表技能／道具的正式可用性已核對。匯入、匯出與取消不會套用，儲存不會啟動 AI。
- `DesktopPreferencesStore` 在 `LocalApplicationData/LaLa/DesktopPreview` 依身分雜湊分檔。預覽身分與後續遊戲帳號分開；原 Python 設定不被覆寫，無帳密、Token、遊戲快照或授權旗標落盤。
- 官方原圖由 `wlre/resources/assets/` 直接嵌入 Desktop assembly，沒有另一套重複素材或 Android 資源變更。

全畫面／子視窗差距見 [Python 介面盤點](../../docs/DESKTOP_PYTHON_PARITY.md)，尚未完成全部介面一致。

詳細來源映射、驗收與限制見 [桌面介面移植與驗收](../../docs/DESKTOP_INTERFACE_MIGRATION.md)。

## 程式圖示與打包

自製標題列、原生 WindowIcon 及 Windows ApplicationIcon 都直接引用
`wlre/resources/assets/app.ico`。`dotnet publish -r win-x64 --self-contained false`
的實際 apphost 可用 `python tools/check_desktop_icon.py <Lala.Desktop.exe>`
核對原生 RT_GROUP_ICON 與全部 RT_ICON 圖框，CI Windows 同樣執行。

目前 C# Desktop 沒有獨立安裝器、.lnk 產生器、Linux .desktop 或 macOS .app bundle；
不把 runtime WindowIcon 當成這些打包層已完成。Windows 使用者建立且沒有自訂
IconLocation 的捷徑會取用目標 EXE 的圖示，但本輪未在 Windows Shell 實機建立／驗收。
既有 tools/build/build_nuitka.py 與 build_macos.py 是 Python 發行流程，已引用同一 app.ico，
本批未改動也未冒稱已重新建置 Python 安裝包。macOS Finder bundle／Dock、Linux launcher
整合及作業系統舊圖示快取仍需平台驗收。

## 帳號設定

帳號資料保存於 `LocalApplicationData/LaLa/Desktop/Login/accounts.json`。使用「儲存此組」建立或更新帳號，或勾選記住帳號後按登入，自動保存目前帳號與分流。記住密碼會一併記住帳號；取消記住密碼會移除已存的加密密碼，刪除此組會一併移除該帳號的密碼。

「載入設定／儲存設定」透過原生檔案選擇器匯入、匯出帳號與分流 JSON，匯出不含密碼。匯入會合併帳號，同帳號與伺服器群組不重複建立；格式錯誤時保留原設定。帳號清單可還原已記住的官方分流，不會自動連線，失效分流需重新選擇。Enter 可送出已填妥的登入資料或確認已選擇角色；連線期間不能修改已存帳號設定。

## 啟動資源準備與登入共用

Windows 使用 AppData\Local\LaLa\Resources；其他系統使用 .NET 的 LocalApplicationData 對應位置。路徑無效時停止準備，不退回程式目錄或共用暫存目錄。版本視窗取得有效官方清單後自動驗證、下載，由既有資源流程建立固定快取及資料庫目錄；可停止或按「重新驗證、下載」重啟。登入使用 `AccountRuntime.CreateUsingPreparedResources` 在記憶體內綁定目前啟動資源，不再下載、解碼、驗證或寫入一次。中斷只釋放帳號綁定，下一次登入可沿用同一批資源；啟動資源停止或被替換時，所有舊綁定立即失效，須回資源頁準備，不自動重跑。登入前的官方目標 metadata 檢查保留。一般遊戲操作仍 Held。
詳見 [接線範圍與驗證](../../docs/DESKTOP_RESOURCE_INTEGRATION.md)。

### PR #79 ver 8.0.50：條件式物品圖顯示

登入前／登入後資源準備可取得受支援的 MainPackage 物品圖，在來源、精確依賴、像素、
SQLite 獨立回讀及版本重查通過後，由 Core 的當前 activation 提供。背包與儲藏格逐次讀取，
刷新、停止、換帳與關閉會更新／清除圖片並釋放 Bitmap；未通過時保留名稱與不可用狀態。
確認視窗包含專用圖片庫路徑，圖片寫入結果獨立回報；停止不會撤銷已完成的磁碟寫入。
此接線仍未經實際官方圖片正向驗收，頭像、表情、小地圖與全介面一致尚未完成；
HasVisualAssets=false，一般遊戲操作仍 Held。測試僅自有合成圖片、資料與 loopback。

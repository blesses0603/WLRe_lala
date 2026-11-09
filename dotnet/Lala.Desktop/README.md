# LaLa Desktop 桌面介面移植

PR #79 的 C#／Avalonia 桌面宿主加入登入、主畫面、背包、特技、戰場陣形、地圖、遠征及自動戰鬥設定介面。版面、原圖、色彩與操作入口以 Python 桌面版 v7.3.1 的實際程式為基準。

**依本次新要求，「包包」改名「背包」，背包與特技各自使用獨立視窗、搜尋與選取狀態。** 超空間袋仍在背包視窗內，分為儲藏室與雜物櫃。

目前可操作介面、顯示 Core 不可變快照、搜尋／分頁／檢視細節、編輯及保存本機設定草稿。**登入與選角已接入共用核心的單次受控流程；官方資料啟用與一般遊戲操作尚未接入 Desktop**；這個宿主還不能取代 Python 客戶端。沒有用假登入切換畫面，也不以離線 `world_ready`／`Ready` 旗標啟用送出權限。

## 開啟與檢查

```bash
dotnet build dotnet/Lala.Desktop/Lala.Desktop.csproj -c Release
dotnet run --project dotnet/Lala.Desktop -c Release --no-build
```

啟動先顯示「登入／選角」。按 **檢視桌面介面** 開啟未連線的主畫面。角色卡有獨立的 **背包** 與 **特技** 入口；右側可切換 **事件紀錄／戰場陣形**，小地圖下方開啟導航預覽；遠征圖示與 AI 齒輪開啟原有獨立設定視窗。

密碼記憶、施放、補給、儲藏存取、實際移動、派遣與聊天送出等尚無宿主接點的操作維持停用並顯示原因。登入欄位不持久化；取得輸入、切換身分或關閉視窗時清除密碼。手動填寫核對過的驗證／正式 IP:port、十進位 XOR、平台及語言後按登入；兩次帳密傳送分別確認，角色不預選。官方 TCP 沒有 TLS、XOR 可逆；登入準備一分鐘內有效，角色選擇在登入期限內完成。詳見[接線與限制](../../docs/DESKTOP_LOGIN_INTEGRATION.md)。

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

詳細來源映射、驗收與限制見 [桌面介面移植與驗收](../../docs/DESKTOP_INTERFACE_MIGRATION.md)。

# Nuitka 打包

在 Windows 安裝 64 位元 Python 3.12，安裝時保留 Tcl/Tk。完整解壓後，雙擊 `build_nuitka.bat`。

第一次會依 Python 版本建立獨立 `.nuitka-env/py3.xx`、安裝打包套件，並在 Nuitka 需要時下載編譯工具；需要網路，不需要 PyArmor 授權。

預設為資料夾版，完成後執行：

`dist_nuitka\standalone\WLRe_LaLa.dist\WLRe_LaLa.exe`

分享時帶走整個 `WLRe_LaLa.dist` 資料夾，不能只複製 EXE。使用者電腦不需另外安裝 Python。

若要單一 EXE，在此資料夾的命令提示字元執行：

```
build_nuitka.bat --mode onefile
```

輸出：`dist_nuitka\onefile\WLRe_LaLa.exe`。單檔會在啟動時解壓資源，地圖及圖片較多，啟動可能較資料夾版慢。

如需指定編譯器：

```
build_nuitka.bat --compiler msvc
build_nuitka.bat --compiler mingw64
```

MSVC 需要 Visual Studio 2022 或更新的 C++ 建置工具。MinGW 使用 Nuitka 提供的版本；本打包流程支援 64 位元 Python 3.10～3.14，預設優先選 3.12。3.13／3.14 自動選用 MSVC；未安裝時會明確顯示安裝指引，不會繼續嘗試不相容的 MinGW64。

打包入口 `WLRE_Client.py` 直接啟動 GUI，不會執行原始碼用的 `wlre/launcher.py`，避免打包後再呼叫 EXE 當作 Python 而重複啟動。ICO 同時套用 EXE 與視窗；地圖、物品圖片、表情及 JSON 逐一加入，未將原始碼當作資料檔複製。

打包成功後會自動以 `--self-test` 檢查 GUI 模組、JSON、ZIP 與 ICO。這項自檢不連線或登入，也不能代替 Windows 互動介面與正式伺服器驗證。

失敗時查看輸出目錄中的 `build.log`、`compilation-report.xml`；EXE 啟動錯誤記錄於 `%LOCALAPPDATA%\WLRE_Client\error.log`。

第 09 項已在 GitHub Actions 真正編譯並自檢 Windows x64 EXE，以及 macOS arm64／Intel x64 APP；這是自動化建置驗證，不等於已完成使用者電腦上的實機互動與正式伺服器驗證。

參考：[Nuitka 官方手冊](https://nuitka.net/user-documentation/user-manual.html)、[常見問題](https://nuitka.net/user-documentation/common-issue-solutions.html)。

## Python 偵測失敗

舊 v0.4.11 的 BAT 僅接受 3.10～3.12，若只有 3.13／3.14 會被擋在編譯前。v0.4.12 已放寬到 3.14，且實際檢查 Tkinter。

BAT 會列出選中的版本、位元數、路徑及 Tk 版本；找不到可用環境時列出 `py -0p` 與 PATH Python 的診斷，不再把缺少 Python 與編譯失敗混在一起。此階段失敗不會有 Nuitka 編譯報告。

僅有 Python 3.13／3.14 且沒有 C++ 工具時，可安裝 Visual Studio 2022 Build Tools 的「使用 C++ 的桌面開發」，或另裝 64 位元 Python 3.12（含 Tcl/Tk）後重開 BAT。無須移除既有 Python。

本次比對來源為你提供的 `WLRE_Nuitka_Core(1).zip`：採用其中的 Python 3.10～3.14 偵測、MSVC／MinGW64 選擇、依 Python 版本區分建置環境、Nuitka>=4.3 與獨立編譯子程序環境；打包內容則使用本專案的客戶端與資源。


## 第 09 項：建置驗證分層

1. **三平台原始碼回歸**：`.github/workflows/test.yml` 在每次 PR／main 提交皆自動執行 Linux、Windows、macOS 完整單元測試、原始碼 GUI 冒煙測試與 dry-run；這些原始碼測試不代表已產生可執行 EXE／APP。
2. **原生打包驗證**：`.github/workflows/desktop-packaging.yml` 不在任何 PR／main 提交時自動執行，只有使用者需要預先取得 EXE／APP 時，才從 Actions `Run workflow` 手動觸發；在 Windows x64、macOS arm64、macOS Intel x64 真正編譯 Nuitka，啟動編譯後產物作資源自檢及可執行的 GUI 冒煙測試，並驗證 ZIP CRC。macOS 另確認 Mach-O 架構與 `codesign --verify --deep --strict`，Intel GitHub Runner 的 GUI 限制如後述。
3. **人工驗收**：需在使用者的 Windows 桌面及 Mac Finder 驗證實際操作；Apple Developer ID 公證、Gatekeeper 與正式伺服器連線不屬自動 CI 能證明的事項。

macOS Intel 的 GitHub hosted runner 曾在原始碼 Tk GUI 冒煙測試逾時；CI 明確使用 `WLRE_NATIVE_GUI_SMOKE=0` 停用 **Intel 虛擬機的 GUI 視窗檢查**，但仍要求完整單元測試、原生編譯、編譯後 APP 的資源自檢、Mach-O 架構檢查、簽章與 ZIP 完整性。Intel 使用者電腦上的實際 APP GUI 啟動**尚未驗證**，需人工驗收。macOS Apple Silicon 的 CI GUI 冒煙測試維持啟用。

手動原生驗證的完整打包產物會暫存於 GitHub Actions artifacts；正式版仍需推送與 `wlre.__version__` 相符、尚未發行的 `vX.Y.Z` 標籤才能觸發 GitHub Release，正式 Release 將自動執行三平台原生打包。macOS Intel 與 Apple Silicon 是分開建置的原生 APP，並非 Universal Binary。

## 打包速度與編譯快取（第 09 項）

- Windows 和 macOS 預設使用最多 **6** 個平行 C 編譯工作，仍不超過偵測到的 CPU 數。可按記憶體容量調整：Windows 用 `build_nuitka.bat --jobs 8`；macOS 用 `python -m tools.build.build_macos --arch arm64 --jobs 8`（允許 1～16）。
- 執行 `--dry-run --jobs 8` 可以核對設定，不會啟動 Nuitka 編譯。工作數太高可能用盡 RAM 或比預設更慢，優先視 CPU、RAM 與測試結果調整。
- macOS 已移除原本無條件使用的 `--disable-cache=ccache`。Nuitka 會在編譯器快取工具可用時使用它，並不保證所有 runner 都裝有 ccache。
- GitHub Actions 手動原生驗證與正式 Release 會透過 `NUITKA_CACHE_DIR` 配合 `actions/cache` 儲存與恢復 Nuitka 編譯快取；按照 Windows、macOS arm64／x64、Python 版本與 requirements 分開快取。pip 下載快取也開啟。
- **第一次全新編譯通常不會因快取而變快**，重複建置且 C 原始碼和編譯器選項足夠相似時才可能命中。快取結果會在 GitHub Actions 日誌中顯示，可用各次 Nuitka 編譯時間比較；沒有測量前不宣稱百分比改善。
- 此次加速不移除任何圖片、JSON、ZIP、Tk 插件或 `--include-package=wlre`，仍要求完整編譯後自檢與跨平台回歸測試通過。若遇到記憶體不足，可指定 `--jobs 2`。

## GitHub Actions 開發測試／正式打包分流（2026-10-19）

- 使用者確認不再限制 GitHub Actions 額度，因此 `Main and PR tests` 改回一般 PR/main 提交同時驗證 Linux、Windows、macOS。
- `Native desktop packaging verification` 僅接受 `workflow_dispatch` 手動執行 Windows x64、macOS arm64／Intel x64；任何 PR 更新都不自動原生打包。
- 發版標籤 `vX.Y.Z` 照常由 `Windows and macOS Nuitka Release` 自動進行正式發行。一般 PR 驗證不是 Release，不會自行建立標籤或發布新版本。
- 一般 Commit 檢查三平台原始碼測試；正式 Release 或手動打包時才核對 Nuitka 編譯、資源自檢、封裝完整性與工作流程產物。沒有實際執行成功的項目不得記為通過。
- Mac Intel 實機 Finder GUI、Apple Developer ID 公證、Windows 使用者電腦互動及正式遊戲伺服器端到端仍屬人工驗收，CI 不能取代。


### 固定執行規則

- **Windows 開發預覽**：以 `run_client.bat` 執行 Python 原始碼，無須 Nuitka。macOS 開發預覽以 `run_client.command` 執行。
- **PR／main 每次更新**：由 `.github/workflows/test.yml` 自動執行 Windows／Linux／macOS 測試與打包規劃的 `--dry-run`；`--dry-run` 不會產生 EXE／APP。
- **需要提前取得原生安裝包**：開啟 GitHub Actions 的 `Native desktop packaging verification`，手動選擇分支再按 `Run workflow`。
- **正式 Release**：以 `vX.Y.Z` 標籤觸發 `.github/workflows/release-windows.yml`，執行正式 Windows EXE 與 macOS APP 原生打包並建立發行版本。
- 歷史上已啟動的舊打包工作不會因修改 YAML 自動取消；舊紀錄須另行刪除。本次改動不合併尚未驗收的副本／協力功能。

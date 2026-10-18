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

目前交付包含原始碼與打包流程；尚未在 Windows 實際編譯產生 EXE。

參考：[Nuitka 官方手冊](https://nuitka.net/user-documentation/user-manual.html)、[常見問題](https://nuitka.net/user-documentation/common-issue-solutions.html)。

## Python 偵測失敗

舊 v0.4.11 的 BAT 僅接受 3.10～3.12，若只有 3.13／3.14 會被擋在編譯前。v0.4.12 已放寬到 3.14，且實際檢查 Tkinter。

BAT 會列出選中的版本、位元數、路徑及 Tk 版本；找不到可用環境時列出 `py -0p` 與 PATH Python 的診斷，不再把缺少 Python 與編譯失敗混在一起。此階段失敗不會有 Nuitka 編譯報告。

僅有 Python 3.13／3.14 且沒有 C++ 工具時，可安裝 Visual Studio 2022 Build Tools 的「使用 C++ 的桌面開發」，或另裝 64 位元 Python 3.12（含 Tcl/Tk）後重開 BAT。無須移除既有 Python。

本次比對來源為你提供的 `WLRE_Nuitka_Core(1).zip`：採用其中的 Python 3.10～3.14 偵測、MSVC／MinGW64 選擇、依 Python 版本區分建置環境、Nuitka>=4.3 與獨立編譯子程序環境；打包內容則使用本專案的客戶端與資源。


## 第 09 項：建置驗證分層

1. **原始碼測試**：`.github/workflows/test.yml` 的 Windows、Linux、macOS 單元測試、原始碼 GUI 冒煙測試與 dry-run，不代表已產生可執行 EXE／APP。
2. **原生打包驗證**：`.github/workflows/desktop-packaging.yml` 對 PR 分別在 Windows x64、macOS arm64、macOS Intel x64 編譯 Nuitka，實際啟動**編譯後產物**執行 `--self-test` 和 `--smoke-test-gui`，並驗證 ZIP CRC。macOS 還需檢查 Mach-O 架構與 `codesign --verify --deep --strict`。
3. **人工驗收**：需在使用者的 Windows 桌面及 Mac Finder 驗證實際操作；Apple Developer ID 公證、Gatekeeper 與正式伺服器連線不屬自動 CI 能證明的事項。

macOS Intel 的 GitHub hosted runner 曾在原始碼 Tk GUI 冒煙測試逾時；CI 明確使用 `WLRE_NATIVE_GUI_SMOKE=0` 停用 **Intel 虛擬機的 GUI 視窗檢查**，但仍要求完整單元測試、原生編譯、編譯後 APP 的資源自檢、Mach-O 架構檢查、簽章與 ZIP 完整性。Intel 使用者電腦上的實際 APP GUI 啟動**尚未驗證**，需人工驗收。macOS Apple Silicon 的 CI GUI 冒煙測試維持啟用。

PR 完整打包產物會暫存於 GitHub Actions artifacts；正式版仍需推送與 `wlre.__version__` 相符、尚未發行的 `vX.Y.Z` 標籤才能觸發 GitHub Release。macOS Intel 與 Apple Silicon 是分開建置的原生 APP，並非 Universal Binary。

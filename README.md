# 飄流Re:LaLa · By 赤寧

飄流 Re 的 Python 桌面客戶端與離線導航工具，目前版本為 **v0.4.19**。介面使用 Tkinter，提供登入選角、戰鬥與組隊、地圖導航、補給、煉金、家具製作、聊天及經驗效率資訊。

主要使用與 EXE 打包流程以 Windows 為目標；Linux 可用於原始碼開發、離線工具及測試。正式伺服器行為仍需實機驗證。

## 快速開始

### Windows 使用者

1. 安裝 **64 位元 Python 3.12**，保留 Tcl/Tk 與 pip，並確認命令列可執行 `python` 或 `py`。
2. 取得完整專案並解壓縮至新資料夾，保留 `wlre/resources/` 內的所有資源。
3. 關閉舊版程式，執行 `run_client.bat`。
4. 在登入視窗選擇伺服器、分流，輸入帳密後登入並選角。

啟動器會檢查 Pillow 圖片支援；若缺少依賴，會在專案內建立 `.ui-env` 並安裝。首次啟動可能需要網路及資料夾寫入權限。

伺服器選項包含地球 1～5 線與水星 1～2 線。程式不會自動登入或啟動 AI；使用前請先確認帳號、分流與功能設定。

### 原始碼開發

在專案根目錄開啟命令列，建議使用獨立虛擬環境：

```sh
python -m venv .venv
```

依作業系統啟用環境：

| 終端機 | 指令 |
| --- | --- |
| Windows 命令提示字元（cmd） | `.venv\Scripts\activate.bat` |
| Windows PowerShell | `.venv\Scripts\Activate.ps1` |
| Linux／macOS shell | `source .venv/bin/activate` |

接著安裝依賴並啟動：

```sh
python -m pip install -r requirements-ui.txt
python -m wlre.launcher
```

桌面介面需要可用的 Tkinter 與顯示環境。Linux 無顯示器時，可使用 Xvfb 驗證介面啟動；離線命令列工具不需要顯示器。macOS 的互動介面尚未驗證。

## 功能與操作

主頁提供角色與夥伴、目前活動、AI／徘徊、補給紀錄、煉金、家具製作、隊伍與經驗效率摘要，可直接切換至對應功能；完整經驗統計位於「經驗效率」分頁。離線時保留最後收到的資料並明確標示，尚未同步的數值不會顯示為零。

| 功能 | 說明 |
| --- | --- |
| 登入與帳號記憶 | 記憶多組帳號及分流；密碼記憶依賴 Windows DPAPI 加密，不會明文儲存。 |
| 戰鬥與組隊 | 戰鬥資訊、AI 設定、隊伍管理及必要隊員檢查。 |
| 地圖與移動 | 地圖顯示、四點徘徊、離線路徑預覽與傳點相關功能。 |
| 補給與製作 | 回復、補給、煉金、家具製作及配方查詢。 |
| 聊天與效率 | 手動發話、表情顯示、事件紀錄及經驗效率資訊。 |

使用必要隊員檢查時，先在 AI 下方設定最多四格必要隊員，啟用「缺員逃跑」並儲存套用，再啟動 AI。

Windows 的登入記憶檔位於 `%LOCALAPPDATA%\WLRE_LaLa\login_memory.json`；未設定 `LOCALAPPDATA` 時，使用 `~/.config/WLRE_LaLa/login_memory.json`。既有使用者設定沿用原本的儲存位置。

## 離線導航

只開啟導航視窗：

```sh
python -m wlre.launcher --navigation
```

Windows 也可執行 `run_navigation.bat`。此工具用於離線幾何與路徑預覽，不會送出角色移動指令。

不啟動視窗即可列出內附導航資源及查看命令列選項：

```sh
python -m wlre nav-list
python -m wlre --help
python -m wlre nav-route --help
```

## 自檢與測試

在已安裝介面依賴的環境中，於專案根目錄執行：

```sh
python WLRE_Client.py --self-test
python -m unittest discover -s tests -v
```

自檢會確認 GUI 模組、必要資源、JSON、ZIP 完整性與圖示能否讀取，不會登入伺服器，也不會開啟視窗。

目前 Linux 開發環境的驗證結果為 **83 項測試中 82 項通過、1 項 Windows DPAPI 測試略過**，資源自檢通過；另已使用虛擬顯示器確認登入視窗、離線導航視窗與場景載入。這些檢查不代表 Windows EXE 或正式服操作已驗證。既有版本驗證紀錄見 [VALIDATION.md](docs/VALIDATION.md)。

## Windows EXE 打包

在 Windows 安裝 64 位元 Python，建議使用含 Tcl/Tk 的 Python 3.12，然後執行：

```bat
build_nuitka.bat
```

預設產生資料夾版：

```text
dist_nuitka/standalone/WLRE_Client.dist/WLRE_Client.exe
```

分享時需帶上整個 `WLRE_Client.dist` 資料夾。若要單一 EXE：

```bat
build_nuitka.bat --mode onefile
```

輸出為 `dist_nuitka/onefile/WLRE_Client.exe`。首次建置會建立獨立環境、安裝 Nuitka 依賴，並可能下載編譯工具。Python 3.13／3.14 需使用 MSVC；詳細需求、編譯器選擇及錯誤排查見 [Nuitka 打包說明](docs/NUITKA_BUILD.md)。

## 專案結構

```text
WLRE_Client.py        直接啟動與資源自檢入口，也是 Nuitka 打包入口
run_client.bat       Windows 主程式啟動
run_navigation.bat   Windows 離線導航啟動
wlre/
  launcher.py        原始碼介面啟動與圖片依賴檢查
  __main__.py        命令列工具
  ui/                Tkinter 介面
  services/          戰鬥、世界、物品與社交功能
  core/              狀態、活動與事件紀錄
  network/           連線與協定處理
  storage/           預設設定、登入記憶與分流資料
  resources/         JSON、地圖、圖示與表情資源
tools/              建置與資源維護工具
tests/              unittest 測試
docs/               架構、協定與驗證文件
```

詳細目錄與資源維護約定見 [STRUCTURE.md](docs/STRUCTURE.md)；協定筆記見 [PROTOCOLS.md](docs/PROTOCOLS.md)。表情資源維護入口為 `collect_emoji_resources.bat`。

更新內容見 [更新紀錄](CHANGELOG.md)。

## 已知限制

- Windows EXE 編譯、原生密碼加密及正式伺服器行為仍需在對應環境實測。
- 移動目的地通知不等於抵達確認；導航及傳點是否可用，以伺服器回覆為準。
- 家具配方依已確認條件顯示，尚未同步圖鑑旗標；需要圖紙的項目可能不顯示。
- 物品圖庫缺圖時使用預設圖；表情目前顯示靜態第一幀。
- 聊天需手動送出，並保留既有發話限制。

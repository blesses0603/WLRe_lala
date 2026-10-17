# 飄流 RE:LaLa Android v0.0.1（實驗測試版）

此分支的 Android 版本從 **v0.0.1** 獨立編號，與 Windows／macOS 的版本分離。

## 目前包含

- Kivy 直式手機登入介面與預設分流選單。
- 使用既有 Python 網路客戶端，各帳號建立獨立連線執行緒和指令佇列。
- 角色 1／2 的選角按鈕保留鎖定狀態，選角待回覆時不可重複送出。
- 顯示角色 HP／SP、等級、地圖及伺服器確認的位置；未同步資料不補造數值。
- 每條連線可獨立停止，結束後保留錯誤原因並可移除卡片釋放記憶體。
- 內附 Noto Sans TC 中文字型，避免手機使用預設 Roboto 時中文缺字。
- 密碼僅在本次連線時使用，不寫入本機設定、程式庫或事件紀錄。
- GitHub Actions 測試用 APK 工作流程。

## 尚未完成或確認

- **正式伺服器登入尚未實機驗證**。封包解析基於既有研究，不能保證 Android 可登入。
- **鎖定螢幕／切換 App 後持續作業尚未支援**。本版切換背景會要求停止全部連線，並清空密碼欄；回到 App 不會自動重連。需要 Android Foreground Service、常駐通知與實機省電測試。
- 目前沒有 Android Keystore 的「記住密碼」功能；**請勿將私人帳密、密鑰加入 Git 儲存庫**。
- 目前沒有保證任意數量帳號都能保持連線，實際受裝置 RAM、散熱、網路與 Android 政策限制。
- 自動戰鬥、徘徊等為現有 Python 核心的研究功能，尚未完成 Android UI 與持續運作的整合驗證。

## 從 GitHub 取得 Android APK

1. 開啟本儲存庫的 [Actions](https://github.com/blesses0603/WLRe_lala/actions)。
2. 選擇 **Android v0.0.1 Test APK** 工作流程，確認執行分支為 `android-development`。
3. 若沒有自動開始，等待分支推送觸發；或使用 **Run workflow** 手動執行（若介面提供）。
4. 等待工作流程變綠後，進入該次執行頁，從 **Artifacts** 下載 `WLRe_LaLa-Android-v0.0.1-debug`。
5. 解壓 ZIP，將其中的 APK 複製到 Android 手機，再依手機提示允許安裝該來源的應用程式。

**注意：** 目前不能聲稱 APK 已經編譯成功。必須等 Actions 工作流程真正成功並顯示 Artifact，才有可安裝的成品。

## 手機驗收順序

1. 首先只開 App，確認直式介面、地球／水星分流下拉選單可以操作，不要急著輸入主要遊戲帳密。
2. 再由使用者自主決定是否使用專門的測試帳號測試正式登入，觀察是否取得選角清單。
3. 驗證單一帳號停止不影響其他連線；接著才測試兩個帳號並行。
4. 目前不把鎖屏後仍在線視為通過；背景服務是下一階段。

## 開發與隔離

原有 Windows／macOS 程式碼保留；新入口為 `main.py`，Android 專用程式位於 `android_app/`。打包設定是根目錄的 `buildozer.spec`。所有修改只提交至 `android-development`。


## 開發驗證

橋接測試不連線正式伺服器：

```bash
python -m unittest discover -s tests -p test_android_sessions.py -q
```

Kivy 控制項與中文字型測試需要 Kivy 2.3.1、Pillow 及桌面顯示，Linux CI 使用 `xvfb-run`：

```bash
KIVY_NO_ARGS=1 xvfb-run -a python -m unittest discover -s tests -p test_android_ui.py -q
```

Actions 先執行這兩組測試，再進行 Buildozer 編譯。下載 ZIP 同時附 APK 的 SHA256 校驗檔；建置成功不代表已完成手機或正式服登入驗證。

中文字型來自 Google Fonts 的 Noto Sans TC（OFL 1.1），依變動字重來源產生 400 Regular，授權文字位於 `android_app/assets/fonts/OFL.txt`。

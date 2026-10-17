# 飄流Re:LaLa  =By赤寧= v0.4.19

關閉舊版，解壓至新資料夾後執行 `run_client.bat`，輸入帳密並選角。

## 使用與建置

- 登入選擇伺服器「地球／水星」，再選分流（地球 1～5 線、水星 1～2 線）。
- 支援多組帳號及分流記憶；記住密碼需使用 Windows DPAPI，不會明文儲存。
- 主頁提供戰鬥、組隊、四點徘徊、地圖導航、補給、煉金、家具製作、聊天與經驗效率。
- AI 下方可設定四格必要隊員；啟用缺員逃跑並儲存套用後，再啟動 AI。
- 設定可沿用原使用者儲存位置；不會自動啟動 AI 或登入。
- EXE 打包：`build_nuitka.bat`；單檔模式加上 `--mode onefile`。詳見 `docs/NUITKA_BUILD.md`。
- 導航工具：`run_navigation.bat`；表情資源維護：`collect_emoji_resources.bat`。
- 自檢：`python WLRE_Client.py --self-test`。
- 測試：`python -m unittest discover -s tests -v`。

## 本版分區調整

- 將 `tools/start_ui.py` 移至 `wlre/launcher.py`。
- `run_client.bat` 與 `run_navigation.bat` 改用 `python -m wlre.launcher`。
- `tools` 僅保留 EXE 建置與表情資源收集工具。
- 自動準備圖片依賴與原有啟動方式維持不變。
- 六大功能分區及既有功能保留，目錄說明見 `docs/STRUCTURE.md`。

## 現有限制

Windows EXE 編譯、原生密碼加密與正式伺服器行為需實機驗證。
移動目的地通知不等於抵達確認；導航與傳點可用性仍以伺服器回覆為準。
家具配方依已確認條件顯示，尚未同步圖鑑旗標；需圖紙項目可能不顯示。
物品圖庫缺圖使用原版預設圖，表情目前顯示靜態第一幀。
聊天需手動送出；保留既有發話限制。

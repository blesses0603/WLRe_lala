# 公開遊戲資源移除與防回流清單

**狀態：待處理。** 新增檔案檢查器不會撤回既有公開檔案、既有 Release，亦不會清除 Git 歷史。

## 立即處置（須由儲存庫擁有者執行）

1. 優先暫時將儲存庫設為 Private，避免繼續公開提供檔案；檢查 Actions、Release、Artifacts、fork 與外部快取。請先考量協作者與既有使用者的存取影響。
2. 盤點散布授權與實際來源。若無公開轉載授權，先停止發佈含官方素材的安裝包。
3. 保留可用的本機遊戲資源備份，但不要把官方 Bundle、完整衍生表格或圖像重新上傳其他公開位置。

## 已確認的待遷移路徑（非完整清單）

- `wlre/resources/item_icons.zip`
- `wlre/resources/smallmaps.zip`
- `wlre/resources/navigation_data.zip`
- `wlre/resources/emoji_images.zip`
- `wlre/resources/npc_*.json.gz`
- `wlre/resources/*_catalog.json`、`portals.json`、`stage_coordinates.json` 等遊戲衍生資料
- `wlre/resources/assets/` 內來源未釐清的官方圖像
- `docs/button-assets/` 的貼圖、預覽及封裝檔
- v0.5.0 Release 的 Windows／macOS 安裝包（目前打包流程會加入資源目錄，須複核其實際內容）

## 安全遷移順序

1. **實作本機資源安裝器**：從使用者自己的合法遊戲安裝目錄讀取，或在本機驗證使用者提供的資源。限制允許檔名及大小，檢查 SHA-256／版本，拒絕 ZIP Slip，不更動官方安裝檔。
2. **修改各模組讀取路徑**：物品圖示、小地圖、導航、NPC、背景／按鈕等統一讀取本機資料；缺檔需停用相關功能並給明確訊息，不能誤判新版相容。
3. **修改建置與測試**：公開建置不得將官方素材重新打包上傳；測試改用合成 fixture。
4. **獨立移除 PR**：完成讀取路徑遷移與回歸測試後，精確列出並移除受影響追蹤檔案；同時清查 Release/Artifact。
5. **經核准後處理歷史**：Git 歷史重寫及 force-push 可能破壞協作、既有 PR 與外部 clone。需使用者明確核准、協調協作者；即使清理成功，也不能保證撤回已經下載或 fork 的副本。

## 新提交防護

`.gitignore` 只防一般意外新增，對已追蹤檔案、`git add -f` 及舊歷史無效。CI 的 `tools.check_public_resources` 額外檢查 PR/推送新增與修改的禁止路徑。這是**過渡性變更檢查**，不是全倉安全合格證明；移除完成後應改成全樹檢查。

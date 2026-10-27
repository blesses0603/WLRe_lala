# P2 場景名稱與模型引用批次

【開發階段】P2，沿用 PR #59 資源子分支，基準 `a88fc51`；0.6.1 保持不變。

【完成項目】同次官方場景／文字／MainPackage 索引交叉核對，來源 adapter 分離固定／可變長度格式，保留舊文字 dict／ProtocolError 與場景名稱 API。名稱與模型缺口獨立回報；模型索引有效不等於內容或網格有效。

【修改檔案】新增 `parsers/texts.py`、`official/adapters.py`、`official/references.py`、`tests/test_official_scene_references.py`、本報告與 JSON 來源收據；修改官方 contracts／compatibility／manager、遠征文字／舊場景名稱入口、驗證工具、資源模組 workflow 及根目錄六份架構／移植／測試文件。

【影響範圍】官方資源共享層與兩個舊只讀 API。沒有更動遊戲封包、GUI 操作、導航、主分支或原始資產。

【測試結果】新增 13 項合成樣本單元／整管線測試，含 UTF-16／non-BMP、EOF／重複／來源範圍、精確配對、場景／模型／名稱 ID 分離、空名稱引用、缺少／歧義／加密／身分不符、雙來源原子快照、舊 view 撤銷及錯誤文字不發佈。原 Manager 28 項、舊名稱 6 項通過；完整本地 1,316 項，91.833 秒，OK，跳過 2 項。Ruff、名稱檢查、compileall、repository audit、diff check 通過。完整紀錄 `/tmp/lala-scene-references-full.log` 為本機產物，不作永久 CI 憑證。

真實官方資料於 2026-10-27T00:12:30Z 核對：1,337 場景、39,947 文字；有效名稱 1,322／缺少 15；模型 Manifest 身分有效 1,127／缺少 210，涉及 202 個缺少模型 ID。只讀必要兩個 Bundle，版本／hash 前後一致；見 [來源收據](official_scene_references_probe.json)。不是遊戲伺服器 E2E。

【CI 狀態】提交前尚未執行本批遠端 CI，提交後以 PR #59 Checks 及 TESTING.md 的對應提交紀錄為準。上一提交九個成功工作不當作本批通過。

【尚未完成】模型內容／官方掃描網格、缺少名稱及模型的來源原因、資源 Module 生命週期、GUI／舊 Runtime 遷移、其他 Parser、P3～P7、正式服 E2E 與 EXE 打包。

【風險】只接受已觀測的兩族官方模型路徑，其他結構會回報缺口；不能猜替代。來源的 MD5／CRC 是完整性核對，不是數位簽章。文字表含遊戲內容，只留私人快取，不提交原始資料。舊資源不具完整等價替代／全部遷移證據，因此未刪除。

【下一批工作】本批三平台 CI 通過後，將 Manager 接入 P1 生命週期及受管合作式背景工作，驗證關閉撤銷查詢、停止下載及等待工作退出。再逐功能遷移消費者。

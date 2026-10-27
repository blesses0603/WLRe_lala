# reference-python（預留）

階段 0-2 要放在這裡的東西：從舊版抽出、**不依賴 Tk／Pillow／Windows** 的最小參考核心，以及一個無介面 CLI
（登入、選角、持續收包並輸出脫敏的 JSONL）。

目前**尚未開始**，此資料夾沒有程式碼。進行前需先完成 `spec/behavior/` 中「待補的 scenario」，
並確認 `State.apply()` 與 services 的循環依賴要如何拆開。

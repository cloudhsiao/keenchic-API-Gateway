## ADDED Requirements

### Requirement: 相同 inspection name 不重新載入模型
系統 SHALL 維護一個 singleton InspectionManager，記錄當前載入的 inspection name。若新請求的 `X-Inspection-Name` 與當前已載入的相同，SHALL 直接使用現有 adapter 執行辨識，不得重新載入模型。

#### Scenario: 連續相同 inspection 請求（快取命中）
- **WHEN** 連續收到兩個相同 `X-Inspection-Name` 的請求
- **THEN** 第二個請求直接使用已載入的 adapter，不觸發 `load_models()`

#### Scenario: 首次載入（冷啟動）
- **WHEN** 系統啟動後收到第一個 inspect 請求
- **THEN** InspectionManager 呼叫對應 adapter 的 `load_models()`，完成後執行辨識

### Requirement: 切換 inspection name 時卸載舊模型再載入新模型
當新請求的 `X-Inspection-Name` 與當前已載入的不同時，系統 SHALL 先呼叫舊 adapter 的 `unload_models()`，再呼叫新 adapter 的 `load_models()`，最後執行辨識。

#### Scenario: 切換到不同 inspection
- **WHEN** 當前載入的是 `ocr/datecode-num`，收到 `X-Inspection-Name: ocr/holo-num` 的請求
- **THEN** 系統先呼叫 datecode adapter 的 `unload_models()`，再呼叫 holo adapter 的 `load_models()`，最後執行辨識

#### Scenario: 切換時 load_models 失敗
- **WHEN** 切換過程中新 adapter 的 `load_models()` 拋出例外
- **THEN** 系統回傳 HTTP 503，並將 InspectionManager 的當前 adapter 設為 `None`（不保留損壞狀態）

### Requirement: asyncio.Lock 保護並發切換
InspectionManager 的模型載入/卸載操作 SHALL 以 `asyncio.Lock` 保護，確保同一時間只有一個模型切換操作進行。其他等待中的請求 SHALL 在 lock 釋放後序列執行。

#### Scenario: 並發請求觸發模型切換
- **WHEN** 同時收到兩個不同 `X-Inspection-Name` 的請求
- **THEN** 第一個請求取得 lock 並執行模型切換；第二個請求等待 lock 釋放後再執行（可能觸發再次切換）

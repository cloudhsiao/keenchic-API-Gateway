## ADDED Requirements

### Requirement: 從 FDA 開放資料下載許可證資料並快取
系統 SHALL 在模組首次匯入時，從 `data.fda.gov.tw` 下載藥品許可證資料（ZIP 內含 JSON），解析後存入 in-memory list cache（`_permit_cache`）。後續查詢 SHALL 直接讀取 cache，不重複下載。

#### Scenario: 首次匯入成功下載
- **WHEN** `permit_lookup` 模組首次被匯入
- **THEN** `_permit_cache` 被填入許可證資料，長度大於 0

#### Scenario: 下載失敗（網路錯誤）
- **WHEN** FDA API 無法連線或回傳錯誤
- **THEN** `_permit_cache` 為空 list，不拋出例外，並記錄錯誤訊息至 stdout

### Requirement: 依 pcode 查詢產品資訊
`get_product_by_pcode(pcode: str)` SHALL 在 `_permit_cache` 中搜尋許可證字號包含 `pcode` 的記錄，回傳第一筆符合的 dict（含 `license_number`、`product_name_en`、`product_name_zh`）；若無符合記錄，SHALL 回傳 `None`。

#### Scenario: 查詢到符合的 pcode
- **WHEN** 以有效 pcode（如 `"023177"`）呼叫 `get_product_by_pcode()`
- **THEN** 回傳包含 `license_number`、`product_name_en`、`product_name_zh` 的 dict

#### Scenario: 查詢不到符合的 pcode
- **WHEN** 以不存在的 pcode 呼叫 `get_product_by_pcode()`
- **THEN** 回傳 `None`，不拋出例外

#### Scenario: cache 為空時觸發延遲載入
- **WHEN** `_permit_cache` 為空且呼叫 `get_product_by_pcode()`
- **THEN** 系統嘗試重新呼叫 `_load_permit_data()` 填充 cache，再執行查詢

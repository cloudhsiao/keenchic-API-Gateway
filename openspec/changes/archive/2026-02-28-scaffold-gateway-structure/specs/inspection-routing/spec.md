## ADDED Requirements

### Requirement: X-API-KEY 標頭驗證
系統 SHALL 讀取每個受保護請求的 `X-API-KEY` 標頭，並與環境變數 `KEENCHIC_API_KEY` 的值進行比對。若標頭缺失或值不符，SHALL 回傳 HTTP 401；若環境變數未設定，SHALL 回傳 HTTP 500。`GET /health` 端點不需驗證。

#### Scenario: 有效 API key
- **WHEN** 請求包含正確的 `X-API-KEY` 標頭
- **THEN** 系統繼續處理請求，回傳 HTTP 200

#### Scenario: 遺漏 API key
- **WHEN** 請求未包含 `X-API-KEY` 標頭
- **THEN** 系統回傳 HTTP 401，body 包含 `{"detail": "Unauthorized"}`

#### Scenario: 錯誤的 API key
- **WHEN** 請求包含的 `X-API-KEY` 值與環境變數不符
- **THEN** 系統回傳 HTTP 401，body 包含 `{"detail": "Unauthorized"}`

#### Scenario: 環境變數未設定
- **WHEN** `KEENCHIC_API_KEY` 環境變數未設定且收到任何請求
- **THEN** 系統回傳 HTTP 500，body 包含錯誤說明

### Requirement: X-Inspection-Name 路由
系統 SHALL 讀取 `POST /api/v1/inspect` 請求的 `X-Inspection-Name` 標頭，並路由到對應的 inspection adapter。若標頭缺失或值不在 registry 中，SHALL 回傳 HTTP 422。

#### Scenario: 有效 inspection name
- **WHEN** 請求包含合法的 `X-Inspection-Name`（如 `ocr/datecode-num`）
- **THEN** 系統將請求路由至對應 adapter 並執行辨識

#### Scenario: 不存在的 inspection name
- **WHEN** 請求包含未登錄的 `X-Inspection-Name`（如 `ocr/unknown`）
- **THEN** 系統回傳 HTTP 422，body 說明該 inspection name 不存在

#### Scenario: 遺漏 X-Inspection-Name 標頭
- **WHEN** 請求未包含 `X-Inspection-Name` 標頭
- **THEN** 系統回傳 HTTP 422，提示標頭為必填

### Requirement: Health Check 端點
`GET /health` SHALL 回傳 HTTP 200 及目前系統狀態，包含當前載入的 inspection name 與 backend 類型，不需 API key 驗證。

#### Scenario: 正常查詢健康狀態
- **WHEN** 收到 `GET /health` 請求
- **THEN** 系統回傳 HTTP 200，body 包含 `{"status": "ok", "loaded_inspection": "<name or null>", "backend": "<backend>"}`

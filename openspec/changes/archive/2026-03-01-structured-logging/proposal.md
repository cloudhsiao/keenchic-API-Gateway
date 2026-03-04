## Why

目前所有執行期輸出均透過 `print()` 寫入 stdout，缺乏欄位化資訊（request-id、介面名稱、處理時長），無法用 log aggregator 過濾、追蹤或告警，也難以在多工環境中對應同一筆請求的生命週期。

## What Changes

- 引入 `structlog` 作為統一 logger，取代所有 `print()` 呼叫
- 每個 HTTP 請求自動附加隨機產生的 `request_id`（UUID4 短碼）
- 記錄欄位：`request_id`、`inspection_name`、`duration_ms`、`status_code`、`error`（可選）
- 日誌格式可透過環境變數切換：開發環境輸出人類可讀的 colored text；生產環境輸出 JSON（供 log collector 消費）
- `InspectionManager` 的 model load/unload 事件納入結構化日誌

**Non-goals**

- 不整合 Prometheus 或任何 metrics 系統（另立 change）
- 不修改 `keenchic/inspections/ocr/`（submodule，唯讀）
- 不導入中央化 log aggregator（基礎建設不在此範疇）

## Capabilities

### New Capabilities
- `request-logging`：HTTP 請求全生命週期的結構化日誌，含 request-id 追蹤、處理時間與錯誤欄位

### Modified Capabilities
（無現有 spec 受到功能需求層面的異動）

## Impact

**受影響的程式碼**
- `main.py`：加入 structlog 初始化與 lifespan logging
- `keenchic/api/router.py`（或對應路由檔）：middleware 注入 request-id；請求進入/完成時各記錄一次
- `keenchic/core/inspection_manager.py`：load/unload model 改用 structured logger

**新增依賴**
- `structlog`（純 Python，無系統依賴）

**環境變數**
- `LOG_FORMAT`：`text`（預設）或 `json`
- `LOG_LEVEL`：`DEBUG` / `INFO`（預設）/ `WARNING` / `ERROR`

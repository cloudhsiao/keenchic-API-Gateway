## ADDED Requirements

### Requirement: 結構化日誌初始化
應用程式 SHALL 在啟動時透過 `configure_logging()` 初始化 structlog，
依據 `LOG_FORMAT` 環境變數決定輸出格式：
- `text`（預設）：人類可讀的 ConsoleRenderer（含 ANSI 色彩）
- `json`：機器可讀的 JSONRenderer，適用 log collector

#### Scenario: 以 text 格式啟動
- **WHEN** `LOG_FORMAT` 未設定或設為 `text`
- **THEN** structlog 輸出 key=value 格式日誌至 stdout

#### Scenario: 以 json 格式啟動
- **WHEN** `LOG_FORMAT=json`
- **THEN** structlog 輸出每行一個 JSON 物件至 stdout

#### Scenario: 無效格式值
- **WHEN** `LOG_FORMAT` 設為非 `text` / `json` 的值
- **THEN** 應用程式記錄 warning 並回退至 `text` 格式，不中止啟動

---

### Requirement: 請求 ID 注入
每個進入應用層的 HTTP 請求 SHALL 被自動分配一個唯一 `request_id`（12 位 hex 字串），
並在整個請求生命週期內透過 structlog contextvars 自動攜帶於所有日誌欄位中。

#### Scenario: 正常請求收到 request_id
- **WHEN** 任意 HTTP 請求到達 `/api/v1/inspect` 或 `/health`
- **THEN** 該請求的所有日誌事件均包含相同的 `request_id` 欄位

#### Scenario: 並行請求的 request_id 互不干擾
- **WHEN** 兩個請求同時處理中
- **THEN** 各自的日誌事件僅攜帶自身的 `request_id`，不互相污染

---

### Requirement: 請求生命週期日誌
應用程式 SHALL 在每個 HTTP 請求的進入與完成時各記錄一條結構化日誌。

進入日誌欄位：`request_id`、`method`、`path`、`inspection_name`（若有）
完成日誌欄位：`request_id`、`status_code`、`duration_ms`

#### Scenario: 成功的推理請求
- **WHEN** `POST /api/v1/inspect` 成功回傳 200
- **THEN** 記錄一條 `http.request` 事件（含 method、path、inspection_name）
- **THEN** 記錄一條 `http.response` 事件（含 status_code=200、duration_ms > 0）

#### Scenario: 請求因缺少 header 返回 422
- **WHEN** 請求缺少 `X-Inspection-Name` header
- **THEN** 記錄 `http.response` 事件，status_code=422，duration_ms 為正數

#### Scenario: 未捕捉的例外
- **WHEN** 處理過程中拋出未捕捉的 Exception
- **THEN** 記錄 `http.error` 事件，含 status_code=500 與 `error` 欄位（例外訊息）

---

### Requirement: 模型載入與卸載日誌
`InspectionManager` SHALL 在模型載入與卸載時各記錄一條結構化日誌。

#### Scenario: 首次載入模型
- **WHEN** 新的 `inspection_name` 請求觸發 `load_models()`
- **THEN** 記錄 `model.load` 事件，含 `inspection_name` 與 `backend` 欄位

#### Scenario: 切換至不同模型（含卸載）
- **WHEN** 目前已載入模型 A，請求切換至模型 B
- **THEN** 先記錄 `model.unload` 事件（含前一個 `inspection_name`）
- **THEN** 再記錄 `model.load` 事件（含新的 `inspection_name`）

#### Scenario: 卸載失敗
- **WHEN** `unload_models()` 拋出例外
- **THEN** 記錄 `model.unload_failed` warning 事件，含 `inspection_name` 與 `error` 欄位
- **THEN** 系統繼續嘗試載入新模型，不中止請求

---

### Requirement: 上傳儲存失敗日誌
當 `KEENCHIC_UPLOAD_DIR` 已設定但檔案儲存失敗時，系統 SHALL 記錄 warning 而非 `print()`。

#### Scenario: 上傳儲存目錄無寫入權限
- **WHEN** `KEENCHIC_UPLOAD_DIR` 指向無寫入權限的目錄
- **THEN** 記錄 `upload.save_failed` warning 事件，含 `filename` 與 `error` 欄位
- **THEN** 請求仍正常繼續推理，不因儲存失敗中止

---

### Requirement: 日誌等級設定
應用程式 SHALL 依據 `LOG_LEVEL` 環境變數過濾日誌輸出。
有效值：`DEBUG`、`INFO`（預設）、`WARNING`、`ERROR`（大小寫不敏感）

#### Scenario: 設定為 DEBUG
- **WHEN** `LOG_LEVEL=DEBUG`
- **THEN** 所有等級的日誌均輸出，含細節診斷訊息

#### Scenario: 設定為 WARNING
- **WHEN** `LOG_LEVEL=WARNING`
- **THEN** 僅輸出 warning 及以上等級，`http.request` 等 info 事件不出現

#### Scenario: 無效等級值
- **WHEN** `LOG_LEVEL` 設為非預期值（如 `VERBOSE`）
- **THEN** 回退至 `INFO` 等級並記錄一條 warning，不中止啟動

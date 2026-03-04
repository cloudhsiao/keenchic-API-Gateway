## Context

目前 `print()` 散落在兩處：
- `keenchic/core/inspection_manager.py:54`：unload 失敗警告
- `keenchic/api/router.py:72`：上傳儲存失敗警告

FastAPI 自身依賴 uvicorn 的 access log（stdlib `logging`），但應用層完全無結構化輸出。
需要在不破壞現有路由邏輯的前提下，注入 request-id 並輸出結構化欄位。

## Goals / Non-Goals

**Goals:**
- 以 `structlog` 取代所有 `print()` 呼叫
- 每個 HTTP 請求自動附加 `request_id`，並在同一請求生命週期全程攜帶
- 輸出格式透過 `LOG_FORMAT` env var 切換（`text` / `json`）
- 輸出等級透過 `LOG_LEVEL` env var 控制
- `InspectionManager` 的 load / unload 事件納入結構化日誌

**Non-Goals:**
- Prometheus metrics 或任何 push-based 監控
- 中央化 log aggregator 設定（Loki、ELK 等）
- 修改 submodule（`keenchic/inspections/ocr/`）內部日誌

## Decisions

### 1. 選用 `structlog` 而非擴充 stdlib `logging`

**選擇**：使用 `structlog`

**理由**：stdlib `logging` 的結構化輸出需要自訂 formatter，且 context binding 需手動傳遞 extra dict。
`structlog` 原生支援 context variable 綁定（`structlog.contextvars`），可在 middleware 中一次設定 `request_id`，後續所有 log 自動攜帶，無須傳參。

**替代方案考慮**：`python-json-logger`（只解決格式問題，不解決 context 傳遞）

---

### 2. request_id 注入點：Starlette Middleware

**選擇**：在 `main.py` 以 `app.middleware("http")` 掛載輕量 middleware

**理由**：
- Starlette middleware 在路由層之前執行，可覆蓋 `/health` 與 `/api/v1/inspect` 兩個端點
- 使用 `structlog.contextvars.bind_contextvars(request_id=...)` 綁定至 async context，不需在每個 handler 手動傳遞
- `request_id` 採 `uuid.uuid4().hex[:12]`（12 位短碼），兼顧唯一性與日誌可讀性

**替代方案**：FastAPI `BackgroundTasks` 或 Depends — 無法覆蓋 middleware 層級的錯誤（如 422 validation error），捨棄

---

### 3. 日誌初始化時機

**選擇**：在 `main.py` 的 FastAPI `lifespan` context manager 中呼叫 `configure_logging()`

**理由**：確保在 uvicorn worker 啟動後、第一個請求到達前完成初始化；
在 module import 時初始化會導致測試環境難以覆寫設定。

---

### 4. 日誌輸出格式設計

| `LOG_FORMAT` | 輸出格式 | 適用場景 |
|---|---|---|
| `text`（預設）| ConsoleRenderer（colored key=value）| 本地開發 |
| `json` | JSONRenderer | 生產環境、log collector |

structlog 的 processor chain：
```
TimeStamper → add_log_level → add_logger_name → contextvars_merge → renderer
```

---

### 5. 需要記錄的事件

| 事件 | 位置 | 欄位 |
|---|---|---|
| 請求進入 | middleware | `request_id`, `method`, `path`, `inspection_name` |
| 請求完成 | middleware | `request_id`, `status_code`, `duration_ms` |
| 請求異常 | middleware | `request_id`, `status_code`, `error` |
| model load | `InspectionManager.run()` | `inspection_name`, `backend` |
| model unload | `InspectionManager.run()` | `inspection_name` |
| unload 失敗 | `InspectionManager.run()` | `inspection_name`, `error` |
| 上傳儲存失敗 | `router._save_upload_if_configured()` | `filename`, `error` |

## Risks / Trade-offs

- **structlog + uvicorn stdlib logging 並存**：uvicorn 本身的 access log 仍走 stdlib。
  → 可接受：兩套 log 各自服務不同層（uvicorn transport vs. 應用層業務）；不做統一，避免過度設定。

- **middleware 計時不含 uvicorn 網路層**：`duration_ms` 從 middleware 入口計時，不含 TLS handshake 或 keep-alive 等待。
  → 可接受：應用層延遲已足夠診斷推理瓶頸。

- **同步 `run()` 的 context 傳遞**：`InspectionManager.run()` 內部呼叫同步的 `adapter.run()`，asyncio contextvars 在同執行緒同步呼叫中正常傳遞，無需額外處理。
  → 需在整合測試中驗證 `request_id` 是否正確出現在 model 事件日誌。

## Migration Plan

1. `pyproject.toml`：加入 `structlog` 依賴
2. `keenchic/core/config.py`：新增 `LOG_FORMAT` 與 `LOG_LEVEL` 兩個 Settings 欄位
3. 新增 `keenchic/core/logging.py`：封裝 `configure_logging()` 函式
4. `main.py`：加入 lifespan（呼叫 `configure_logging()`）與 logging middleware
5. `keenchic/core/inspection_manager.py`：將 `print()` 替換為 `structlog.get_logger()`
6. `keenchic/api/router.py`：將 `print()` 替換為 structured logger

**Rollback**：structlog 為純加法依賴；若需回滾，移除 middleware 與 configure_logging() 呼叫，保留 import 不影響功能。

## Open Questions

- 無；範疇已在 proposal 明確定義。

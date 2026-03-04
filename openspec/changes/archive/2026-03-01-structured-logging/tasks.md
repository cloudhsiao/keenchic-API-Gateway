## 1. 依賴與設定

- [x] 1.1 在 `pyproject.toml` 加入 `structlog` 依賴，執行 `uv sync` 確認安裝成功
- [x] 1.2 在 `keenchic/core/config.py` 的 `Settings` 新增兩個欄位：`LOG_FORMAT: str = "text"` 與 `LOG_LEVEL: str = "INFO"`

## 2. 日誌初始化模組

- [x] 2.1 建立 `keenchic/core/logging.py`，實作 `configure_logging(log_format: str, log_level: str)` 函式，依 `log_format` 選擇 ConsoleRenderer 或 JSONRenderer，並設定 processor chain（TimeStamper → add_log_level → add_logger_name → contextvars_merge → renderer）
- [x] 2.2 在 `configure_logging()` 中處理無效 `log_format` 值（回退 `text` 並記錄 warning）與無效 `log_level` 值（回退 `INFO` 並記錄 warning）

## 3. FastAPI 整合

- [x] 3.1 在 `main.py` 加入 `lifespan` context manager，於應用啟動時呼叫 `configure_logging(settings.LOG_FORMAT, settings.LOG_LEVEL)`，並將其掛載至 `FastAPI(lifespan=lifespan)`
- [x] 3.2 在 `main.py` 新增 HTTP logging middleware（`@app.middleware("http")`）：進入時綁定 `request_id`（`uuid.uuid4().hex[:12]`）、`method`、`path`、`inspection_name` 至 contextvars，完成時記錄 `status_code` 與 `duration_ms`，例外時記錄 `error` 欄位並 re-raise

## 4. 替換現有 print() 呼叫

- [x] 4.1 在 `keenchic/core/inspection_manager.py` 加入 `structlog.get_logger()` 模組級 logger，將 `print(f"Warning: failed to unload ...")` 替換為 `log.warning("model.unload_failed", ...)`
- [x] 4.2 在 `keenchic/core/inspection_manager.py` 的 `run()` 中，於 `load_models()` 前後分別記錄 `model.unload` 與 `model.load` 事件（含 `inspection_name`、`backend`）
- [x] 4.3 在 `keenchic/api/router.py` 的 `_save_upload_if_configured()` 中，將 `print(f"Warning: failed to save upload ...")` 替換為 `log.warning("upload.save_failed", ...)`

## 5. 驗證

- [x] 5.1 以 `LOG_FORMAT=text LOG_LEVEL=DEBUG uv run python serve.py` 啟動，送出 `POST /api/v1/inspect` 請求，確認 stdout 出現含 `request_id`、`duration_ms` 的 key=value 日誌
- [x] 5.2 以 `LOG_FORMAT=json` 重新啟動，確認相同請求的日誌輸出為合法 JSON（可用 `| python -m json.tool` 驗證）
- [x] 5.3 觸發模型切換（送出兩個不同 `X-Inspection-Name` 的請求），確認 `model.unload` 與 `model.load` 事件出現在日誌中且均攜帶正確的 `request_id`
<!-- 5.1–5.3 需實際推理環境（GPU/OpenVINO 模型）進行人工驗證 -->

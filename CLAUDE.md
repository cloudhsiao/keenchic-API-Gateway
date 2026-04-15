# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# 語言
- 對話總是用繁體中文回覆、唯有專有技術名詞以英文呈現（例如 P-value）
- 程式碼內容（包括 string）以及註解總是以英文撰寫


# 程式碼偏好
- 使用 4 個空格縮排
- 使用 pytest 而非 unittest
- 函數必須有完整的 type hints
- 優先使用 f-string 而非 format()
- 總是使用 uv 管理 python 套件


## Git Workflow 規範
- 頻繁提交：每次完成一組功能後必須 commit
- 提交訊息請涵蓋變更的全部範圍，並保持訊息簡潔
- 開始實作新功能時建立並切換到新的 Git 分支
- 永遠 *不要* 推送到 main 分支（main 或 master），避免干擾 prod 環境


## 常用指令

```bash
# 安裝依賴
uv sync

# 啟動 server（預設 port 8000）
uv run keenchic-serve
uv run keenchic-serve --backend cpu --port 8080

# 直接用 uvicorn
uv run uvicorn main:app --host 0.0.0.0 --port 8000

# 執行測試
uv run pytest
uv run pytest tests/test_router.py::test_health -v

# Jetson aarch64 wheel 構建（須先安裝 cython, setuptools, wheel, numpy）
python3 build_wheel.py
```


## 專案架構

### 請求流程

```
HTTP POST /api/v1/inspect
  Header: X-API-KEY         → deps.py: require_api_key() 驗證
  Header: X-Inspection-Name → router.py 讀取，傳入 InspectionManager
  Body:   multipart/form-data (image, date_image, permit_image, YMD_option, include_diag)
          ↓
  router.py: 驗證 kwargs（adapter.accepted_kwargs() 動態白名單，非法欄位回 422）
          ↓
  InspectionManager.run(inspection_name, image, **kwargs)
    → registry.py: get_adapter_class(name)   # 首次呼叫才 importlib 載入
    → adapter.load_models(backend)           # 第一次或切換 inspection 時
    → adapter.run(image, **kwargs)           # 同步推理
          ↓
  JSONResponse (InspectResponse schema)
```

### 核心模組

| 檔案 | 職責 |
|------|------|
| `main.py` | FastAPI app，lifespan、structlog logging middleware（綁定 request_id） |
| `serve.py` | CLI entry point（`keenchic-serve`），解析 --backend/--host/--port |
| `keenchic/core/config.py` | pydantic-settings，讀取環境變數 |
| `keenchic/core/inspection_manager.py` | **Singleton**，asyncio.Lock 序列化 load/unload，一次只保留一個 adapter |
| `keenchic/core/logging.py` | structlog 設定，支援 text/json 輸出格式 |
| `keenchic/api/router.py` | `POST /api/v1/inspect`、`GET /health` |
| `keenchic/api/deps.py` | `require_api_key()` FastAPI dependency |
| `keenchic/inspections/base.py` | `InspectionAdapter` ABC（load_models / unload_models / run / accepted_kwargs） |
| `keenchic/inspections/registry.py` | `_ADAPTER_ENTRIES` → lazy `importlib.import_module` 建構 registry |
| `keenchic/inspections/result_codes.py` | `InspectionResultCode`（0=SUCCESS, 1=INVALID_INPUT, 2=DETECTION_FAILED） |
| `keenchic/schemas/response.py` | `InspectResponse` pydantic model |
| `keenchic/services/permit_lookup.py` | FDA open data 許可證查詢，模組載入時預載快取，失敗則首次查詢時重試 |
| `build_wheel.py` | Cython wheel 構建（三層編譯：keenchic dotted modules → submodule dotted → submodule bare） |

### Adapter 對照表

| X-Inspection-Name | Adapter Class | Submodule Dir | accepted_kwargs |
|---|---|---|---|
| `ocr/datecode-num` | `DatecodeNumAdapter` | `ocr/` + `datecode_num_st/` | `include_diag`, `YMD_option`, `permit_image` |
| `ocr/holo-num` | `HoloNumAdapter` | `holo_num_st_lol/` | `include_diag` |
| `ocr/pill-count` | `PillCountAdapter` | `pill_count_st/` | `include_diag` |
| `ocr/temper-num` | `TemperNumAdapter` | `temper_num_st/` | `include_diag` |
| `ocr/temper-table` | `TemperTableAdapter` | `temper_num_st/` | `include_diag`, `input_coords`, `table_size` |

所有 submodule dir 位於 `keenchic/inspections/ocr/` 下。

### Backend 選擇邏輯

`KEENCHIC_BACKEND` env var（或 `--backend` CLI arg）控制推理後端：
- `GPU` / `trt` / `tensorrt` → TensorRT，失敗自動 fallback 到 OpenVINO
- `CPU` / `openvino` → 強制 OpenVINO
- `AUTO` → 同 GPU 邏輯

`temper_num` 無 TRT weights，永遠走 OpenVINO。
`temper_table` 支援 TRT（primary on GPU edge server）及 OpenVINO fallback；兩者共用 `temper_num_st/` submodule dir，使用不同的後端模組（`model_detect_openvino_512` / `model_detect_trt_512`）。

### 環境變數（`.env` 或 shell export）

| 變數 | 說明 | 預設 |
|------|------|------|
| `KEENCHIC_API_KEY` | X-API-KEY header 驗證（必填） | `""` |
| `KEENCHIC_BACKEND` | 推理後端 | `GPU` |
| `KEENCHIC_UPLOAD_DIR` | 上傳圖片儲存目錄（選填） | `None` |
| `LOG_FORMAT` | `text` 或 `json` | `text` |
| `LOG_LEVEL` | `DEBUG` / `INFO` / `WARNING` / `ERROR` | `INFO` |


## 新增 Adapter

1. 在 `keenchic/inspections/adapters/ocr/` 新增 `<name>.py`，繼承 `InspectionAdapter`，實作 `load_models` / `unload_models` / `run`
2. 若需要額外請求欄位，覆寫 `accepted_kwargs()` 回傳 set（router 據此做白名單驗證）
3. 在 `keenchic/inspections/registry.py` 的 `_ADAPTER_ENTRIES` 加一行 `(name, module_path, class_name)`

### sys.path 衝突處理

各 submodule 內部使用裸 `import`（例如 `from utils import ...`），不是 package-relative import。每個 adapter 的 `load_models` 必須先呼叫 `_ensure_submodule_on_path()`，清除衝突的 `sys.modules` entry 再插入正確路徑。

## 重要限制

- `keenchic/inspections/ocr/` 是 **git submodule**，任何檔案**不得修改**；只能讀取以理解介面
- `pill_count_st/procd_pill.py` 頂層 `import streamlit`，但 `proc()` 不使用它 → adapter 必須在 import 前先 mock
- `holo_num` 兩個後端使用不同 proc 檔：OpenVINO 用 `procd_holo_ov`，TRT 用 `procd_holo`
- `holo_num` TRT 的 enhance model 是工廠函式（`get_model_trt`），由 `procd_holo.proc` 在推理時呼叫
- `InspectionManager` 使用 `asyncio.Lock` 序列化，uvicorn 限 `workers=1`

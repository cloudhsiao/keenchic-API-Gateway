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

### Fork Workflow（本 repo 專屬）

本 repo 採用 fork workflow：
- `origin` = `cloudhsiao/keenchic-API-Gateway`（個人 fork）
- `upstream` = `shrchen1/keenchic-API-Gateway`（原始 repo，prod）

規則：
- Feature branch 一律 `git push -u origin <branch>`，**永不 push 到 upstream**
- PR 必須從 `cloudhsiao:<branch>` 開到 `shrchen1:main`
- 開新 feature branch 前必須先切回 main 並同步上游：
  ```bash
  git checkout main
  git fetch upstream
  git merge --ff-only upstream/main
  git push origin main                 # 讓 fork 的 main 也跟上，避免逐漸落後
  git checkout -b feat/<next-feature>
  ```
- 使用 gh CLI：`gh pr create --repo shrchen1/keenchic-API-Gateway --base main --head cloudhsiao:<branch>`
  - 或執行一次 `gh repo set-default shrchen1/keenchic-API-Gateway`，之後 `gh pr create` 可省略 `--repo`

### AI Commit 前檢查

Commit 之前，AI 必須對照**變更主題**與**當前 branch name 前綴**（feat/fix/chore/docs）：
- 主題嚴重不符時（例如 `fix/*` branch 出現新功能 / `docs/*` 夾帶邏輯變更），先提示使用者是否要改 branch name、拆 commit、或拆 PR
- 相符或只是小幅順手修（typo、註解）則直接 commit，不打斷流程
- 同一 branch 含多種主題但有清楚 umbrella（例如 `chore/hardening` 含 feat + fix + docs）算合理，不需提示


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
python3 build_wheel.py                              # 全部算法
python3 build_wheel.py --list                       # 列出可選算法
python3 build_wheel.py -a ocr/datecode-num          # 單一算法
python3 build_wheel.py -a ocr/datecode-num -a ocr/pill-count  # 子集（PEP 440 local version 命名）
```


## API Service Dev Runbook

### 本機開發啟動

```bash
# 1. 安裝依賴
uv sync

# 2. 建立本機環境變數
cp .env.example .env

# 3. 至少設定 API key；CPU 開發建議同時設定 backend
export KEENCHIC_API_KEY=dev-api-key
export KEENCHIC_BACKEND=CPU

# 4. 啟動 API service
uv run python serve.py --backend cpu
```

### 常用 dev 啟動方式

```bash
# 推薦：走 CLI entrypoint
uv run keenchic-serve --backend cpu --host 0.0.0.0 --port 8000

# 等價方式：直接跑 serve.py
uv run python serve.py --backend cpu --host 0.0.0.0 --port 8000

# 進階：直接跑 uvicorn，workers 必須是 1
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

### 背景執行與看 log

```bash
# 背景執行
uv run python serve.py --backend cpu > /tmp/keenchic-api.log 2>&1 &

# 即時追 log
tail -f /tmp/keenchic-api.log
```

### 啟動後確認

```bash
curl http://127.0.0.1:8000/health
```

預期回傳至少包含：
- `status: ok`
- `backend_config: CPU`（若以 CPU 模式啟動）

### 開發注意事項

- 本 repo 預設 `KEENCHIC_BACKEND=GPU`，本機開發若沒有 TensorRT / CUDA，請明確使用 `--backend cpu` 或設定 `KEENCHIC_BACKEND=CPU`
- `.env` 會由 `pydantic-settings` 自動載入，不一定要用 shell `export`
- 若使用 `uvicorn`，`--workers` 必須固定為 `1`，因為模型 singleton 無法跨 process 共享
- `KEENCHIC_UPLOAD_DIR` 有設定時，request 上傳圖片會被存到該目錄；不想落地可留空
- 若要被動監看錯誤，不必主動打 API，只需讓服務在背景執行並 `tail -f` log


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
| `build_wheel.py` | Cython wheel 構建；由 `*.build.toml` descriptor 驅動，支援 `--algorithm` 選擇性打包 |

### Adapter 對照表

| X-Inspection-Name | Adapter Class | Submodule Dir | accepted_kwargs |
|---|---|---|---|
| `ocr/datecode-num` | `DatecodeNumAdapter` | `ocr/` + `datecode_num_st/` | `include_diag`, `YMD_option`, `permit_image` |
| `ocr/holo-num` | `HoloNumAdapter` | `holo_num_st_lol/` | `include_diag` |
| `ocr/pill-count` | `PillCountAdapter` | `pill_count_st/` | `include_diag` |
| `ocr/temper-num` | `TemperNumAdapter` | `temper_num_st/` | `include_diag` |
| `ocr/meter-table` | `MeterTableAdapter` | `temper_num_st/` | `include_diag`, `input_coords`, `table_size` |

所有 submodule dir 位於 `keenchic/inspections/ocr/` 下。

### Backend 選擇邏輯

`KEENCHIC_BACKEND` env var（或 `--backend` CLI arg）控制推理後端：
- `GPU` / `trt` / `tensorrt` → TensorRT，失敗自動 fallback 到 OpenVINO
- `CPU` / `openvino` → 強制 OpenVINO
- `AUTO` → 同 GPU 邏輯

`temper_num` 無 TRT weights，永遠走 OpenVINO。
`meter_table` 支援 TRT（primary on GPU edge server）及 OpenVINO fallback；兩者共用 `temper_num_st/` submodule dir，使用不同的後端模組（`model_detect_openvino_512` / `model_detect_trt_512`）。

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
3. 在 `keenchic/inspections/registry.py` 的 `_ADAPTER_ENTRIES` 加一行：
   ```python
   ("ocr/my-feature", "keenchic.inspections.adapters.ocr.my_feature", "MyFeatureAdapter"),
   ```
4. 在同目錄新增 `<name>.build.toml`（build_wheel.py 自動 discover，**不需修改 build_wheel.py**）：
   ```toml
   inspection_name = "ocr/my-feature"

   [adapter]
   source = "keenchic/inspections/adapters/ocr/my_feature.py"
   cython = true   # false 則以 .py 形式保留

   [[submodule]]
   dir = "keenchic/inspections/ocr/my_feature_st"
   dotted = [
       { name = "my_feature_st.model_detect", src = "model_detect.py" },
   ]
   bare = [
       { name = "utils", src = "utils.py" },
   ]
   weights_subdir = "weights"
   ```
   - `dotted`：adapter 用 `from my_feature_st.xxx import ...` 的模組，從 parent dir（`ocr/`）編譯
   - `bare`：submodule 內部裸 `import xxx` 的模組，從 submodule dir 本身編譯
   - 共用 submodule dir 的算法（如 `temper-num` 和 `meter-table` 共用 `temper_num_st/`）重複宣告即可，build 時自動去重

### sys.path 衝突處理

各 submodule 內部使用裸 `import`（例如 `from utils import ...`），不是 package-relative import。每個 adapter 的 `load_models` 必須先呼叫 `_ensure_submodule_on_path()`，清除衝突的 `sys.modules` entry 再插入正確路徑。

## 重要限制

- `keenchic/inspections/ocr/` 是 **git submodule**，任何檔案**不得修改**；只能讀取以理解介面
- `pill_count_st/procd_pill.py` 頂層 `import streamlit`，但 `proc()` 不使用它 → adapter 必須在 import 前先 mock
- `holo_num` 兩個後端使用不同 proc 檔：OpenVINO 用 `procd_holo_ov`，TRT 用 `procd_holo`
- `holo_num` TRT 的 enhance model 是工廠函式（`get_model_trt`），由 `procd_holo.proc` 在推理時呼叫
- `InspectionManager` 使用 `asyncio.Lock` 序列化，uvicorn 限 `workers=1`

## Why

目前專案根目錄只有一個單體 `main.py`（從 datecode-num POC 演化而來），直接寫死了 datecode 辨識邏輯，無法支援多個 inspection 模組的路由。需要在 POC 成果的基礎上，建立可擴充的 API gateway 架構，使新增 inspection 模組時只需新增 adapter 與更新 registry，不修改核心框架程式碼。

## What Changes

- 建立 `keenchic/` 作為主 package namespace，取代目前扁平的根目錄結構
- 建立 `keenchic/api/`：FastAPI router（`POST /api/v1/inspect`、`GET /health`）與 auth dependency（`X-API-KEY` header）
- 建立 `keenchic/core/config.py`：以 pydantic-settings 集中管理環境變數
- 建立 `keenchic/core/inspection_manager.py`：singleton，維護當前載入的 adapter 與模型，同名 inspection 請求直接複用，不同名時先卸載再載入，以 `asyncio.Lock` 保護
- 建立 `keenchic/inspections/base.py` + `registry.py`：InspectionAdapter ABC 與 `"ocr/datecode-num"` → adapter class 對應表
- 建立 `keenchic/inspections/adapters/ocr/datecode_num.py`：第一個 adapter，封裝現有 `datecode_num_st` 的 `proc()` 呼叫（含 v2 permit image + product lookup）
- 將根目錄 `util.py` 的 FDA 藥證查詢邏輯遷移至 `keenchic/services/permit_lookup.py`
- 重構根目錄 `main.py` 為精簡的 FastAPI app factory
- **submodule 不異動**：`keenchic/inspections/ocr/` 維持現有 `.gitmodules` 路徑

## Capabilities

### New Capabilities

- `inspection-routing`：透過 `X-Inspection-Name` header 路由到對應 adapter，並以 `X-API-KEY` 驗證身份
- `dynamic-model-cache`：InspectionManager 動態載入/卸載模型，相同 inspection name 不重複載入
- `inspection-adapter-interface`：InspectionAdapter ABC 與 registry，定義新增模組的擴充合約
- `ocr-datecode-num`：datecode-num OCR adapter（含 v1 單圖 + v2 雙圖含藥證查詢）
- `permit-lookup`：FDA 藥證資料查詢服務（從 data.fda.gov.tw 下載並 in-memory cache）

### Modified Capabilities

（無，目前 `openspec/specs/` 為空，無既有 spec 需更新）

## Non-goals

- 不新增其他 OCR adapter（holo-num、pill-count、temper-num）：架構就位後另立 change
- 不建立 Docker / docker-compose：本次僅針對裸機 uvicorn 執行環境
- 不實作 API key 的多租戶或權限管理：維持單一靜態 key
- 不修改 `keenchic/inspections/ocr/` submodule 內的任何演算法程式碼

## Impact

- **新增檔案**：`keenchic/` package 下所有新建模組（約 10 個 Python 檔案）
- **修改檔案**：根目錄 `main.py`（精簡為 app factory）；`util.py` 移至 `keenchic/services/permit_lookup.py` 後可刪除
- **無 API 破壞性變更**：`POST /api/v1/inspect` 端點行為與現有 `main.py` 的 v1/v2 相同
- **依賴**：新增 `pydantic-settings`；其餘依賴不變

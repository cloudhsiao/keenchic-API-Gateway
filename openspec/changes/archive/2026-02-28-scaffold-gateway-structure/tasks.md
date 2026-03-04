## 1. Package 骨架建立

- [x] 1.1 建立 `keenchic/__init__.py`、`keenchic/api/__init__.py`、`keenchic/core/__init__.py`、`keenchic/services/__init__.py`、`keenchic/schemas/__init__.py`、`keenchic/inspections/__init__.py`、`keenchic/inspections/adapters/__init__.py`、`keenchic/inspections/adapters/ocr/__init__.py` 共 8 個 `__init__.py`
- [x] 1.2 建立 `pyproject.toml`，宣告 Python >= 3.12、依賴 `fastapi`、`uvicorn`、`pydantic-settings`、`python-multipart`，並設定 package root 為 `keenchic/`

## 2. Core 設定層

- [x] 2.1 建立 `keenchic/core/config.py`：以 `pydantic-settings` 的 `BaseSettings` 宣告 `KEENCHIC_API_KEY`（str）、`KEENCHIC_BACKEND`（str，預設 `"AUTO"`）、`KEENCHIC_UPLOAD_DIR`（str | None）；匯出 singleton `settings`
- [x] 2.2 建立 `.env.example`，列出所有環境變數範本（含說明注解，不填入實際值）

## 3. Inspection Adapter 框架

- [x] 3.1 建立 `keenchic/inspections/base.py`：定義 `InspectionAdapter` ABC，包含抽象方法 `load_models(backend: str) -> None`、`unload_models() -> None`、`run(image: np.ndarray, **kwargs) -> dict`
- [x] 3.2 建立 `keenchic/inspections/registry.py`：定義 `REGISTRY: dict[str, type[InspectionAdapter]]`，初始僅含 `"ocr/datecode-num": DatecodeNumAdapter`（lazy import 避免循環依賴）；提供 `get_adapter_class(name: str) -> type[InspectionAdapter] | None`

## 4. InspectionManager

- [x] 4.1 建立 `keenchic/core/inspection_manager.py`：實作 `InspectionManager` singleton，內含 `_current_name: str | None`、`_current_adapter: InspectionAdapter | None`、`_lock: asyncio.Lock`
- [x] 4.2 在 `InspectionManager` 實作 `async def run(inspection_name: str, image: np.ndarray, **kwargs) -> dict`：相同 name 直接呼叫 `adapter.run()`；不同 name 執行 unload → 查 registry → load → run；name 不在 registry 時拋出 `ValueError`
- [x] 4.3 在 `InspectionManager` 實作 `get_status() -> dict`：回傳 `{"loaded_inspection": ..., "backend": ...}`，供 health endpoint 使用

## 5. Services 層

- [x] 5.1 建立 `keenchic/services/permit_lookup.py`：將根目錄 `util.py` 的完整邏輯（`_load_permit_data()`、`get_product_by_pcode()`、`_permit_cache`、模組匯入時預熱 cache）遷移至此，import 路徑更新為 `keenchic.services.permit_lookup`

## 6. Schemas

- [x] 6.1 建立 `keenchic/schemas/response.py`：定義 `InspectResponse` Pydantic model，包含 `result: int`、`pred_text: str`、`YMD: str`、`pcode: str | None`、`pname_en: str | None`、`pname_zh: str | None`、`diag_img: str | None`（及現有 main.py 的所有回應欄位）

## 7. API 層

- [x] 7.1 建立 `keenchic/api/deps.py`：實作 `require_api_key()` FastAPI Dependency，讀取 `X-API-KEY` header，與 `settings.KEENCHIC_API_KEY` 比對；未設定回 500，不符回 401
- [x] 7.2 建立 `keenchic/api/router.py`：`GET /health`（無 auth，呼叫 `inspection_manager.get_status()`）；`POST /api/v1/inspect`（需 auth，讀 `X-Inspection-Name` header，解碼上傳圖片為 numpy array，呼叫 `inspection_manager.run()`，回傳 `InspectResponse`）

## 8. Datecode-Num Adapter

- [x] 8.1 建立 `keenchic/inspections/adapters/ocr/datecode_num.py`：繼承 `InspectionAdapter`，在 `load_models()` 中確認 submodule import 路徑（`keenchic/inspections/ocr/datecode_num_api/datecode_num_st/`）可正常 import，載入 smp、smp_pcode、yolo12 三個模型
- [x] 8.2 在 `DatecodeNumAdapter.run()` 實作 v1 邏輯：接受 `image`、`YMD_option`、`include_diag`、`debug`，呼叫 `datecode_num_st.proc()` 並整理回傳 dict
- [x] 8.3 在 `DatecodeNumAdapter.run()` 擴充 v2 邏輯：若 `kwargs` 包含 `permit_image`，額外呼叫 pcode 辨識流程，再呼叫 `from keenchic.services.permit_lookup import get_product_by_pcode` 查詢產品名稱，合併進回傳 dict
- [x] 8.4 更新 `keenchic/inspections/registry.py`，正式匯入並登錄 `DatecodeNumAdapter`

## 9. 根目錄 main.py 重構

- [x] 9.1 重構根目錄 `main.py` 為 FastAPI app factory：建立 `app = FastAPI()`，`app.include_router()` 掛載 `keenchic/api/router.py`，移除所有 datecode 特定邏輯
- [x] 9.2 確認 `uvicorn main:app --host 0.0.0.0 --port 8000` 可正常啟動（即使無 GPU 環境，OpenVINO backend 應可啟動）

## 10. 清理與驗證

- [x] 10.1 刪除根目錄 `util.py`（邏輯已遷移至 `keenchic/services/permit_lookup.py`）
- [x] 10.2 執行 smoke test：`curl -X GET http://localhost:8000/health` 回傳 HTTP 200；`curl -X POST http://localhost:8000/api/v1/inspect -H "X-API-KEY: test" -H "X-Inspection-Name: ocr/datecode-num" -F "image=@<test_image.jpg>"` 回傳合法 JSON

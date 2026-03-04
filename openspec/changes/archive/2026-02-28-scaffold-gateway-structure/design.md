## Context

目前根目錄的 `main.py` 是從 `datecode_num_api` POC 直接演化而來的單體 FastAPI app，hardcode 了 datecode 辨識邏輯。若要支援多種 inspection 模組（holo-num、pill-count 等），必須重構成可動態路由的 gateway 架構。現有 submodule `keenchic/inspections/ocr/` 內各模組已有一致的 `proc()` 介面，是實作 adapter pattern 的良好基礎。

## Goals / Non-Goals

**Goals:**
- 建立 `keenchic/` 作為統一 package namespace
- 透過 `X-Inspection-Name` header 路由到對應的 inspection adapter
- InspectionManager singleton 管理動態模型 cache，避免不必要的模型重載
- datecode-num adapter 完整實作（含 v1 + v2 邏輯）
- FDA 藥證查詢邏輯獨立成 service 層

**Non-Goals:**
- holo-num、pill-count、temper-num adapter 實作（留待後續 change）
- Docker / 容器化部署
- 多租戶 API key 管理
- submodule 演算法程式碼的任何修改

## Decisions

### 1. Package Namespace：`keenchic/` 統一所有程式碼

**決策**：自有程式碼（api、core、services、schemas、inspections/adapters）全放入 `keenchic/` package。
**理由**：submodule 路徑 `keenchic/inspections/ocr/` 已在 `.gitmodules` 固定，合併 namespace 可避免兩套根目錄並列的混亂，也讓 import 路徑一致（`from keenchic.core.config import settings`）。
**替代方案考慮過**：獨立 `app/` 目錄（但與 submodule namespace 不一致，需維護兩個根目錄）。

### 2. Adapter 與引擎分離：`adapters/ocr/` vs `ocr/`（submodule）

**決策**：submodule 引擎放 `keenchic/inspections/ocr/`，自有 adapter 放 `keenchic/inspections/adapters/ocr/`。
**理由**：明確區分「不能修改的外部程式碼」與「我們維護的封裝層」，避免日後 submodule 更新時誤觸 adapter 程式碼。
**替代方案考慮過**：adapter 與引擎放同一層（難以區分歸屬，且混入 submodule 目錄會造成 git 衝突風險）。

### 3. 動態模型 cache：last-one-wins singleton

**決策**：`InspectionManager` 內部維護 `_current_name: str | None` 與 `_current_adapter: InspectionAdapter | None`。新請求若 inspection name 相同則直接呼叫 `adapter.run()`；不同則呼叫 `current.unload_models()` → `new.load_models()` → `new.run()`，全程加 `asyncio.Lock`。
**理由**：多數部署場景為單一 inspection 服務連續請求，切換情境較少，last-one-wins 可最大化 cache 命中率，同時避免多個大型 DL 模型同時佔用記憶體。
**替代方案考慮過**：LRU cache 保留多個 adapter（記憶體需求難以預測，各模組模型大小差異大）；per-process 隔離（需 proxy 層，複雜度過高）。

### 4. Auth：FastAPI Dependency

**決策**：`X-API-KEY` header 驗證實作為 `require_api_key()` FastAPI Dependency，注入到需要保護的路由。
**理由**：與現有 POC 行為兼容，Dependency 方式可在測試時輕易 override，不需中間件。
**替代方案考慮過**：Middleware（無法 per-route 細控，例外路由 `/health` 不需驗證）。

### 5. 設定管理：pydantic-settings

**決策**：新增 `keenchic/core/config.py`，以 `pydantic-settings` 的 `BaseSettings` 宣告所有環境變數（`KEENCHIC_API_KEY`、`KEENCHIC_BACKEND`、`KEENCHIC_UPLOAD_DIR`）。
**理由**：型別安全、自動 `.env` 檔案讀取、易於測試（可直接實例化傳入參數）。

## Risks / Trade-offs

| 風險 | 緩解措施 |
|------|----------|
| 切換 inspection 時舊模型 unload 期間新請求卡住 | `asyncio.Lock` 確保序列處理；可在 health endpoint 回報 loading 狀態 |
| FDA API 下載失敗導致 permit_lookup 回傳空 | `permit_lookup.py` 已有 try/except，回傳 `None` 而非拋出例外；v2 回應中 pname 欄位可為空 |
| submodule 更新破壞 adapter 介面 | `InspectionAdapter` ABC 的 `run()` signature 是穩定的 gateway 層契約；submodule 的 `proc()` 行為變動只需修改對應 adapter，不影響 gateway 框架 |
| `keenchic/inspections/ocr/` submodule 與 `keenchic/` package 並存造成 import 混淆 | submodule 內部無 `__init__.py` 作為 package root，需透過 `sys.path` 或相對路徑匯入；adapter 程式碼明確使用完整路徑 import |

## Migration Plan

1. 建立 `keenchic/` package 骨架（所有 `__init__.py`）
2. 建立 `keenchic/core/config.py`（pydantic-settings）
3. 建立 `keenchic/inspections/base.py` + `registry.py`
4. 建立 `keenchic/core/inspection_manager.py`
5. 建立 `keenchic/api/deps.py` + `keenchic/api/router.py`
6. 建立 `keenchic/schemas/`（request.py + response.py）
7. 建立 `keenchic/services/permit_lookup.py`（從根目錄 `util.py` 遷移）
8. 建立 `keenchic/inspections/adapters/ocr/datecode_num.py`
9. 重構根目錄 `main.py` 為單純 app factory
10. 確認 uvicorn 啟動正常、smoke test curl 驗證
11. 刪除根目錄 `util.py`（邏輯已遷入 `services/`）

**回滾策略**：根目錄 `main.py` 在重構完成前保留原有邏輯不刪除；確認新架構通過測試後再切換。

## Open Questions

- `keenchic/inspections/ocr/` submodule 內各模組是否需要在 `sys.path` 做特殊設定，才能讓 adapter 正確 import？需在實作 `datecode_num.py` adapter 時確認。
- v2 的 permit image（第二張圖）是否應作為通用欄位抽象到 `InspectionAdapter` ABC，或維持 datecode-num 專屬邏輯在 adapter 層處理？（目前傾向後者，保持 ABC 介面精簡）

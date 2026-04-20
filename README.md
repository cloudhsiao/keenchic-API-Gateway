# Keenchic Inspection API Gateway

輕量型 FastAPI 推理閘道，透過統一的 HTTP API 路由到各影像辨識模型。同一時間只保留一個 adapter 在記憶體，支援 TensorRT（GPU）與 OpenVINO（CPU）後端自動切換。

---

## 目錄

- [Keenchic Inspection API Gateway](#keenchic-inspection-api-gateway)
  - [目錄](#目錄)
  - [系統需求](#系統需求)
  - [快速開始](#快速開始)
  - [環境變數](#環境變數)
  - [啟動方式](#啟動方式)
    - [使用 serve.py（推薦）](#使用-servepy推薦)
    - [使用 entry point](#使用-entry-point)
    - [使用 uvicorn（進階）](#使用-uvicorn進階)
  - [API 文件](#api-文件)
    - [GET /health](#get-health)
    - [POST /api/v1/inspect](#post-apiv1inspect)
    - [Result Code 對照表](#result-code-對照表)
    - [Inspection 清單與回應欄位](#inspection-清單與回應欄位)
      - [`ocr/datecode-num` — 日期碼 OCR](#ocrdatecode-num--日期碼-ocr)
      - [`ocr/holo-num` — 全息數字 OCR](#ocrholo-num--全息數字-ocr)
      - [`ocr/pill-count` — 藥丸計數](#ocrpill-count--藥丸計數)
      - [`ocr/temper-num` — 溫度 / 有效期 OCR](#ocrtemper-num--溫度--有效期-ocr)
      - [`ocr/meter-table` — 多通道溫度表格 OCR](#ocrmeter-table--多通道溫度表格-ocr)
  - [架構說明](#架構說明)
  - [Wheel 打包（Jetson 部署）](#wheel-打包jetson-部署)
  - [新增 Adapter](#新增-adapter)

---

## 系統需求

| 項目 | 版本 |
|---|---|
| Python | 3.12+ |
| uv（套件管理） | 最新版 |
| OpenVINO | 2025.3.0 |
| TensorRT（GPU，選用） | 視硬體而定 |
| CUDA（GPU，選用） | 視 TRT 版本而定 |

---

## 快速開始

```bash
# 1. 安裝依賴
uv sync

# 2. 建立環境變數檔
cp .env.example .env
# 編輯 .env，至少設定 KEENCHIC_API_KEY

# 3. 啟動服務（CPU 模式）
uv run python serve.py --backend cpu

# 4. 確認服務正常
curl http://localhost:8000/health
```

---

## 環境變數

建立 `.env` 檔案並設定以下變數（參考 `.env.example`）。

| 變數名稱 | 必填 | 預設值 | 說明 |
|---|---|---|---|
| `KEENCHIC_API_KEY` | 是 | — | 所有受保護端點的靜態 API 金鑰，透過 `X-API-KEY` header 驗證 |
| `KEENCHIC_BACKEND` | 否 | `GPU` | 推理後端：`GPU`（TRT 優先，失敗自動降級 OpenVINO）、`CPU`（OpenVINO）、`AUTO`（同 GPU） |
| `KEENCHIC_UPLOAD_DIR` | 否 | 空（停用） | 上傳影像的儲存目錄；留空表示不儲存 |
| `LOG_FORMAT` | 否 | `text` | 日誌格式：`text`（人類可讀）或 `json`（結構化，適合 log aggregator） |
| `LOG_LEVEL` | 否 | `INFO` | 日誌等級：`DEBUG` / `INFO` / `WARNING` / `ERROR` |

---

## 啟動方式

### 使用 serve.py（推薦）

```bash
uv run python serve.py [選項]
```

| 選項 | 預設值 | 說明 |
|---|---|---|
| `--backend {gpu,cpu,auto}` | 讀取 `KEENCHIC_BACKEND` | 覆蓋環境變數設定 |
| `--host HOST` | `0.0.0.0` | 綁定 IP |
| `--port PORT` | `8000` | 綁定埠號 |

範例：

```bash
# CPU 模式，埠號 8080
uv run python serve.py --backend cpu --port 8080

# GPU 模式，僅本機存取
uv run python serve.py --backend gpu --host 127.0.0.1
```

### 使用 entry point

安裝後可直接執行：

```bash
keenchic-serve --backend cpu
```

### 使用 uvicorn（進階）

```bash
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

> **注意**：因模型為單例且不可分享跨 process，`--workers` 必須為 `1`。

---

## API 文件

啟動後可瀏覽自動產生的互動式文件：

- Swagger UI：`http://localhost:8000/docs`
- ReDoc：`http://localhost:8000/redoc`

---

### GET /health

健康檢查，無需認證。

**回應範例**

```json
{
  "status": "ok",
  "loaded_inspection": "ocr/datecode-num",
  "backend": "openvino"
}
```

| 欄位 | 說明 |
|---|---|
| `status` | 固定為 `"ok"` |
| `loaded_inspection` | 目前載入的 inspection 名稱；未載入時為 `null` |
| `backend` | 目前使用的推理後端（`tensorrt` / `openvino`） |

---

### POST /api/v1/inspect

影像辨識推理，需提供 API 金鑰。

**Headers**

| Header | 必填 | 說明 |
|---|---|---|
| `X-API-KEY` | 是 | 對應 `KEENCHIC_API_KEY` 環境變數 |
| `X-Inspection-Name` | 是 | 指定辨識項目，如 `ocr/datecode-num` |

**Request（multipart/form-data）**

| 欄位 | 類型 | 說明 |
|---|---|---|
| `image` | file | 待辨識影像（PNG / JPG 等 OpenCV 支援格式）。除 `ocr/datecode-num` 外均為必填 |
| `date_image` | file | 僅 `ocr/datecode-num`：日期戳記影像。優先於 `image`；兩者至少提供其一 |
| `permit_image` | file | 僅 `ocr/datecode-num`：許可證影像（選填）。提供時觸發 FDA 資料庫查詢 |
| `YMD_option` | string | 僅 `ocr/datecode-num`：`1`=D/M/Y（預設），`2`=M/D/Y |

> 傳入某個 inspection 不支援的欄位（如對 `ocr/pill-count` 傳 `permit_image`），會收到 HTTP 422。

**Query 參數**

| 參數 | 類型 | 預設值 | 說明 |
|---|---|---|---|
| `include_diag` | bool | `false` | 回應中包含 base64 診斷圖（`diag_img`） |

**curl 範例**

```bash
# 基本辨識
curl -X POST http://localhost:8000/api/v1/inspect \
  -H "X-API-KEY: your-api-key" \
  -H "X-Inspection-Name: ocr/datecode-num" \
  -F "image=@/path/to/image.jpg"

# 指定日期格式（YMD_option 為 form field）
curl -X POST http://localhost:8000/api/v1/inspect \
  -H "X-API-KEY: your-api-key" \
  -H "X-Inspection-Name: ocr/datecode-num" \
  -F "image=@/path/to/image.jpg" \
  -F "YMD_option=2"

# 含許可證影像（v2）
curl -X POST http://localhost:8000/api/v1/inspect \
  -H "X-API-KEY: your-api-key" \
  -H "X-Inspection-Name: ocr/datecode-num" \
  -F "image=@/path/to/date_image.jpg" \
  -F "permit_image=@/path/to/permit_image.jpg"

# 含診斷圖
curl -X POST "http://localhost:8000/api/v1/inspect?include_diag=true" \
  -H "X-API-KEY: your-api-key" \
  -H "X-Inspection-Name: ocr/pill-count" \
  -F "image=@/path/to/pills.jpg"
```

**回應結構（200 OK）**

```json
{
  "result": 0,
  "pred_text": "220115",
  "pred_text_b": "",
  "pred_text_b2": "",
  "YMD": "15/01/2022",
  "YMD_b": "",
  "YMD_b2": "",
  "pred_text_p": "220115",
  "pred_text_b_p": "",
  "pred_text_b2_p": "",
  "pcode": null,
  "pcode_b": null,
  "pcode_b2": null,
  "pname_en": null,
  "pname_zh": null,
  "diag_img": null
}
```

**錯誤回應**

| HTTP 狀態碼 | 原因 |
|---|---|
| `400` | 影像檔案無法解碼（非有效圖片格式） |
| `401` | `X-API-KEY` 缺失或不正確 |
| `422` | 缺少必要欄位、`X-Inspection-Name` 不存在、傳入不支援的欄位 |
| `503` | 模型載入失敗（所有後端均無法初始化） |

---

### Result Code 對照表

所有 inspection 的 `result` 欄位使用統一定義（`InspectionResultCode`）：

| 值 | 名稱 | 說明 |
|---|---|---|
| `0` | `SUCCESS` | 辨識成功 |
| `1` | `INVALID_INPUT` | 無效輸入（由 gateway 層攔截，通常對應 HTTP 400） |
| `2` | `DETECTION_FAILED` | 影像中未能偵測或辨識目標 |

---

### Inspection 清單與回應欄位

#### `ocr/datecode-num` — 日期碼 OCR

辨識包裝上的生產日期或有效期限數字，支援雙圖模式（含許可證辨識與 FDA 資料庫查詢）。

| 欄位 | 說明 | v1 | v2（含 permit_image）|
|---|---|---|---|
| `result` | Result code | O | O |
| `pred_text` | 主要辨識文字 | O | O |
| `pred_text_b` / `pred_text_b2` | 備選辨識結果 | O | O |
| `YMD` / `YMD_b` / `YMD_b2` | 格式化日期字串 | O | O |
| `pred_text_p` / `*_p` | 後處理填充版本 | O | O |
| `pcode` / `pcode_b` / `pcode_b2` | 許可證號碼 | — | O |
| `pname_en` / `pname_zh` | 英文 / 中文品名（FDA 查詢） | — | O |
| `diag_img` | 診斷圖（include_diag=true） | O | O |

支援後端：OpenVINO、TensorRT

---

#### `ocr/holo-num` — 全息數字 OCR

辨識全息防偽標籤上的數字，pipeline：低光增強 → 顯示區裁切 → 字符偵測。

| 欄位 | 說明 |
|---|---|
| `result` | Result code |
| `pred_text` | 辨識文字 |
| `diag_img` | 原始診斷圖（include_diag=true） |
| `diag_img_en` | 增強後診斷圖（include_diag=true） |

支援後端：OpenVINO、TensorRT

---

#### `ocr/pill-count` — 藥丸計數

使用實例分割模型計算影像中的藥丸數量。

| 欄位 | 說明 |
|---|---|
| `result` | Result code |
| `pill_counts` | 偵測到的藥丸數量 |
| `diag_img` | 診斷圖（include_diag=true） |

支援後端：OpenVINO、TensorRT

---

#### `ocr/temper-num` — 溫度 / 有效期 OCR

辨識溫度計或有效期限面板上的數字。

| 欄位 | 說明 |
|---|---|
| `result` | Result code |
| `pred_text` | 辨識文字 |
| `diag_img` | 診斷圖（include_diag=true） |

支援後端：OpenVINO（僅 CPU，無 TRT 權重）

---

#### `ocr/meter-table` — 多通道溫度表格 OCR

辨識多探頭溫度計的表格顯示面板，支援指定讀取位置（row/col）與表格尺寸。

**額外 Request 欄位（form-data）**

| 欄位 | 類型 | 預設值 | 說明 |
|---|---|---|---|
| `input_coords` | string | `"1,1"` | 要讀取的儲存格位置，格式 `"[row,col]"` 或 `"row,col"`（1-based） |
| `table_size` | string | `"2,2"` | 表格尺寸，格式 `"[rows,cols]"` 或 `"rows,cols"` |

**回應欄位**

| 欄位 | 說明 |
|---|---|
| `result` | Result code |
| `pred_text` | 指定儲存格的辨識文字 |
| `diag_img` | 診斷圖（include_diag=true） |

**curl 範例**

```bash
# 基本辨識（讀取 [1,1]，2x2 表格）
curl -X POST http://localhost:8000/api/v1/inspect \
  -H "X-API-KEY: your-api-key" \
  -H "X-Inspection-Name: ocr/meter-table" \
  -F "image=@/path/to/image.png"

# 指定儲存格與表格尺寸
curl -X POST http://localhost:8000/api/v1/inspect \
  -H "X-API-KEY: your-api-key" \
  -H "X-Inspection-Name: ocr/meter-table" \
  -F "image=@/path/to/image.png" \
  -F "input_coords=[1,2]" \
  -F "table_size=[2,4]"
```

> `input_coords` 超出實際偵測結果範圍時，回傳 `result=2`（DETECTION_FAILED）而非錯誤。

支援後端：OpenVINO（CPU），TensorRT（GPU，需對應 `.engine` 權重）

---

## 架構說明

```
HTTP Request
    │
    ▼
[middleware]  生成 request_id、記錄 inspection_name、計算回應時間
    │
    ▼
[POST /api/v1/inspect]
    │
    ├─ X-API-KEY 驗證 (deps.py)
    ├─ 影像解碼 (OpenCV)
    │
    ▼
[InspectionManager]  單例，asyncio.Lock 序列化
    │
    ├─ registry 查詢 → 取得 adapter class
    ├─ kwargs 驗證（adapter.accepted_kwargs()）→ 非法欄位回 422
    ├─ 若需切換：unload 舊 adapter → load 新 adapter
    │   └─ TRT 失敗時自動降級 OpenVINO
    │
    ▼
[Adapter.run()]
    ├─ 呼叫 submodule proc()
    ├─ 若有 permit_image → permit_lookup（FDA 資料庫）
    └─ 回傳 dict
    │
    ▼
[InspectResponse]  Pydantic 序列化
    │
    ▼
HTTP 200 JSON
```

**關鍵設計決策：**

- **單一 Adapter 駐留**：同時只載入一個模型，節省 GPU/CPU 記憶體，切換時自動 unload
- **自動降級**：TRT 初始化失敗時，自動改用 OpenVINO，不中斷服務
- **欄位驗證由 Adapter 自聲明**：每個 adapter 透過 `accepted_kwargs()` 宣告接受的請求欄位，router 統一驗證，新增 adapter 不需修改 router
- **Submodule 隔離**：`keenchic/inspections/ocr/` 為 git submodule，gateway 只透過 adapter 呼叫，不直接修改
- **結構化日誌**：每個請求綁定 `request_id`，便於追蹤
- **FDA 許可證資料預載快取**：`permit_lookup` 模組在首次 import 時從 FDA 開放資料平台下載完整許可證清單並快取於記憶體。後續 API request 的 pcode 查詢皆為記憶體內搜尋，不再對外發送請求。啟動時下載失敗會在首次查詢時重試。若 FDA 端資料有更新，需重啟服務才能取得最新資料。

---

## Wheel 打包（Jetson 部署）

`build_wheel.py` 負責在 Jetson Orin（aarch64）上將 Python 原始碼編譯成 Cython `.so` 並打包成 `.whl`，包含模型權重。打包資訊由各算法的 `*.build.toml` descriptor 驅動，**新增算法不需修改 `build_wheel.py`**。

### 前置需求

在 Jetson 上執行前需安裝 build 工具：

```bash
pip install cython setuptools wheel numpy
```

### 基本用法

```bash
# 列出所有可打包的算法
python3 build_wheel.py --list

# 打包全部算法（預設）
python3 build_wheel.py

# 打包指定算法（可重複 -a）
python3 build_wheel.py -a ocr/datecode-num
python3 build_wheel.py -a ocr/datecode-num -a ocr/pill-count
```

### 產出 wheel 命名規則

| 打包範圍 | wheel 檔名 |
|---|---|
| 全部算法 | `keenchic_api_gateway-0.1.0-cp312-cp312-linux_aarch64.whl` |
| 指定算法子集 | `keenchic_api_gateway-0.1.0+ocr_datecode_num-...-linux_aarch64.whl` |

子集 build 使用 PEP 440 local version tag 標識所含算法，避免與完整 wheel 衝突。後裝的 wheel 會取代先裝的，無法同時安裝多個版本。

### Wheel 內容

每個 wheel 固定包含 **core**（FastAPI app、InspectionManager、registry、schemas 等）加上**所選算法**的：

- Cython 編譯的 `.so`（adapter + submodule 模組）
- 模型權重（`*/weights/*`）

### Descriptor 格式（`*.build.toml`）

每個算法在 `keenchic/inspections/adapters/ocr/` 下有一個同名的 `.build.toml`：

```toml
inspection_name = "ocr/datecode-num"      # X-Inspection-Name

[adapter]
source = "keenchic/inspections/adapters/ocr/datecode_num.py"
cython = true   # false 則以 .py 原始碼保留（不 Cython 編譯）

[[submodule]]
dir = "keenchic/inspections/ocr/datecode_num_st"   # submodule 子目錄

# dotted：adapter 用 `from datecode_num_st.xxx import ...` 的模組
# 從 parent dir（ocr/）編譯，.so 放在 datecode_num_st/ 內
dotted = [
    { name = "datecode_num_st.model_detect_openvino", src = "model_detect_openvino.py" },
    { name = "datecode_num_st.model_detect_trt",      src = "model_detect_trt.py"      },
    { name = "datecode_num_st.procd_date",             src = "procd_date.py"             },
]

# bare：submodule 內部裸 `import xxx` 的模組
# 從 submodule dir 本身編譯，module 名為裸名
bare = [
    { name = "utils", src = "utils.py" },
]

weights_subdir = "weights"   # 相對 dir，打包進 wheel 的 package_data
```

---

## 新增 Adapter

新增一個辨識算法需要以下四個步驟，**不需修改 `build_wheel.py` 或 router**。

### 步驟一：建立 Adapter

在 `keenchic/inspections/adapters/ocr/` 建立新檔案，繼承 `InspectionAdapter`：

```python
# keenchic/inspections/adapters/ocr/my_feature.py
from keenchic.inspections.base import InspectionAdapter
from keenchic.inspections.result_codes import InspectionResultCode

class MyFeatureAdapter(InspectionAdapter):

    @classmethod
    def accepted_kwargs(cls) -> set[str]:
        # 宣告此 adapter 接受哪些 request 欄位（router 據此驗證，多傳回 422）
        return {"include_diag", "my_custom_param"}

    def load_models(self, backend: str) -> None: ...
    def unload_models(self) -> None: ...
    def run(self, image, **kwargs) -> dict:
        result = ...  # 呼叫 submodule proc()
        return {
            "result": int(result.get("result", InspectionResultCode.DETECTION_FAILED)),
        }
```

> `accepted_kwargs()` 預設回傳 `{"include_diag"}`，不需額外欄位時可省略覆寫。

### 步驟二：註冊到 Registry

在 `keenchic/inspections/registry.py` 的 `_ADAPTER_ENTRIES` 加一行：

```python
("ocr/my-feature", "keenchic.inspections.adapters.ocr.my_feature", "MyFeatureAdapter"),
```

### 步驟三：新增 Build Descriptor

在同目錄新增 `my_feature.build.toml`（`build_wheel.py` 自動 discover）：

```toml
inspection_name = "ocr/my-feature"

[adapter]
source = "keenchic/inspections/adapters/ocr/my_feature.py"
cython = true

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

建立後執行 `python3 build_wheel.py --list` 確認新算法已被 discover。

### 步驟四：更新回應 Schema（選用）

若有新的回應欄位，更新 `keenchic/schemas/response.py`。

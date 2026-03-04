## ADDED Requirements

### Requirement: v1 單圖辨識（日期碼 OCR）
`DatecodeNumAdapter.run()` SHALL 接受一張圖片（`image: np.ndarray`）及可選參數 `YMD_option`（1=日/月/年，2=月/日/年，預設 1）、`include_diag`（bool），並呼叫 `datecode_num_st` 的 `proc()` 回傳辨識結果。`proc()` 的 `debug` 參數固定傳 `False`，不對外暴露。

#### Scenario: 成功辨識日期碼
- **WHEN** 傳入一張含有效日期碼的圖片
- **THEN** 回傳 dict 包含 `result=0`、非空的 `pred_text`、格式化的 `YMD`

#### Scenario: 辨識失敗（無法解析日期）
- **WHEN** 傳入一張無法辨識日期的圖片
- **THEN** 回傳 dict 包含 `result` 非 0、`pred_text` 為空字串，不得拋出例外

#### Scenario: include_diag=True 時包含診斷圖
- **WHEN** 呼叫時傳入 `include_diag=True`
- **THEN** 回傳 dict 的 `diag_img` 欄位包含 base64 編碼的 PNG 字串

### Requirement: v2 雙圖辨識（日期碼 + 許可證）
當請求同時提供 `date_image` 與 `permit_image` 兩張圖片時，adapter SHALL 同時辨識日期碼與許可證號碼（pcode），並呼叫 `permit_lookup.get_product_by_pcode(pcode)` 查詢產品名稱。

#### Scenario: v2 成功辨識並查詢產品名稱
- **WHEN** 傳入有效的 `date_image` 與 `permit_image`，且 pcode 存在於 FDA 資料庫
- **THEN** 回傳 dict 包含 `pname_en`、`pname_zh` 非空字串

#### Scenario: v2 pcode 查詢無結果
- **WHEN** 辨識出 pcode 但 FDA 資料庫中無對應記錄
- **THEN** 回傳 dict 的 `pname_en`、`pname_zh` 為 `null`，`result` 仍反映辨識結果

### Requirement: 模型動態載入與卸載
`load_models(backend)` SHALL 根據 `backend` 參數（`"openvino"` 或 `"trt"`）載入對應的 smp、pcode、yolo 等模型；`unload_models()` SHALL 釋放所有已載入的模型物件並設為 `None`，釋放記憶體。

#### Scenario: 首次載入（冷啟動）
- **WHEN** 呼叫 `load_models("openvino")`
- **THEN** 3 個模型物件（smp, smp_pcode, yolo12）全部載入完成，無例外

#### Scenario: 卸載後再載入（切換後重建）
- **WHEN** 先呼叫 `unload_models()` 再呼叫 `load_models("openvino")`
- **THEN** 模型物件重新載入，`run()` 可正常執行

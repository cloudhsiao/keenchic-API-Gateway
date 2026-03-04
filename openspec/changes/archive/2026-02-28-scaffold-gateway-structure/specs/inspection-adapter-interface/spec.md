## ADDED Requirements

### Requirement: InspectionAdapter ABC 定義統一介面
系統 SHALL 提供 `InspectionAdapter` 抽象基底類別（ABC），定義以下抽象方法：`load_models(backend: str) -> None`、`unload_models() -> None`、`run(image: np.ndarray, **kwargs) -> dict`。所有 adapter 實作 SHALL 繼承此 ABC。

#### Scenario: 子類別正確實作所有抽象方法
- **WHEN** 一個新 adapter class 繼承 `InspectionAdapter` 並實作所有抽象方法
- **THEN** 該 class 可被正常實例化

#### Scenario: 子類別未實作抽象方法
- **WHEN** 一個 adapter class 繼承 `InspectionAdapter` 但遺漏部分抽象方法實作
- **THEN** Python 在實例化時拋出 `TypeError`

### Requirement: Registry 映射 inspection name 到 adapter class
系統 SHALL 維護一個 registry（dict），將 inspection name 字串（如 `"ocr/datecode-num"`）映射到對應的 adapter class。`InspectionManager` SHALL 使用此 registry 來實例化 adapter。新增 inspection 模組時，MUST 只需修改 registry，不得修改框架核心程式碼。

#### Scenario: 查詢已登錄的 inspection name
- **WHEN** 以 `"ocr/datecode-num"` 查詢 registry
- **THEN** 回傳 `DatecodeNumAdapter` class（未實例化）

#### Scenario: 查詢不存在的 inspection name
- **WHEN** 以 `"ocr/unknown"` 查詢 registry
- **THEN** 回傳 `None` 或拋出 `KeyError`，不得靜默失敗

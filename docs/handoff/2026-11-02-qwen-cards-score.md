# Bàn giao: thẻ S cho qwen, tính điểm của spike khung (QW-S1, QW-S2)

Ngày soạn: 2026-11-02. Issue #135 (AG-Q1). Working model: `qwen2.5-coder:14b` + sổ kinh nghiệm L1b. Quy tắc ADR-004 / Roadmap 1.7: qwen chỉ nhận thẻ S có test chặt.

## Bối cảnh

`spikes/2a1-framework/score.py` mới in số đo thô. Chuẩn hoá 0-10 và quy tắc quyết định ([`docs/specs/framework-spike.md`](specs/framework-spike.md) mục 4 và 5) còn để cho báo cáo F5 làm tay. Hai thẻ dưới đây giao phần tính toán thuần này cho qwen, vào module mới `spikes/2a1-framework/common/scoring.py`. Mỗi thẻ một hàm, thuật toán ghi từng bước, test đóng băng.

## Mục tiêu

1. `common.scoring.normalise` (QW-S1) và `common.scoring.decide` (QW-S2) xanh trên test đóng băng.
2. Không đổi `score.py`: nối hai hàm vào báo cáo là việc của Claude khi review.

## Phạm vi

Trong: `spikes/2a1-framework/common/scoring.py` (mới), hai file test.
Ngoài: `score.py`, `run.py`, `variants/`, mọi dependency mới. Hàm thuần, không đọc file, không in.

## Chuẩn bị sẵn

Thư mục [`docs/handoff/prep/2026-11-02-qwen-score/`](prep/2026-11-02-qwen-score/):

| File | Việc |
| --- | --- |
| `test_scoring_normalise.py` | 16 test đóng băng của QW-S1 |
| `test_scoring_decide.py` | 19 test đóng băng của QW-S2 |
| `reference_scoring.py` | Bản tham chiếu của Claude, xanh cả 35 test; **không** đưa vào sổ L1b làm ví dụ |
| `conftest.py` | Chỉ trong thư mục này: đăng ký `reference_scoring.py` thành `common.scoring` |

Chạy test với bản tham chiếu (từ gốc repo):

```powershell
uv run pytest docs/handoff/prep/2026-11-02-qwen-score -q
```

Chạy cùng hai file test, không sửa, với `common/scoring.py` thật của qwen (từ `spikes/2a1-framework`; `--noconftest` tắt conftest tham chiếu, `python -m` đưa thư mục hiện tại vào đường dẫn để `common` import được):

```powershell
cd spikes/2a1-framework
uv run python -m pytest ../../docs/handoff/prep/2026-11-02-qwen-score/test_scoring_normalise.py ../../docs/handoff/prep/2026-11-02-qwen-score/test_scoring_decide.py --noconftest -q -p no:cacheprovider
```

Khi nhận thẻ, hai file test được chép nguyên văn vào `spikes/2a1-framework/tests/` (đóng băng) trước khi qwen chạy; lệnh trong từng thẻ dưới đây dùng vị trí đó.

---

## Thẻ QW-S1: `normalise`

- Model: `qwen2.5-coder:14b` + L1b
- Hạng: S (một hàm, thuật toán ghi sẵn)
- Base: nhánh hiện tại; thẻ không phụ thuộc QW-S2

### Việc cần làm

Tạo `spikes/2a1-framework/common/scoring.py` với đúng một hàm công khai:

```python
def normalise(raw: dict[str, dict[str, float]], better: dict[str, str]) -> dict[str, dict[str, float]]:
```

- `raw`: tên số đo (`"S1"`) -> tên biến thể (`"plain"`) -> giá trị.
- `better`: tên số đo -> `"fewer"` (giá trị nhỏ hơn tốt hơn) hoặc `"higher"` (giá trị lớn hơn tốt hơn).
- Trả về cùng hình dạng, giá trị là điểm `float` từ 0 đến 10.

Hằng số viết sẵn: `BETTER = ("fewer", "higher")`.

### Các bước (làm đúng thứ tự)

1. Với mỗi `measure` trong `raw`: nếu `measure` không có trong `better`, `raise ValueError`. Nếu `better[measure]` không nằm trong `BETTER` (so khớp chính xác, `"FEWER"` hay `"lower"` đều sai), `raise ValueError`. Kiểm tra này chạy cho **mọi** số đo trước khi tính bất cứ điểm nào, kể cả khi các giá trị bằng nhau.
2. Bỏ qua khoá trong `better` mà `raw` không có.
3. Với mỗi `measure`, đặt `values = raw[measure]`. Nếu `values` rỗng, bỏ số đo đó khỏi kết quả.
4. Tính `best` và `worst`: với `"fewer"`, `best = min(values.values())`, `worst = max(...)`; với `"higher"`, `best = max(...)`, `worst = min(...)`.
5. Nếu `best == worst` (một biến thể, hoặc tất cả bằng nhau): mọi biến thể được `10.0`.
6. Ngược lại, điểm của biến thể là `10.0 * (value - worst) / (best - worst)`. Công thức này đúng cho cả hai chiều (biến thể tốt nhất được 10, tệ nhất được 0).
7. Không sửa `raw` và `better`. Kết quả là dict mới, giá trị luôn là `float`.

### Ví dụ

| `raw` | `better` | Kết quả |
| --- | --- | --- |
| `{"S1": {"a": 100, "b": 60, "c": 140}}` | `{"S1": "fewer"}` | `{"S1": {"a": 5.0, "b": 10.0, "c": 0.0}}` |
| `{"X": {"a": 0, "b": 1, "c": 4}}` | `{"X": "higher"}` | `{"X": {"a": 0.0, "b": 2.5, "c": 10.0}}` |
| `{"S1": {"a": 7, "b": 7}}` | `{"S1": "fewer"}` | `{"S1": {"a": 10.0, "b": 10.0}}` |

### Trường hợp biên (đều có test)

Một biến thể -> 10; tất cả bằng nhau -> 10 (cả hai chiều); hai biến thể cùng tốt nhất; giá trị âm và số thực; nhiều số đo độc lập với chiều riêng; `better` có khoá thừa; `raw` rỗng -> `{}`; `better` sai (`"lower"`, `"FEWER"`) -> `ValueError` kể cả khi giá trị bằng nhau; số đo không có trong `better` -> `ValueError`; không sửa đối số.

### Được sửa

Chỉ `spikes/2a1-framework/common/scoring.py` (mới). Test đóng băng: `spikes/2a1-framework/tests/test_scoring_normalise.py`.

### Xong khi

- Lệnh dưới xanh cả 16 test, và `uv run ruff check .` + `uv run ruff format --check .` sạch.
- `git diff --stat` chỉ liệt kê file được phép.

```powershell
cd spikes/2a1-framework
uv run python -m pytest tests/test_scoring_normalise.py -q -p no:cacheprovider
```

---

## Thẻ QW-S2: `decide`

- Model: `qwen2.5-coder:14b` + L1b
- Hạng: S (một hàm, quy tắc ghi sẵn)
- Base: nhánh hiện tại; thẻ không phụ thuộc QW-S1 (cả hai ghi `common/scoring.py`, mỗi thẻ chỉ chứa hàm của mình; Claude ghép khi review, việc ghép không tính là `claude_fixes`)

### Việc cần làm

Thêm vào `spikes/2a1-framework/common/scoring.py` đúng một hàm công khai:

```python
def decide(
    totals: dict[str, float],
    s1_lines: dict[str, int],
    plain_capability_lines: dict[str, int],
    packages: dict[str, int],
) -> str:
```

Trả về `"plain"`, `"pydanticai"` hoặc `"langgraph"`. Nó cài đặt đúng mục 5 của spec, các quy tắc 2 đến 4. Quy tắc 1 ("bỏ biến thể trượt mục 3") đã được người gọi làm: biến thể trượt **không có mặt** trong `totals`.

Tham số:

| Tham số | Kiểu | Ý nghĩa |
| --- | --- | --- |
| `totals` | `dict[str, float]` | Tổng điểm có trọng số 0-10 của từng biến thể còn lại. Phải có `"plain"`; `"pydanticai"` và `"langgraph"` có thể vắng |
| `s1_lines` | `dict[str, int]` | S1: số dòng orchestration của từng biến thể (có khoá cho mọi biến thể trong `totals`) |
| `plain_capability_lines` | `dict[str, int]` | Với mỗi framework: số dòng `plain` phải viết để có một năng lực mà framework đó cung cấp sẵn (lấy số lớn nhất nếu có nhiều). Framework vắng khoá = không có năng lực nào được nêu = 0 |
| `packages` | `dict[str, int]` | Số runtime package mới của từng biến thể (có khoá cho mọi framework trong `totals`) |

Hằng số viết sẵn: `FRAMEWORKS = ("pydanticai", "langgraph")`, `MIN_GAIN = 1.5`, `MIN_S1_CUT_PERCENT = 30`, `CAPABILITY_LINES = 150`, `EPSILON = 1e-9`.

### Quy tắc trong spec (nguyên văn, mục 5)

> 2. A framework (`pydanticai` or `langgraph`) is chosen over `plain` only if **both**: its total score is at least 1.5 points higher, and S1 is at least 30 % fewer lines or it provides a capability that `plain` needed more than 150 lines to build (named in the report).
> 3. Otherwise the result is "no framework": the `plain` code becomes the base for the Phase 2 orchestration, and the result ADR amends ADR-004 ("pick one" becomes "pick one or none").
> 4. Between the two frameworks, the higher total score wins; a tie goes to fewer runtime packages.

### Các bước (làm đúng thứ tự)

1. Nếu `"plain"` không có trong `totals`, `raise ValueError`.
2. `candidates = []`. Với mỗi `name` trong `FRAMEWORKS` mà `name in totals`, kiểm tra quy tắc 2 (bước 3 đến 5); nếu đạt, thêm vào `candidates`.
3. Điều kiện điểm: `totals[name] - totals["plain"] >= MIN_GAIN - EPSILON`. (`EPSILON` để `4.1 - 2.6` kiểu `1.4999999999999996` vẫn tính là đủ 1.5.) Không đạt thì loại `name`, cả khi điều kiện kia thoả.
4. Điều kiện S1 (quy tắc 2, vế đầu): `plain = s1_lines["plain"]`, `fw = s1_lines[name]`; đạt khi `plain > 0` và `(plain - fw) * 100 >= MIN_S1_CUT_PERCENT * plain` (so nguyên, không dùng số thực; đúng 30 % vẫn đạt, 29 % không). `plain == 0` thì vế này không bao giờ đạt.
5. Điều kiện năng lực (quy tắc 2, vế sau): đạt khi `plain_capability_lines.get(name, 0) > CAPABILITY_LINES` (nghiêm ngặt: đúng 150 dòng không đạt; chỉ tính cho chính framework `name`). Quy tắc 2 yêu cầu **cả** điều kiện điểm (bước 3) **và** (S1 hoặc năng lực) (bước 4 hoặc 5).
6. Nếu `candidates` rỗng: trả `"plain"` (quy tắc 3).
7. Quy tắc 4 chỉ xét trong `candidates` (framework không đạt quy tắc 2 không được tranh, dù điểm cao hơn). `top = max(totals[n] for n in candidates)`; `leaders = [n for n in candidates if top - totals[n] <= EPSILON]`.
8. Trả về phần tử của `leaders` có `packages[n]` nhỏ nhất (`min(leaders, key=...)`). Hoà cả số package thì lấy phần tử đứng trước theo thứ tự `FRAMEWORKS` (spec không nói; `min` giữ phần tử đầu).

### Ví dụ

| `totals` | `s1_lines` | `plain_capability_lines` | Kết quả |
| --- | --- | --- | --- |
| `plain 5.0, pydanticai 7.0` | `plain 100, pydanticai 60` | `{}` | `pydanticai` |
| `plain 5.0, pydanticai 9.0` | `plain 100, pydanticai 71` | `{}` | `plain` (S1 chỉ ít hơn 29 %) |
| `plain 5.0, langgraph 7.0` | `plain 100, langgraph 100` | `langgraph 151` | `langgraph` |
| `plain 5.0, langgraph 6.4` | `plain 100, langgraph 10` | `langgraph 400` | `plain` (thiếu 1.5 điểm) |

### Trường hợp biên (đều có test)

Chỉ có `plain` -> `plain`; đúng 1.5 điểm và đúng 30 % -> framework; nhiễu số thực quanh 1.5; 29 % -> `plain`; framework nhiều dòng hơn `plain`; năng lực 151 đạt, 150 không; năng lực của framework khác không tính; năng lực không thay điều kiện điểm; S1 cắt mạnh không thay điều kiện điểm; hai framework đều đạt -> điểm cao hơn thắng; hoà điểm -> ít package hơn; framework điểm cao hơn nhưng không đạt quy tắc 2 thua framework đạt; biến thể trượt (vắng khoá) bị bỏ; thiếu `plain` -> `ValueError`; `plain` có S1 = 0 không chia cho 0.

### Được sửa

Chỉ `spikes/2a1-framework/common/scoring.py`. Test đóng băng: `spikes/2a1-framework/tests/test_scoring_decide.py`.

### Xong khi

- Lệnh dưới xanh cả 19 test, và `uv run ruff check .` + `uv run ruff format --check .` sạch.
- `git diff --stat` chỉ liệt kê file được phép.

```powershell
cd spikes/2a1-framework
uv run python -m pytest tests/test_scoring_decide.py -q -p no:cacheprovider
```

---

## Điểm spec mục 5 chưa rõ, bản tham chiếu chọn như sau

| # | Điểm chưa rõ | Cách chọn trong thẻ |
| --- | --- | --- |
| 1 | "capability that `plain` needed more than 150 lines" tính theo framework nào, một hay nhiều | Theo từng framework, lấy số dòng lớn nhất; vắng = 0 |
| 2 | "at least 30 % fewer lines": 30 % của số dòng `plain` | `(plain - fw) * 100 >= 30 * plain` bằng số nguyên |
| 3 | Quy tắc 4 so cả hai framework hay chỉ những framework đã đạt quy tắc 2 | Chỉ những framework đạt quy tắc 2 |
| 4 | Hoà cả điểm lẫn số package | Spec không nói; lấy `pydanticai` (đứng trước trong `FRAMEWORKS`), chưa có test cố định hành vi này |
| 5 | Sai số số thực ở ngưỡng 1.5 và hoà điểm | Dùng `EPSILON = 1e-9` |
| 6 | `plain` bị loại ở mục 3 | Spec không nói; hàm báo `ValueError`, người gọi phải xử lý ca đó |

Cần Hùng xác nhận các dòng 1, 3, 4 và 6 trước khi báo cáo F5 dùng hàm này.

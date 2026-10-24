# Bàn giao: Phase 2a.1, spike agent framework (24/10)

Spec và tiêu chí loại (viết trước khi có code, không sửa sau lần chạy thật đầu tiên): [`docs/specs/framework-spike.md`](../specs/framework-spike.md). Dữ liệu chuẩn bị sẵn: [`prep/2026-10-24-framework-spike/`](prep/2026-10-24-framework-spike/). Nếu code trên `main`, ADR hay file này mâu thuẫn nhau, dừng lại và hỏi.

## Bối cảnh

- ADR-004: Phase 0–1 không dùng agent framework; đầu Phase 2 spike PydanticAI và LangGraph trên đúng một luồng Planner → Worker → Reviewer rồi chọn **một**. Roadmap Phase 2 và Blueprint §10 ghi giống vậy.
- ADR-021 (Accepted 23/10, mới hơn ADR-004): tự xây trước, phái sinh từ mã permissive thứ hai, dùng sản phẩm có sẵn sau cùng; giảm tỷ trọng phụ thuộc bên thứ ba. ADR-006 đã sửa theo: EventBus tự xây (in-process + hàng đợi SQLite), NATS chỉ khi nhiều máy. LFMAP Flows (TOML trên jobs + EventBus) thay n8n dần.
- ADR-022 (Proposed): tầng Leading Agent local giữa Claude và Working Agent; lộ trình B0 → shadow mode trong 2a.1 → filter mode khi đạt ngưỡng. B0 (23/10, `docs/research/2026-10-23-b0-benchmark.md`): chỉ `qwen3.8:27b` dùng được làm Leading (7/7 verdict, 2/3 seed, 0 trích dẫn bịa), chậm 200–466 s mỗi review.
- `qwen-loop` (Python thuần, ngoài sản phẩm) đã chạy Working tier từ 21/10 và là bằng chứng rằng luồng này viết được không cần framework.

## Mục tiêu

1. Có dữ liệu đo để ra **một ADR** (đề xuất số ADR-023) chọn PydanticAI, LangGraph, hoặc không framework, theo luật quyết định viết sẵn ở spec §5.
2. Chạy Leading Agent ở **shadow mode** trên cùng luồng, đo các ngưỡng ADR-022 (spec §6). Claude vẫn review mọi thứ.

## Mâu thuẫn với tài liệu đã chốt (cần Hùng xem)

| # | Mâu thuẫn | Cách xử lý trong handoff này |
| --- | --- | --- |
| M1 | ADR-004, Roadmap, Blueprint §10 nói "chọn **một** trong hai"; ADR-021 nói tự xây trước. Chọn một framework mà không so với bản tự xây là trái ADR-021. | Thêm biến thể `plain` (Python thuần) làm mốc. Framework chỉ thắng khi vượt rõ mốc (spec §5). Nếu kết quả là "không framework", ADR-023 sửa ADR-004 thành "chọn một hoặc không". **Câu hỏi Q4 cho Hùng**; trong lúc chờ, làm theo khuyến nghị (thêm mốc tốn thêm khoảng nửa phiên Cloud, đảo ngược được). |
| M2 | LangGraph tự nó là một engine luồng có checkpoint, trùng vai với LFMAP Flows (ADR-021) và nguyên tắc "không thêm framework orchestration thứ hai". | Tiêu chí loại E6: framework chỉ được nằm **bên trong một bước** (gọi như một hàm từ job hoặc bước Flows), không có daemon, scheduler hay server riêng. |
| M3 | ADR-022 mới Proposed; ghi chú B6 của ADR-004 và Blueprint §4.4 giữ review ở cloud. | Shadow mode không mâu thuẫn: Claude review toàn bộ, báo cáo Leading chỉ để so. Filter mode vẫn cần ADR-022 Accepted, ngoài phạm vi. |
| M4 | ADR-022 đặt code tầng Leading trong `lfmap-tools` (ngoài repo, chỉ có trên DIEP-ANH, phiên Cloud không với tới). | Spike nằm trong repo lfmap ở `spikes/2a1-framework/`, project uv riêng, **không** là thành viên workspace, không vào bản phân phối. Claude tự quyết (đảo ngược được); sau ADR-023, phần được chọn chuyển đi, phần còn lại xoá. |

## Quyết định đã chốt (Claude, đảo ngược được)

| # | Quyết định | Phương án loại |
| --- | --- | --- |
| D1 | Ba biến thể trên cùng một luồng: `plain`, `pydanticai` (`pydantic-ai-slim[openai]==2.60.0`), `langgraph` (`langgraph==1.2.16`, `langchain-ollama==1.1.0`, `langgraph-checkpoint-sqlite==3.1.2`). Tất cả MIT (client `openai` Apache-2.0), bản mới nhất trên PyPI 24/10. | Chỉ so hai framework (trái ADR-021, M1); `pydantic-ai` đầy đủ (kéo logfire, nhiều SDK cloud) |
| D2 | Luồng: Plan → Work → Review → chờ duyệt, chạy **theo lô từng pha** để Ollama nạp mỗi model một lần mỗi pha; bước duyệt ghi trạng thái ra đĩa, **thoát process**, `resume` ở process mới (mô phỏng hàng đợi approvals ADR-018, không đụng hàng đợi thật). | Luồng sản phẩm email → tóm tắt (chưa có plugin `email`, không có đáp án đúng để chấm); xen kẽ từng card (đổi model mỗi card, chậm vài phút mỗi card) |
| D3 | Dữ liệu: replay gói K4–K7 (PR #26) có verdict đã biết, cộng ≥ 12 seed bug (đã có 8). Phần dùng chung (`common/`: model dữ liệu, prompt, gate, quote check, socket guard, đo đạc) không phụ thuộc framework; biến thể chỉ viết phần điều phối. | Gói việc mới chưa có đáp án (không chấm được); mỗi biến thể tự viết prompt (khác biệt do prompt, không do framework) |
| D4 | Model: Leading `qwen3.8:27b`, Working `qwen2.5-coder:14b`, temperature 0, `num_ctx` 16384, output theo JSON schema. Chế độ thinking theo kết quả B0b nếu đã chạy, không thì mặc định. | `gpt-oss:20b` (4/7 JSON hỏng ở B0); `qwen3-coder:30b` làm Leading (sai verdict 3/7) |
| D5 | Không gọi Claude hay API trả phí trong code spike. Phần "Claude review" của shadow mode là một phiên Claude Code đọc kết quả. | Gọi API Claude từ script (tốn phí, cần duyệt T3) |
| D6 | Mọi gói của spike ghim đúng bản trong `spikes/2a1-framework/uv.lock` riêng; `scripts/check_licenses.py` của workspace không đổi. Thêm một dòng vào `docs/PROVENANCE.md` (spike, Internal). | Thêm vào workspace (kéo framework vào lock chung trước khi có quyết định) |

## Phạm vi

Trong: thư mục `spikes/2a1-framework/` (code, test, `uv.lock` riêng, kết quả chạy), báo cáo `docs/research/` và bản nháp ADR-023, dòng `docs/PROVENANCE.md`, CHANGELOG gốc (mục `[Unreleased]`, một dòng).
Ngoài: mọi thay đổi trong `packages/` và `plugins/`; Agent Router (2a.2); EventBus (2a.3); hàng đợi approvals thật; filter mode; gọi Claude/API trả phí; CI chạy test của spike (ruff gốc vẫn lint thư mục này).

## Thiết kế

Chi tiết ở spec. Tóm tắt bố cục:

```text
spikes/2a1-framework/
  pyproject.toml, uv.lock        # project riêng; dependency-groups: pydanticai, langgraph
  common/                        # models.py, prompts.py, gates.py, quote.py, ollama.py, guard.py, metrics.py, fake.py
  variants/plain/  variants/pydanticai/  variants/langgraph/   # mỗi biến thể: flow.py (+ state)
  cases/                         # chép từ docs/handoff/prep/2026-10-24-framework-spike/cases + seed mới
  tests/test_common.py           # gate, quote check, guard
  tests/test_variant_contract.py # tham số hoá theo biến thể, FakeModel, có resume ở subprocess
  run.py                         # run --variant X --case|--package ...; resume <run_id> --approve|--reject
  score.py                       # đọc results/, in bảng E1–E8, S1–S7, spec §6
  results/<ngày>/                # kết quả chạy thật trên DIEP-ANH (commit được: chỉ là code lfmap và JSON)
```

Hợp đồng biến thể: `run_flow(package, *, models, state_dir, replay_cards=None) -> RunResult` và `resume(run_id, *, approve: bool, state_dir) -> RunResult`. Cùng một bộ contract test cho cả ba; biến thể nào không qua thì bị loại theo E4/E5.

## Danh sách task

| # | Task | Môi trường | Tiêu chí hoàn thành | Dự kiến |
| --- | --- | --- | --- | --- |
| F0 | Khung spike: project uv riêng, `common/`, `FakeModel`, socket guard, contract test (chưa biến thể nào qua), chép cases, thêm ≥ 4 seed theo spec §7, `run.py`/`score.py` khung, xác định commit gốc của K4–K7, dòng PROVENANCE | Cloud (Linux, không cần GPU) | `pytest` của spike xanh cho `common/`; contract test chạy và đỏ đúng chỗ; ruff gốc sạch; PR merge | 27/10 |
| F1 | Biến thể `plain` | Cloud | contract test xanh; socket guard không bắt gì | 28/10 |
| F2 | Biến thể `pydanticai` | Cloud (song song F1) | như F1, kèm số gói và dung lượng (E8, S2) | 28–29/10 |
| F3 | Biến thể `langgraph` | Cloud (song song F1) | như F2 | 28–29/10 |
| F4 | Chạy thật: 3 biến thể × 19+ case (replay) + 1 lần Plan; ghi `results/` | Local DIEP-ANH qua Remote Control (GPU, Ollama), chạy đêm (10 review ≈ 40–75 phút mỗi biến thể) | `score.py` in đủ E1–E8, S1–S7 và spec §6 | 30–31/10 |
| F5 | Shadow mode: Claude review từng case **trước khi** đọc báo cáo Leading, rồi so; viết `docs/research/2026-11-0x-framework-spike.md` + bản nháp ADR-023 theo luật spec §5 | Cloud (phiên Claude Code) | báo cáo + ADR draft trong PR; danh sách sửa tài liệu dự án trong thân PR | 01–02/11 |

Không giao qwen: code điều phối và guard là phần cần thiết kế (card M), theo B6.

## Chuẩn bị sẵn

- Spec `docs/specs/framework-spike.md`: tiêu chí loại E1–E8, điểm S1–S7, luật quyết định, ngưỡng shadow.
- `docs/handoff/prep/2026-10-24-framework-spike/cases/`: 15 case của B0/B0b (card, diff, `expected.json`, log K5; 8 seed) và `bench_b0.py` (script B0: gọi Ollama, quote check, chấm seed) để dùng lại logic.
- Phiên bản và giấy phép các gói ở D1 đã tra PyPI 24/10. Lưu ý cho F2/F3: `langchain-core` kéo `langsmith` (tracing tắt khi không đặt biến môi trường, E2 sẽ kiểm); `pydantic-ai-slim` kéo `genai-prices`, `opentelemetry-api`, `logfire-api` (không gửi gì khi chưa cấu hình, E2 kiểm).
- DIEP-ANH: Ollama đã có `qwen3.8:27b` và `qwen2.5-coder:14b`. Thư mục `D:\Development\lfmap` nằm trong quyền đã cấp.
- **Hùng tự chạy một lần trước F4** (lệnh tải gói từ PyPI, bộ phân loại trên máy chặn Claude): `cd D:\Development\lfmap; git pull; cd spikes\2a1-framework; uv sync --all-groups`.

## Rủi ro

| Rủi ro | Giảm thiểu |
| --- | --- |
| Framework kéo nhiều phụ thuộc, khó gỡ sau này | E1, E8 và S2 đo trước; framework không vào workspace cho đến ADR-023 |
| Kết quả nghiêng vì prompt khác nhau giữa biến thể | prompt, gate, model dùng chung trong `common/` |
| Mẫu nhỏ (19+ case, 12 seed) | ghi rõ giới hạn trong báo cáo; điểm framework dựa chủ yếu vào code (S1–S7), không vào chất lượng model |
| `qwen3.8:27b` chậm, DIEP-ANH mất điện hoặc mất mạng giữa chừng | chạy đêm, mỗi case độc lập, chạy lại từ `results/` |
| Hạn mức Claude tuần này ở mức cảnh báo (reset 28/10 18:00 VN) | F0 trước, F1–F3 sau reset; F2/F3 dời được mà không chặn F1 |
| Spike phình thành sản phẩm | chỉ trong `spikes/`, không sửa `packages/`/`plugins/` (spec §8) |

## Câu hỏi còn mở (gom vào danh sách quyết định cho Hùng)

- Q4 (từ M1): cho phép kết quả "không framework" và sửa ADR-004 thành "chọn một hoặc không"? Khuyến nghị: **có**.
- Q1–Q3 của bản nháp Phase 2 (tách 2a/2b, hộp thư cho `email`, case-study `lfmap-isomp`) không chặn 2a.1, nhưng 2a/2b quyết định thứ tự sau spike.

## Cập nhật tài liệu dự án (sau F5, ngoài repo)

- 03_Decisions_ADR: thêm ADR-023 (kết quả spike); nếu "không framework" thì sửa ADR-004; ghi chú tiến độ ADR-022 (số đo shadow).
- 05_Roadmap Phase 2: dòng "Spike PydanticAI vs LangGraph → ADR chọn một" sửa theo ADR-023.
- 01 Blueprint §10 (dòng Agent framework) và §13 mục 6.
- 04_License_Register: dòng cho framework được chọn (nếu có), trạng thái Ship.

## Prompt khởi động cho Claude Code

F0 (Cloud, repo `hungnp1999/lfmap`):

> Read `CLAUDE.md`, `docs/handoff/2026-10-24-phase2a-framework-spike.md` and `docs/specs/framework-spike.md`. Do task F0 only. Create `spikes/2a1-framework/` as a standalone uv project (not a workspace member) with dependency groups `pydanticai` and `langgraph` pinned exactly as in spec §1, the shared `common/` package, `FakeModel`, the socket guard, `tests/test_common.py` and `tests/test_variant_contract.py` (parametrised over the three variants; variants are stubs that raise `NotImplementedError`, so those tests fail as expected and are marked `xfail(strict=True)` until F1–F3). Copy the cases from the prep folder, add at least four seeded cases per spec §7, find the K4–K7 base commit from PR #26 and record it in `cases/README.md`. Add the `docs/PROVENANCE.md` row and one CHANGELOG line. Do not touch `packages/` or `plugins/`. Root `ruff check .` and `ruff format --check .` must pass. Open a PR; it may be merged when CI and CodeQL are green.

F1/F2/F3 (Cloud, one session each, after F0 is merged):

> Read `CLAUDE.md`, the handoff and the spec. Do task F<n> only: implement `variants/<name>/` against the contract in the handoff ("Hợp đồng biến thể"), using only `common/` for prompts, gates and models. Remove the `xfail` for this variant; the contract test must pass offline with the socket guard on. Record S1, S3, S5 and (for frameworks) the package count and installed size in `variants/<name>/NOTES.md`. Do not change `common/`, the spec or other variants; if `common/` blocks you, stop and ask. Open a PR.

F4 (Local, Remote Control on DIEP-ANH, after Hùng ran `uv sync --all-groups`):

> In `D:\Development\lfmap\spikes\2a1-framework`, run `run.py` for each variant over every case in replay mode, then one Plan run on the K4–K7 package, with the models in handoff D4. Keep the socket guard on. Write results to `results/<date>/`, run `score.py`, commit on a branch and open a PR. Do not delete models or files outside this folder.

F5 (Cloud): see the task table; Claude reviews each case blind first, then compares with the Leading report.

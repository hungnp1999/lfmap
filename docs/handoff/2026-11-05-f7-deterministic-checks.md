# Bàn giao: F7 kiểm tra xác định cho các seed gate không thấy

- Ngày: 2026-11-05
- Issue: #154 (sau F6, PR #153). Lịch tuần: #156.
- Thiết kế: `docs/research/2026-11-05-f7-deterministic-checks.md`
- Chuẩn bị sẵn: `docs/handoff/prep/2026-11-05-f7/` (probe + test đóng băng)
- Người duyệt: anh Hùng, cổng 1 (chốt file bàn giao này và 3 quyết định ở mục "Câu hỏi mở"), khung 17:00 thứ Sáu 06/11

## Bối cảnh

Lần chạy lại shadow F6 (#153, chỉ `plain`) còn 8/19 case `ready` sai so với `expected.json`. Sáu case là seed mà gate xác định không thấy (`exists`, `swallow`, `count`, `order`, `unlink`, `sql`), thêm `K4-real` và `K7-real`. Leading review bỏ sót `exists`, `swallow`, `count` dù checklist S1, S2, S6 đã gọi tên. ADR-022 còn Proposed. Issue #154 cấm chỉnh prompt thêm: tìm kiểm tra xác định cho từng loại, không được thì ghi là giới hạn.

## Mục tiêu

- Thêm hai gate xác định `ruff_extra` và `probes` vào `spikes/2a1-framework`, chạy trước Leading review.
- Ma trận 19 case: 8 case đúng như thiết kế bị gate mới bắt, 11 case còn lại không bị gate mới báo.
- `score.py` báo thêm số seed do kiểm tra bắt, để so trực tiếp với F6.

## Quyết định đã chốt

1. **Hai kiểm tra, không hơn** (Claude, đảo ngược được): `ruff_extra` (S110 kể cả exception có kiểu, S112, S608) và `probes` (test ẩn theo module đích). Đã đo trên Cloud ngày 05/11 với workspace `018ffdf`: bắt đủ 6 seed và 2 case real, 0 báo nhầm.
   - Loại: luật AST "kiểm tra file trước `require_*`" (K4 ủy quyền kiểm tra quyền cho `MarkitdownTool.convert`, cần danh sách cho phép theo thẻ); luật AST `mkstemp` thiếu `unlink` (probe đã bắt, thêm thành phần không thêm kết quả); mutation probe (đo độ mạnh của test, không phải lỗi của diff); SIM105 (gợi ý `contextlib.suppress` vẫn nuốt lỗi).
2. Probe đã viết sẵn và đóng băng; Working Agent chỉ chép, không sửa.
3. Luật ruff mới chỉ trong spike. Đưa vào `ruff.toml` gốc là issue Backlog riêng.
4. `Package.checks = True` mặc định; `run.py --no-checks` để chạy lại kiểu F6.

## Phạm vi

Được sửa (chỉ các file này):

- `spikes/2a1-framework/common/checks.py` (mới)
- `spikes/2a1-framework/common/gates.py` (chỉ `run_gates`)
- `spikes/2a1-framework/common/models.py` (chỉ thêm `Package.checks`)
- `spikes/2a1-framework/run.py` (chỉ cờ `--no-checks`)
- `spikes/2a1-framework/score.py` (`checks_caught` và các cột mới)
- `spikes/2a1-framework/probes/` (mới, chép nguyên từ prep)
- `spikes/2a1-framework/tests/test_f7_checks.py` (mới, chép nguyên từ prep)
- `spikes/2a1-framework/cases/README.md` (một bảng "What the F7 checks see")
- `CHANGELOG.md` (một dòng `[Unreleased]` / Added)
- `docs/research/2026-11-05-f7-deterministic-checks.md` (mục kết quả cuối)

Không sửa: `cases/*/` (card, diff, expected), các variant, `packages/`, `ruff.toml` gốc, các test đã có.

## Thiết kế

Chi tiết trong ghi chú thiết kế mục 5–6. Tóm tắt API mà test đóng băng đòi:

```python
# common/checks.py
PROBES_DIR: Path  # spikes/2a1-framework/probes
PROBES: dict[str, list[str]]  # target path -> probe file names
CHECK_GATES = {"ruff_extra", "probes"}


def probes_for(target: str) -> list[Path]: ...
def run_checks(package: Package, card: Card) -> list[GateResult]: ...  # [] without workdir
# score.py
def checks_caught(attempt: Attempt) -> bool: ...
```

- `ruff_extra`: `[*package.ruff_cmd, "check", "--isolated", "--line-length", "120", "--select", "S110,S112,S608", "--config", "lint.flake8-bandit.check-typed-exception = true", card.target]`, chạy trong workdir qua `gates._run`.
- `probes`: chỉ khi `probes_for(card.target)` khác rỗng **và** `card.tests` khác rỗng. Chép từng probe vào thư mục của `card.tests[0]`, chạy `[*package.pytest_cmd, <đường dẫn tương đối của probe>]` trong workdir, xóa probe trong `finally`. Output bắt đầu bằng tên các file probe.
- `run_gates`: sau `pytest`, `if package.checks: gates += run_checks(package, card)`. Tránh import vòng (`checks` dùng `gates._run`): import trễ trong hàm hoặc `from common import gates`.
- Path an toàn: probe chỉ ghi trong `package.workdir` (workdir do người chạy đưa vào, không phải đầu vào của model); vẫn dùng `os.path.realpath` + `startswith` cho thư mục đích như `read_in`.

## Danh sách task

### Task [CC] F7-B: xây hai gate kiểm tra (Roadmap 2a.1, P2)

- Môi trường: Cloud (Claude Code, Sonnet). Lý do: không cần GPU, Office hay máy nhà; ma trận chạy được trên Linux.
- Blocked by: Hùng duyệt file này (cổng 1, 06/11 17:00).
- Nhánh: `feature/f7-checks` từ `main` mới nhất.
- Bước:
  1. Chép `docs/handoff/prep/2026-11-05-f7/probes/*.py` vào `spikes/2a1-framework/probes/`, `.../tests/test_f7_checks.py` vào `spikes/2a1-framework/tests/`. Không sửa nội dung.
  2. Viết `common/checks.py`, sửa `gates.py`, `models.py`, `run.py`, `score.py` theo mục Thiết kế.
  3. `cd spikes/2a1-framework && uv sync && uv run pytest -q tests` (toàn bộ test spike, kể cả 18 test F7 không cần workspace).
  4. Ma trận trên workspace thật: `git -C <lfmap> fetch --depth=1 origin 018ffdf316f8166da5039126a700a2d31d8bb14d`, `git worktree add --detach <ws> 018ffdf...`, `cd <ws> && uv sync`, rồi `LFMAP_F7_WORKDIR=<ws> LFMAP_F7_PYTEST="<ws>/.venv/bin/python -m pytest -q -p no:cacheprovider" uv run pytest -q tests/test_f7_checks.py` (37 test xanh, khoảng 1 phút). Xóa worktree sau đó.
  5. `ruff check .` và `ruff format --check .` ở gốc repo và trong spike.
  6. Thêm bảng vào `cases/README.md`, dòng CHANGELOG, mục "Result" cuối ghi chú thiết kế (ma trận thật, số test).
  7. PR `Closes #154`; chạy `/security-review` (task chạy subprocess); merge khi CI + CodeQL xanh.
- Test đóng băng: `docs/handoff/prep/2026-11-05-f7/tests/test_f7_checks.py` (đã chạy xanh 37/37 với bản phác thảo ở Cloud ngày 05/11), probe trong `.../probes/`.
- Tài nguyên: không.
- Cổng: review thường (không đổi ADR, không đổi chính sách).
- Tuyến dự phòng: nếu một probe đỏ sai trên Windows (khác đường dẫn hoặc `os.replace`), ghi lại và hỏi; không sửa probe.

### Task [PO] F7-R: chạy lại seed trên DIEP-ANH (chỉ khi Hùng chọn phương án B ở câu hỏi 2)

- Môi trường: Local DIEP-ANH, tài khoản `lfmap-agent`, Ollama, khoảng 2 giờ GPU, khung tối thứ Bảy 07/11.
- Blocked by: F7-B merge; preflight thứ Sáu 06/11.
- Lệnh: `run.py run --variant plain --case <seed> --workdir <worktree 018ffdf>` cho 6 seed + `K4-real` + `K7-real`, rồi `score.py`.

## Chuẩn bị sẵn

- `docs/handoff/prep/2026-11-05-f7/probes/test_probe_extract.py` (4 probe K4) và `test_probe_embed.py` (1 probe K7).
- `docs/handoff/prep/2026-11-05-f7/tests/test_f7_checks.py`: 18 test offline + 19 test ma trận (bỏ qua khi thiếu `LFMAP_F7_WORKDIR`).
- `docs/handoff/prep/2026-11-05-f7/ruff.toml`: cùng nhóm isort với spike để CI gốc xanh khi file nằm ở prep.
- Đã đo: ma trận 19 case khớp `CAUGHT` trong test; workspace `018ffdf` + `uv sync` chạy được trên Cloud.

## Rủi ro

- Probe viết sau khi xem đáp án: 6/6 là cận trên, không phải tỉ lệ bắt mù. Đã ghi trong ghi chú thiết kế.
- `count` là lỗ của thẻ K7 (thẻ không nói phải kiểm số vector). Probe đúng với `expected.json` nhưng đổ lỗi cho review là không công bằng.
- Probe chỉ có cho K4, K7. Thẻ mới (Plan run, 2a.2) không có probe trừ khi Planner viết.
- S608 có thể báo nhầm f-string chỉ chèn tên bảng hằng; khi đó `# noqa: S608` kèm lý do.

## Câu hỏi mở (gom vào danh sách quyết định cho Hùng)

1. Ngưỡng ADR-022 đo trên cả lớp review (gate + kiểm tra + Leading) hay chỉ Leading? Khuyến nghị: cả lớp (A).
2. Bỏ khung GPU tối thứ Bảy (ma trận chạy trên Cloud) hay giữ để xem Leading phản ứng với log kiểm tra đỏ? Khuyến nghị: bỏ (A).
3. Ghi `count` là lỗ của thẻ và thêm "kiểm hình dạng và số lượng phản hồi từ ngoài" vào checklist thẻ của Planner 2a.2? Khuyến nghị: có.

## Cập nhật tài liệu dự án

- ADR-022 (ghi chú tiến độ, ngoài repo): kết quả F7 và quyết định 1.
- Roadmap 2a.1: F7 xong khi F7-B merge.
- Không đổi License Register (không thêm dependency).

## Prompt khởi động

```text
Repo lfmap, task F7-B of issue #154. Read CLAUDE.md, then docs/handoff/2026-11-05-f7-deterministic-checks.md
(task F7-B, sections "Phạm vi" and "Thiết kế") and docs/research/2026-11-05-f7-deterministic-checks.md
(sections 5-6). Do steps 1-7 of task F7-B exactly and change only the files listed under "Phạm vi".
The probes and tests/test_f7_checks.py in docs/handoff/prep/2026-11-05-f7/ are frozen tests: copy them
unchanged; if a test looks wrong, stop and ask. Branch feature/f7-checks from up-to-date main.
Every commit ends with a Dev-Environment trailer (plus Claude-Session on Cloud). Run /security-review before merging.
Work and write in English. Final report: full spike pytest result, the 19-case matrix of step 4, PR link;
write only that final summary in Vietnamese.
```

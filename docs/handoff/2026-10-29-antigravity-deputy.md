# Bàn giao: Antigravity làm Deputy Agent trong giờ cao điểm

Ngày soạn: 2026-10-29. Nguồn: phương án của Hùng "LFMAP-antigravity-deputy-plan.md" (Google Doc, 2026-10-29), đối chiếu ADR, project instructions, quy tắc provenance và License Register. Chạy thử từ 2026-10-30, đánh giá lại sau 2–3 tuần.

## Bối cảnh

- Hạn mức tuần Claude Pro dùng hết khoảng 30 % trong chưa đầy 24 giờ sau lần reset gần nhất. Hùng có sẵn hạn mức Google Antigravity trong gói Google AI Plus và muốn dùng nó cho việc phụ thay vì nâng Max 5x ngay.
- Mô hình hiện tại (Hùng chốt 2026-10-22): Project (coordinator + thread) là Managing Agent, tự lên kế hoạch, review và merge; Claude Code Cloud/Local và qwen (local, thẻ S có test chặt, ADR-004) là Working Agent.
- Antigravity là IDE agent của Google (bản desktop, model Gemini). Thông tin tra cứu ngày 2026-10-29 (trang `antigravity.google` không truy cập được từ Cloud, nên phần cấu hình cần đối chiếu lại trên UI):
  - Đọc quy tắc workspace từ `AGENTS.md` hoặc `GEMINI.md` ở gốc dự án và thư mục con, `.agents/rules/*.md` (cũ: `.agent/rules/`); quy tắc toàn cục ở `~/.gemini/`. Chưa có thứ tự ưu tiên chính thức giữa `GEMINI.md` và `AGENTS.md`, nên repo chỉ dùng `AGENTS.md`.
  - Quyền: danh sách Allow / Deny / Ask cho lệnh terminal, URL, MCP, file ngoài workspace; mặc định là Ask. Có báo cáo lỗi allow list mất sau khi khởi động lại; sandbox terminal chưa có trên Windows.
  - Dữ liệu: tài khoản cá nhân, khi bật "Enable Telemetry" thì Google ghi lại tương tác để đánh giá và cải thiện Antigravity và các model. Nhân viên Google nói tắt mục này là ngừng thu thập; điều khoản không ghi rõ "không dùng để huấn luyện". Chỉ truy cập qua Google Workspace hoặc GCP mới có cam kết không thu prompt, nội dung, phản hồi.
  - Bảo mật: 11/2025 PromptArmor chứng minh trang web chứa lệnh ẩn khiến agent đọc `.env` bằng `cat` rồi gửi ra ngoài qua browser agent (Google xếp là "known issue"); 01/2026 lỗ hổng RCE qua prompt injection, vá 28/02/2026.
  - Hạn mức: theo cửa sổ 5 giờ và trần tuần, không công bố con số; nhiều báo cáo bị khoá vài ngày. Không đặt việc trên đường găng cho Antigravity.

## Mục tiêu

1. Giảm 30–40 % hạn mức Claude dành cho việc không cần năng lực cao nhất.
2. Không lệch kiến trúc, không mất code, không vi phạm provenance hay quy tắc dữ liệu.
3. Có số liệu sau 2–3 tuần để quyết định: giữ mô hình, nạp credits theo tuần cao điểm, hay nâng Max 5x.

Tiêu chí hoàn thành của đợt chuẩn bị: PR tài liệu đã merge ở các repo; Antigravity cài và cấu hình trên DIEP-ANH; worktree cho task thử đã tạo; task thử AG-P1 qua review và merge.

## Quyết định đã chốt

| # | Quyết định | Lý do | Phương án đã loại |
|---|---|---|---|
| 1 | Antigravity là **Deputy Working Agent**, ngang Claude Code về tầng, hẹp hơn về phạm vi; không lên kế hoạch, không review, không merge | Quyết định và merge vẫn ở Project (Managing Agent) như governance 2026-10-22 | "Deputy Managing Agent" như bản gốc: tên gợi quyền điều phối mà Antigravity không có |
| 2 | Quy tắc cho Antigravity nằm trong `AGENTS.md` ở gốc repo; nội dung trỏ về `CLAUDE.md` và `ARCHITECTURE.md`, không chép lại | Một nguồn duy nhất, không trôi; Antigravity đọc `AGENTS.md` sẵn | `docs/RULES.md` + `DECISIONS.md`/`ROADMAP.md`/`SPEC.md` trong repo: trùng `CLAUDE.md`, và `CLAUDE.md` của lfmap cấm tạo ROADMAP/DECISIONS (ADR nằm ngoài repo) |
| 3 | Antigravity commit và **push nhánh `ag/<task>`**; Project mở PR, review, merge theo luật repo | Giữ CI Provenance, CodeQL, test, squash (lfmap) | `git merge --no-ff` cục bộ vào `main` như bản gốc: bỏ qua mọi check |
| 4 | Commit của Antigravity giữ hook `Dev-Environment: pc-01`, chữ ký SSH của pc-01, và thêm trailer `AI-Agent: antigravity/<model>` | Đúng quy tắc provenance (máy cá nhân được khai báo), tách được phần AI nào viết cho hồ sơ bản quyền | Tiền tố `[AG]` trong tiêu đề commit: trái Conventional Commits của isomp, không nằm trong chữ ký trailer |
| 5 | Mỗi task Antigravity chạy trong **git worktree riêng** `D:\Development\<repo>-ag`, mở đúng thư mục đó trong Antigravity | Không tranh file với Claude Code; Antigravity không thấy phần còn lại của `D:\Development` | Mở cả repo chính hoặc cả `D:\Development` |
| 6 | Phân việc ba tầng: thẻ S có test chặt → qwen (local, không rời máy); việc phụ đặc tả rõ → Antigravity; còn lại → Claude Code | Tầng 0 (model local) đã chạy, rẻ nhất và không gửi dữ liệu ra ngoài | Bỏ qua qwen như bản gốc |
| 7 | Phạm vi dữ liệu: **chờ Hùng chọn** (card trong thread "Thiết lập Google Antigravity hỗ trợ dự án"). Đề xuất: chỉ lfmap + MarkitdownTool (đã public), telemetry tắt, 3 tuần | Gửi code lên Google là gửi dữ liệu ra ngoài, cần Hùng duyệt phạm vi và hạn | Cả isomp (private, hồ sơ bản quyền rủi ro trung bình); hoãn tới khi có Workspace/GCP |

Không mâu thuẫn ADR nào: ADR-004 nói về framework agent trong sản phẩm, Antigravity là công cụ phát triển như Claude Code, không vào sản phẩm.

## Phạm vi

Trong: quy tắc và quy trình cho Antigravity ở lfmap và MarkitdownTool (`AGENTS.md`, mục mới trong `CLAUDE.md`, dòng mới trong `docs/DEVELOPMENT_PROVENANCE.md`); `AGENTS.md` chặn ở isomp; License Register; bản mô tả dùng AI (hồ sơ bản quyền); một task thử.
Ngoài: đổi hook/CI (task AG-T7, sau thử nghiệm), MCP cho Antigravity, browser agent, mọi dữ liệu thật.

## Thiết kế

### Vai trò

| Tầng | Công cụ | Việc | Không được |
| --- | --- | --- | --- |
| Managing Agent | Project (coordinator + thread), Claude | Kế hoạch, kiến trúc, thẻ task, review, merge | — |
| Working Agent | Claude Code Cloud/Local | Logic lõi, bảo mật, tích hợp, debug nhiều module | Merge khi chưa qua review |
| Deputy Working Agent | Antigravity, Gemini Flash mặc định (Pro chỉ khi Flash trượt) | Task `[AG]` trên `ag/*` | Merge, đổi kiến trúc, thêm dependency, sửa file ngoài danh sách |
| Working Agent local | qwen2.5-coder:14b + sổ L1b | Thẻ S có test đóng băng (ADR-004, Roadmap 1.7) | Thẻ M, bảo mật |

### Phân loại task

Gắn nhãn khi soạn thẻ: `[CC]` Claude Code, `[AG]` Antigravity, `[QW]` qwen.

- `[QW]` nếu: code thuần, một chức năng, có test đóng băng sẵn.
- `[AG]` nếu trả lời "Có" cả ba: đặc tả rõ và kiểm được; chỉ đụng file liệt kê sẵn; làm sai thì bỏ nhánh làm lại không ảnh hưởng gì. Thêm điều kiện: không đụng đường dẫn do người dùng cấp, `PermissionManager`, adapter, subprocess, mạng, `.github/`, `.githooks/`, `.claude/`, file khoá dependency.
- Còn lại `[CC]`.

Ví dụ `[AG]`: README, docstring, hướng dẫn sử dụng; test theo đặc tả có sẵn (ngoài phần bảo mật); script tiện ích độc lập trong `scripts/` không gọi mạng; dữ liệu mẫu tổng hợp; tra cứu, so sánh thư viện (kết quả vẫn qua License Register).

### Quy trình một task `[AG]`

1. Project soạn thẻ theo mẫu dưới, đặt trong handoff của tính năng, merge vào `main`.
2. Tạo worktree trên DIEP-ANH (Claude qua Remote Control hoặc Hùng chạy một lệnh):
   ```powershell
   git -C D:\Development\lfmap fetch origin
   git -C D:\Development\lfmap worktree add -b ag/<task> D:\Development\lfmap-ag origin/main
   ```
   Worktree dùng chung `.git/config` của repo chính nên `core.hooksPath` và khoá ký vẫn áp dụng.
3. Hùng mở `D:\Development\lfmap-ag` trong Antigravity, dán prompt khởi động (cuối file).
4. Antigravity làm, commit từng bước nhỏ (bắt buộc commit trước khi đổi model), chạy kiểm tra trong thẻ, `git push -u origin ag/<task>`.
5. Project mở PR từ `ag/<task>`, review theo checklist dưới; ĐẠT thì merge khi CI xanh, CẦN SỬA thì ghi danh sách lỗi vào PR để Antigravity sửa trên cùng nhánh.
6. Dọn: `git worktree remove D:\Development\lfmap-ag`, xoá nhánh đã merge.

### Mẫu thẻ `[AG]`

```markdown
### Task [AG] <mã>: <tên>
- Repo / nhánh: <repo> / ag/<ten-task>, worktree D:\Development\<repo>-ag
- Mục tiêu: <1–2 câu>
- File được phép sửa/tạo: <đường dẫn, mỗi dòng một file>
- Đầu vào tham chiếu: <spec, file mẫu>
- Tiêu chí hoàn thành (kiểm được): <lệnh test/lint phải xanh; điều kiện nội dung>
- KHÔNG được làm: <thêm dependency, sửa file khác, ...>
- Model: Gemini Flash (Pro chỉ khi Flash trượt 2 lần)
```

### Checklist review nhánh `ag/*`

1. `git diff --stat origin/main...ag/<task>`: chỉ có file trong danh sách của thẻ.
2. Mọi commit có `Dev-Environment: pc-01`, `AI-Agent: antigravity/<model>`, được GitHub xác nhận chữ ký (CI Provenance).
3. Tiêu chí hoàn thành của thẻ đạt; test, ruff (lfmap) hoặc unittest (MarkitdownTool) xanh trong CI.
4. Không dependency mới, không đổi kiến trúc, không lộ dữ liệu thật hay đường dẫn máy.
5. Kết luận ĐẠT hoặc CẦN SỬA (liệt kê cụ thể). Review bằng Sonnet khi diff dưới khoảng 200 dòng, Opus khi đụng nhiều module.

### Cấu hình Antigravity trên DIEP-ANH

Tên mục lấy theo tài liệu và bài viết bên thứ ba; đối chiếu lại trên UI khi cài.

| Mục | Giá trị | Lý do |
| --- | --- | --- |
| Account → Enable Telemetry | Tắt | Giảm dữ liệu Google giữ lại |
| Terminal execution | Request review (hỏi trước mọi lệnh) | Lỗi PromptArmor dùng `cat .env`; allow list có lỗi đã báo |
| Allow list lệnh (nếu muốn bớt hỏi) | `git status`, `git diff`, `git log`, `git add`, `git commit`, `uv run pytest`, `uv run ruff` | Lệnh chỉ đọc hoặc chỉ ghi trong worktree |
| Deny list lệnh | `git push origin main`, `git merge`, `git rebase`, `git reset`, `git push --force`, `gh`, `curl`, `Invoke-WebRequest`, `Remove-Item -Recurse` | Chặn merge/ghi đè và gửi dữ liệu ra ngoài |
| File ngoài workspace | Deny | Không đọc `~/.ssh`, `%LOCALAPPDATA%`, tài liệu thật |
| Browser agent / URL | Tắt; nếu cần, chỉ cho tài liệu thư viện | Kênh rò rỉ chính của các lỗi đã công bố |
| MCP server | Không thêm | Không mở rộng quyền |
| Model mặc định | Gemini Flash | Tiết kiệm hạn mức |
| Thư mục mở | Chỉ `D:\Development\<repo>-ag` | Antigravity không thấy repo chính, sổ L1b, dữ liệu bench |

Repo không có `GEMINI.md`; không đặt quy tắc toàn cục trong `~/.gemini/` để tránh hai nguồn.

## Danh sách task

| # | Task | Môi trường | Tiêu chí hoàn thành |
| --- | --- | --- | --- |
| AG-T1 | PR tài liệu: `AGENTS.md`, mục Deputy trong `CLAUDE.md`, dòng `AI-Agent` trong provenance (lfmap, MarkitdownTool); `AGENTS.md` chặn (isomp) | Cloud (thread này) | Merge 3 PR, CI xanh |
| AG-T2 | Cập nhật License Register và bản mô tả dùng AI (project files) | Cloud (thread này) | Có dòng Antigravity / Gemini |
| AG-T3 | Cài Antigravity, đăng nhập, cấu hình theo bảng trên | Hùng trên DIEP-ANH | Ảnh chụp Settings hoặc Hùng xác nhận |
| AG-T4 | Tạo worktree `D:\Development\lfmap-ag` nhánh `ag/lfmap-core-readme`; kiểm `core.hooksPath`, `DEV_ENVIRONMENT=pc-01` | Local (Claude qua Remote Control) | `git -C D:\Development\lfmap-ag config core.hooksPath` = `.githooks` |
| AG-P1 | Task thử: README cho `lfmap-core` (thẻ dưới) | Antigravity trên DIEP-ANH | Nhánh đã push, commit đủ trailer |
| AG-T5 | Review và merge AG-P1, ghi số liệu ngày | Cloud | PR merge hoặc CẦN SỬA có lý do |
| AG-T6 | Thêm cột Antigravity vào báo cáo ngày 22:00 (hạn mức Claude, số task CC/AG/QW, số lần làm lại) | Cloud (coordinator) | Báo cáo 30/10 có bảng |
| AG-T7 | (Sau 1 tuần thử) Hook tự thêm `AI-Agent` từ `git config --worktree`, CI Provenance báo lỗi khi commit trên `ag/*` thiếu trailer | Cloud `[CC]` | PR code ở 3 repo, test hook |

### Thẻ AG-P1

```markdown
### Task [AG] AG-P1: README for lfmap-core
- Repo / nhánh: lfmap / ag/lfmap-core-readme, worktree D:\Development\lfmap-ag
- Mục tiêu: replace the 3-line packages/lfmap-core/README.md with a short guide to the package.
- File được phép sửa/tạo: packages/lfmap-core/README.md
- Đầu vào tham chiếu: ARCHITECTURE.md ("Module map" section), packages/lfmap-core/src/lfmap_core/*.py (read only), plugins/lfmap-powershell/README.md (style)
- Tiêu chí hoàn thành:
  - [ ] One line per public module in src/lfmap_core/, in English, matching what the code does
  - [ ] Sections: purpose, modules, how plugins use it, commands (uv sync, uv run pytest packages/lfmap-core)
  - [ ] Under 120 lines; links to ARCHITECTURE.md instead of repeating it
  - [ ] git diff --stat origin/main shows only that file
- KHÔNG được làm: edit any other file, add dependencies, run anything other than git and uv run pytest
- Model: Gemini Flash
```

## Chuẩn bị sẵn

- Ba PR tài liệu (AG-T1) và cập nhật project files (AG-T2) trong thread này.
- `AGENTS.md` mỗi repo đã có quy tắc trước/trong/sau khi làm, lệnh kiểm tra, cách thêm trailer.
- DIEP-ANH đã có khoá ký `pc-01`, `DEV_ENVIRONMENT=pc-01`, `core.hooksPath` ở lfmap và MarkitdownTool (2026-10-23).
- Thẻ AG-P1 ở trên.

## Rủi ro

| Rủi ro | Mức | Cách phòng |
| --- | --- | --- |
| Code và prompt bị Google giữ hoặc dùng cải thiện model | Trung bình | Chỉ repo đã public (đề xuất), telemetry tắt, không dữ liệu thật, hạn 3 tuần |
| Prompt injection đọc secrets trên DIEP-ANH (`~/.ssh`, token `gh`, credential Git) rồi gửi ra ngoài | Cao | Terminal hỏi trước, browser tắt, deny file ngoài workspace, không MCP; Hùng đọc kỹ lệnh trước khi bấm duyệt |
| Antigravity push nhầm `main` (Git Credential Manager có quyền ghi mọi repo) | Trung bình | Deny list; khuyến nghị ruleset "Require a pull request" trên `main` |
| Lệch kiến trúc | Cao | Danh sách file trong thẻ, review bắt buộc |
| Mất code khi đổi model | Cao | Commit trước khi đổi model, worktree riêng |
| Hết hạn mức Antigravity giữa chừng | Trung bình | Không giao việc gấp; chuyển cho Claude Sonnet hoặc qwen |
| Review tốn hạn mức Claude hơn phần tiết kiệm | Trung bình | Thẻ nhỏ, review bằng Sonnet, đo trong báo cáo ngày |
| Khai AI-use thiếu trong hồ sơ bản quyền | Thấp | Trailer `AI-Agent`, dòng mới trong bản mô tả dùng AI |

## Câu hỏi còn mở

1. Phạm vi repo cho Antigravity (card đang chờ Hùng).
2. Bật ruleset "Require a pull request before merging" trên `main` của 3 repo? Ảnh hưởng: mọi thay đổi phải qua PR (hiện đã là quy ước).
3. Mốc hạn mức Claude (`/usage`) ngày 30/10 để so sánh.

## Cập nhật tài liệu dự án

- 04_License_Register: dòng Google Antigravity (Internal, công cụ dev, điều khoản Google, không phân phối) — làm trong AG-T2.
- 05_Roadmap: không đổi phạm vi; ghi chú "thử Deputy Antigravity 30/10 – 20/11".
- 03_Decisions_ADR: chưa cần ADR; nếu giữ mô hình sau đánh giá, viết ADR "Agent phụ ngoài Anthropic cho task `[AG]`".
- 06_Prompt_Playbook: thêm mẫu thẻ `[AG]` và checklist review `ag/*`.
- Hồ sơ bản quyền: `ban-quyen/03_Mo_ta_su_dung_AI.md` thêm Antigravity/Gemini; `30_So_thiet_bi...` ghi trailer `AI-Agent`.

## Prompt khởi động

Cho Antigravity (dán vào khung agent sau khi mở worktree):

```text
You are the Deputy agent for this repository. Read AGENTS.md first and follow it.
Your task card is "AG-P1" in docs/handoff/2026-10-29-antigravity-deputy.md.
Confirm the current branch is ag/lfmap-core-readme before changing anything.
Edit only the files the card lists. Commit after each small step with
  git commit -m "<type>: <summary>" --trailer "AI-Agent: antigravity/<model you are running>"
When every completion criterion is met, push with git push -u origin ag/lfmap-core-readme
and finish with a short report: what you changed, which criteria you checked, open questions.
```

Cho Project review (thread Cloud):

```text
Review branch ag/<task> against main using the "Checklist review nhánh ag/*" in
docs/handoff/2026-10-29-antigravity-deputy.md and the task card. Open the PR if it does
not exist. Conclude ĐẠT (merge when CI is green) or CẦN SỬA (list each fix in the PR).
```

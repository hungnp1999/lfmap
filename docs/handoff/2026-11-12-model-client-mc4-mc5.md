# Bàn giao: ModelClient MC-4 và MC-5 (#249, #250)

## Bối cảnh

- Spec: `docs/specs/model-client.md` mục 8 (phép đối chiếu embedding) và mục 11. MC-1 đến MC-3 đã merge (PR #221, #225, #226); #189 đã đóng.
- MC-4 (#249) là một lần chạy đo trên DIEP-ANH (pc-01) có Ollama và GPU; ra báo cáo, không đổi mã sản phẩm. MC-5 (#250) chỉ làm nếu MC-4 đạt.

## Mục tiêu

Biết `bge-m3` qua `/v1/embeddings` (OpenAI-compatible, qua `OpenAICompatibleClient`) có cho vector giống `/api/embed` đang dùng không. Nếu giống thì `knowledge` chuyển sang `ctx.models` và bỏ `OllamaEmbedder`.

## Quyết định đã chốt

- Ngưỡng đạt (quyết định 6 của spec): mọi vector có cosine ≥ 0.9999 với vector cũ, cùng số chiều, và bench iso-vi cho cùng file gold trong cùng top-10 trên cả 9 câu, `precision` và số token không thấp hơn.
- Không đạt thì giữ vector cũ; reindex toàn bộ là quyết định riêng của anh Hùng (chỉ mục sẽ lẫn hai loại vector).
- Hàng `llama-server` trong container CPU chỉ là thông tin, bỏ qua nếu DIEP-ANH không có Docker/WSL (hiện không có).

## Phạm vi

MC-4: tạo `docs/research/2026-11-12-model-client-embed-equivalence.md`, `packages/lfmap-knowledge/tests/test_embed_equivalence_bench.py` (đánh dấu `local`, CI bỏ qua) và một script chạy nhỏ dưới `spikes/mc4-embed-equivalence/`. Không sửa `embed.py` hay `lfmap_core/models*.py`.
MC-5: file liệt kê trong #250.

## Danh sách task

| Task | Loại | Ưu tiên | Blocked by | Môi trường |
| --- | --- | --- | --- | --- |
| MC-4 #249 | [CC] | P2 | none | Local pc-01, `res:gpu`, chạy một mình |
| MC-5 #250 | [CC] | P2 | MC-4 đạt | Cloud, `/security-review` |

## Chuẩn bị sẵn (đã kiểm trong repo)

- Bench có sẵn: `packages/lfmap-knowledge/bench/iso-vi/` (30 tài liệu, `questions.json` 9 câu, `context_bench.py`; README ghi cách chạy với `LOCALAPPDATA` riêng và `config.toml` có `[paths] knowledge`).
- Chưa kiểm được từ Cloud (phiên trên máy phải kiểm và dừng nếu lệch): Ollama đang chạy và có `bge-m3`; bản clone `D:\Development\lfmap` đã cập nhật; GPU không bận. Khung 23:00 đến 06:00 giờ VN là giờ chạy shadow review local của ADR-022: phiên phải chạy `ollama ps` trước, nếu có model khác đang nạp thì dừng và báo, không giành GPU.

## Rủi ro

- Ollama `/v1/embeddings` có thể không chuẩn hóa vector như `/api/embed`: báo cả hai số (cosine và có chuẩn hóa hay không), không tự suy kết luận.
- Chạy bench hai lần cần hai chỉ mục tách biệt (hai `LOCALAPPDATA`), tuyệt đối không đụng chỉ mục thật của anh Hùng.
- Mọi thứ dùng đường dẫn do người gọi đưa vào đi qua cơ chế quyền có sẵn; script chỉ đọc `bench/iso-vi/docs`.

## Cập nhật tài liệu dự án

- Sau MC-4: ghi kết quả vào #249, #250 và #189 (đạt hay không).
- Sau MC-5: bỏ `OllamaEmbedder` khỏi `ARCHITECTURE.md`.

## Prompt MC-4 (phiên Claude Code trên DIEP-ANH, thư mục `D:\Development\lfmap`)

```
Task MC-4 of lfmap issue #249 (parent #189). Read docs/handoff/2026-11-12-model-client-mc4-mc5.md and docs/specs/model-client.md section 8 first.
Setup: git fetch origin main; new branch mc4-embed-equivalence from origin/main (Dev-Environment trailer pc-01, commits signed). Do not touch D:\Development\lfmap-* state folders and never the owner's real knowledge index.
Preflight, stop and report instead of improvising on any surprise: (1) Ollama answers on http://127.0.0.1:11434 and `ollama list` has bge-m3; (2) `ollama ps` shows no other model loaded (GPU jobs are strictly serial; 23:00-06:00 VN is the shadow-review window); (3) uv sync works. Use pwsh at C:\Users\Admin\AppData\Local\Microsoft\WindowsApps\pwsh.exe if needed.
Do: write spikes/mc4-embed-equivalence/run.py (stdlib + repo code only, no new dependency) that (a) takes the 30 chunked documents of packages/lfmap-knowledge/bench/iso-vi/docs exactly as the indexer chunks them, plus a 500-text sample drawn from them with a fixed seed; (b) embeds them through the current OllamaEmbedder (/api/embed) and through lfmap_core.models_http.OpenAICompatibleClient against http://127.0.0.1:11434/v1 (model bge-m3); (c) records per-vector cosine (min, mean, count below 0.9999), vector length, and whether vectors are L2-normalised on each path; (d) builds two isolated indexes (separate LOCALAPPDATA and config.toml with [paths] knowledge pointing at the bench docs, one per path) and runs bench/iso-vi/context_bench.py on each, comparing gold files in top-10, precision and tokens per question. Add packages/lfmap-knowledge/tests/test_embed_equivalence_bench.py marked `local` (skipped in CI) asserting the pass rule. Keep run.py small and run it first with a fake embedder through two cases (including the failing case) before the real run; it must restore any environment variable it sets.
Write docs/research/2026-11-12-model-client-embed-equivalence.md (English): numbers, the PASS or FAIL verdict against: all cosine >= 0.9999, equal dimension, same top-10 gold files on all 9 questions, precision and tokens not lower. Do not edit embed.py or lfmap_core/models*.py. Run uv run pytest packages/lfmap-knowledge and ruff. Merge origin/main before push, open a draft PR from the template (no "Closes"), comment the verdict on #249, #250 and #189. Do not merge.
```

## Prompt MC-5 (phiên Claude Code Cloud, repo lfmap; chỉ dán khi #249 ghi PASS)

```
Task MC-5 of lfmap issue #250 (parent #189). First read the verdict on issue #249 and docs/research/2026-11-12-model-client-embed-equivalence.md: if it is not PASS, stop and tell me. Then read docs/handoff/2026-11-12-model-client-mc4-mc5.md, docs/specs/model-client.md section 8 ("After the switch") and issue #250. Branch from up-to-date main.
Declare [adapters] models = true in the knowledge manifest and route embeddings through ctx.models.embed(task="embed"); keep the settings ollama_url, embed_model, embed_batch, embed_concurrency working as fallbacks for the embed route; remove OllamaEmbedder in the same PR; keep knowledge.status ollama_ok and the keyword fallback (mode_used = "keyword") when the embedder is down. Do not change lfmap_core/models*.py behaviour, adapters, or existing vectors (no reindex). Existing lfmap-knowledge tests must pass unchanged. Add changelog.d/189-knowledge-modelclient.changed.md, update ARCHITECTURE.md (remove embed.py/OllamaEmbedder from the knowledge row). Merge origin/main before every push, run uv run pytest and uv run ruff check . and uv run ruff format --check . (7 test_jobs_doctor failures on Linux are pre-existing). Commit trailers: Dev-Environment: cloud and Claude-Session. Open a draft PR from the template with "Closes #250", then run /security-review on the diff and answer every finding in the PR. Do not merge; report the PR link.
```

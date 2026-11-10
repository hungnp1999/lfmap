# Bàn giao: ModelClient MC-2 và MC-3 (#189)

## Bối cảnh

- Spec đã chốt: `docs/specs/model-client.md` (PR #216). Quyết định của Hùng 08/11: ModelClient nằm trong core, Agent Router là chính sách định tuyến.
- MC-1 đã code trong PR #221: `models.py` (Protocol, `[models]`, `load_models_config`), `models_http.py` (client stdlib), `test_models.py`. Chưa nối vào `ctx` hay plugin nào.

## Mục tiêu

Nối MC-1 vào Permission Manager và approval gate, rồi thêm plugin `llm` mỏng. Không đổi adapter (`cli.py`, `mcp_adapter.py`).

## Danh sách task

| Task | Loại | Ưu tiên | Blocked by | Môi trường |
| --- | --- | --- | --- | --- |
| MC-2 | [CC] | P1 | #221 merged | Cloud |
| MC-3 | [CC] | P1 | MC-2 merged | Cloud |

### MC-2 (một PR)

Phạm vi file: `packages/lfmap-core/src/lfmap_core/{models_router.py, models_egress.py, tool.py, runtime.py, approval.py, manifest.py}`, tests mới trong `packages/lfmap-core/tests/`, `ARCHITECTURE.md`, một changelog fragment.

1. `ModelRouter`: `task` -> endpoint qua `ModelsConfig.route`; kiểm data class (`secret` không bao giờ ra cloud, kiểm trước khi hỏi gate); manifest phải có `cloud_ai` và `network`; gọi `ctx.require_approval("external", ..., destination=<host>, data=<class>)` (T3); endpoint local gọi `ctx.permissions.require_network()`.
2. `models_egress.py`: ghi dòng `model_call` vào `audit.jsonl` qua `audit()`: dòng `status=sent` trước khi gửi, dòng kết quả (kích thước, trạng thái cuối) sau. `AUDIT_FIELDS` thêm `host, bytes_out, bytes_in, endpoint, model, data`. Ghi dòng đầu lỗi thì không gửi. Không bao giờ ghi nội dung, vector, API key. Gọi local không ghi dòng nào.
3. `ToolContext.models` (như `events`), chỉ có khi manifest `[adapters] models = true`, nếu không thì `permission_denied`. Plugin chỉ đặt tên task, không đặt được URL.
4. `ARCHITECTURE.md`: sửa invariant "No network beyond loopback" thành có ngoại lệ cloud qua cổng; chuyển dòng module map từ "chưa nối" sang đã nối.
5. Ghi chú ADR (quyết định 11): soạn đoạn ngoại lệ "gated cloud" cho ADR "no network beyond loopback" trong PR body mục "Cập nhật tài liệu dự án"; không tạo file ADR trong repo này.

Test đóng băng (tên cố định trong spec §10): `test_non_loopback_refused_without_approval` (nửa gate: kênh `mcp`, `job`, `flow` -> `permission_denied`, socket guard không cho connect), `test_model_call_audit_line_per_cloud_call`, `test_secret_never_to_cloud`, `test_private_needs_destination_level`, `test_cloud_requires_manifest_permissions`, `test_ctx_models_gate`.

Cổng: PR chạm network và gate nên **gate:po**? Không bắt buộc; nhưng bắt buộc `/security-review` trước khi merge (label `security-review`).

### MC-3 (một PR)

Phạm vi: `plugins/lfmap-llm/` mới (theo mẫu `plugins/lfmap-echo`), `Tool.call_tier` (T0 khi route local, T3 khi route cloud), `uv.lock` nếu workspace cần, changelog fragment.

- Manifest: id `llm`, `[adapters] cli = true, mcp = true, rest = false, events = true, models = true`, `[permissions] network = true, cloud_ai = true`, không đọc/ghi file. Ba operation `summarise`, `extract`, `classify` với `side_effects = "external"`, `min_tier = "T0"`; schema vào/ra theo spec §7.
- Prompt cố định trong plugin, văn bản đầu vào đặt sau dấu phân cách, system message nói đó là dữ liệu. `extract` chỉ giữ khóa trong schema đúng kiểu, sai/thiếu vào `missing`, output không phải JSON -> `backend_unavailable` (`bad_response`). `classify` chỉ trả một nhãn trong `labels`.
- Test đóng băng: `test_call_tier_follows_route`, `test_llm_extract_validates`, `test_llm_classify_label_set`, `test_llm_prompt_delimits_input`, thêm một test flow-step `call = "llm.summarise"`.

## Ngoài phạm vi

MC-4 (đối chiếu embedding trên DIEP-ANH) và MC-5 (chuyển `knowledge`), streaming, tool calling. Không bật route cloud nào trước khi nhãn dữ liệu đi theo dữ liệu (quyết định 3); `allow_cloud_unlabelled` vẫn là mặc định tắt.

## Rủi ro

- Prompt injection qua văn bản đầu vào: kết quả `extract`/`classify` luôn được kiểm bằng code.
- Lộ khóa hoặc nội dung vào log: test grep file audit.
- Tên dòng audit mới phải qua allow-list trong `approval.py`.

## Cập nhật tài liệu dự án

- ADR "no network beyond loopback": thêm ngoại lệ cloud có cổng T3 (quyết định 11, đợi Hùng duyệt qua gate:po khi sửa ADR).
- Roadmap Phase 2: Agent Router = chính sách định tuyến của spec này.

## Prompt khởi động (dán vào phiên Claude Code Cloud, repo lfmap)

```
Task MC-2 of lfmap #189. Read docs/handoff/2026-11-10-model-client-mc2-mc3.md (section MC-2) and docs/specs/model-client.md (sections 4, 5, 6, 9, 10). PR #221 (MC-1) must be merged first; branch from up-to-date main.
Implement only the files listed. Tests named in the card are frozen: write them first with exactly those names. Keep ModelClient/models_http.py behaviour unchanged. Add changelog.d/189-model-router.added.md, update ARCHITECTURE.md, merge origin/main before push, open a draft PR (body: summary, "Cập nhật tài liệu dự án" list incl. the ADR exception text), do NOT write "Closes #189". Run uv run pytest and ruff; the 7 test_jobs_doctor failures on Linux are pre-existing. Then run /security-review on the diff and answer each finding in the PR.
```

Cho MC-3 dùng cùng prompt, thay "MC-2" bằng "MC-3" và các mục tương ứng; MC-3 mới được đóng #189 bằng `Closes #189` sau khi MC-2 đã merge.

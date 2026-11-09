<!-- Excerpt of the project file 01_LFMAP_Blueprint_v0.2 (sections 4 and 5, Vietnamese), kept in the repo so Cloud sessions can read it. The project file stays the source; section 4.4 is the Agent Router routing rule (#189). -->

## 4. Hybrid AI Design

### 4.1 Managing Agents (Cloud — Claude)

Vai trò: Architect, Planner, Reviewer, Decision, Research.

```text
Phân tích yêu cầu → Thiết kế → Phân rã task (Task Card) → Giám sát → Review
```

### 4.2 Working Agents (Local — RTX 5060 Ti 16GB)

Stack: Ollama (runtime), Open WebUI (chat nội bộ), model họ Qwen / DeepSeek.

Thực tế phần cứng: 16GB VRAM chạy thoải mái model ~7–14B đã lượng tử hóa; model lớn hơn phải offload sang RAM và chậm đi đáng kể. Vì vậy Working Agents nhận **task nhỏ, rõ ràng, có test**:

- Coding Agent — viết hàm theo Task Card
- Testing Agent — viết/chạy test
- Documentation Agent — docstring, README
- Data Processing / Batch Agent — xử lý hàng loạt dữ liệu nhạy cảm
- Embedding — sinh vector cho Knowledge Hub

### 4.3 Luồng chuẩn

```text
Human → Claude (Plan) → Task Cards → Local Agents (Execute)
      → Claude (Review) → Human Approval → Merge/Run
```

### 4.4 Quy tắc định tuyến (Agent Router, Phase 2)

| Tiêu chí | Local | Cloud |
|---|---|---|
| Dữ liệu nhạy cảm | ✅ mặc định | chỉ khi người dùng cho phép |
| Task lặp lại, khối lượng lớn | ✅ | |
| Thiết kế, suy luận nhiều bước | | ✅ |
| Review chất lượng | | ✅ |
| Embedding | ✅ | |

## 5. Orchestration Layer

- **MCP** — chuẩn giao tiếp chính giữa agent và tool (discovery, invocation, context).
- **PowerShell 7** — tự động hóa local, tích hợp Windows; được bọc thành plugin `powershell` với danh sách lệnh/script được phép (allow-list), không chạy lệnh tùy ý.
- **n8n** — chỉ dùng **nội bộ** cho workflow cá nhân (email → tool → agent). Không đóng gói vào sản phẩm phân phối do giấy phép Sustainable Use License. Sản phẩm thương mại dùng workflow engine của lfmap-core.

## 6. Giao tiếp giữa Module

Thứ tự ưu tiên:

```text
In-process SDK call  →  MCP  →  REST  →  Event Bus
(cùng process)          (agent)  (UI/n8n) (bất đồng bộ, Phase 2)
```

Tên sự kiện theo Plugin Contract §5: `<plugin>.<operation>.requested` / `.completed` / `.failed` — vd. `markitdown.convert.completed`.


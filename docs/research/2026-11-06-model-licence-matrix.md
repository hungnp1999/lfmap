# RT-06: licence matrix of models that run on 16 GB VRAM

- Date: 2026-11-06
- Plan: RT-06 in [`2026-10-23-commercial-replacements.md`](2026-10-23-commercial-replacements.md) (G1). Output: proposed rows for the "Model AI (weights)" table of the License Register (outside the repo).
- Rule it serves: ADR-021 and the Register note: weights licences differ by family, version and size; only Apache-2.0/MIT models go into anything distributed.

## 1. How far this can be trusted

Cloud cannot reach `huggingface.co` or `ollama.com` (host blocked by the session's network policy), so **no row below was read from its model card today**. Licences come from the model families' published terms as known to Claude and one secondary search on 2026-11-06 (Qwen3, Phi-4, Mistral Small, Gemma terms agree with it; blog sources, not authoritative). Every row therefore has status **to verify**. Before a row moves into the Register, on DIEP-ANH: `ollama show --license <tag>` and open the linked model card, then write the date. Rows already in the Register (checked 2026-10-18/23 on DIEP-ANH) are marked **in Register** and not repeated as new.

Link column: Hugging Face model card of the original release (the Ollama tag is a repackaging; its licence must match).

## 2. Matrix

"Fits" = Q4 weights plus a small KV cache fit in 16 GB with all layers on GPU at about 8K context; sizes are Ollama-style Q4 downloads and approximate.

### 2.1 Chat and reasoning models

| Model | Size / Q4 | Fits 16 GB | Licence (to verify) | Restrictions that matter | Model card | Proposed class |
| --- | --- | --- | --- | --- | --- | --- |
| Qwen3 4B | 4B / ~2.6 GB | yes | Apache-2.0 | none | [Qwen/Qwen3-4B](https://huggingface.co/Qwen/Qwen3-4B) | Internal; Ship after check |
| Qwen3 8B | 8B / ~5 GB | yes | Apache-2.0 | none | [Qwen/Qwen3-8B](https://huggingface.co/Qwen/Qwen3-8B) | Internal; Ship after check |
| Qwen3 14B | 14B / ~9 GB | yes | Apache-2.0 | none | [Qwen/Qwen3-14B](https://huggingface.co/Qwen/Qwen3-14B) | Internal; Ship after check (Working-tier candidate, section 4 of the tiers note) |
| Phi-4 mini | 3.8B / ~2.5 GB | yes | MIT | none | [microsoft/Phi-4-mini-instruct](https://huggingface.co/microsoft/Phi-4-mini-instruct) | Internal; Ship after check |
| Phi-4 | 14B / ~9 GB | yes | MIT | none | [microsoft/phi-4](https://huggingface.co/microsoft/phi-4) | Internal; Ship after check |
| Mistral Nemo | 12B / ~7 GB | yes | Apache-2.0 | none | [mistralai/Mistral-Nemo-Instruct-2407](https://huggingface.co/mistralai/Mistral-Nemo-Instruct-2407) | Internal; Ship after check |
| Mistral Small 3.2 | 24B / ~15 GB | tight at 8K | Apache-2.0 | none | [mistralai/Mistral-Small-3.2-24B-Instruct-2506](https://huggingface.co/mistralai/Mistral-Small-3.2-24B-Instruct-2506) | Internal; Ship after check |
| gpt-oss 20B | 20B MoE / ~14 GB | yes | Apache-2.0 + OpenAI usage policy | usage policy is an acceptable-use addendum | **in Register** | — |
| Gemma 3 (4B, 12B) | 4B ~3 GB, 12B ~8 GB | yes | Gemma Terms of Use (not OSI, not Apache) | prohibited-use policy flows down to every redistribution; distillation limits; Google may require updates | [google/gemma-3-12b-it](https://huggingface.co/google/gemma-3-12b-it) | **Avoid** for Ship; Internal only with Hùng's note |
| Llama 3.1 8B, Llama 3.2 3B | 8B ~5 GB, 3B ~2 GB | yes | Llama community licence | 700 M monthly-active-user clause, attribution and "Llama" naming rules, acceptable-use policy | [meta-llama/Llama-3.1-8B-Instruct](https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct) | **Avoid** for Ship; Internal only |
| Ministral 8B | 8B / ~5 GB | yes | Mistral Research Licence for the 8B-2410 weights (not Apache) | research and non-commercial use only | [mistralai/Ministral-8B-Instruct-2410](https://huggingface.co/mistralai/Ministral-8B-Instruct-2410) | **Avoid** (do not use) |
| DeepSeek-R1 distills (Qwen- or Llama-based, 7B to 32B) | 7B ~5 GB, 14B ~9 GB | 7B, 14B yes | MIT on the distill weights, but the base model's licence still applies (Qwen base: Apache-2.0; Llama base: Llama licence) | check the base per file; Register row "DeepSeek (họ)" must name the exact distill | [deepseek-ai/DeepSeek-R1-Distill-Qwen-14B](https://huggingface.co/deepseek-ai/DeepSeek-R1-Distill-Qwen-14B) | Internal after per-file check |

### 2.2 Coding models

| Model | Size / Q4 | Fits 16 GB | Licence (to verify) | Restrictions | Model card | Proposed class |
| --- | --- | --- | --- | --- | --- | --- |
| Qwen2.5-Coder 14B | 14B / ~9 GB | yes | Apache-2.0 | none | **in Register** | — |
| Qwen2.5-Coder 3B | 3B | yes | Qwen-research licence (not Apache) | non-commercial | [Qwen/Qwen2.5-Coder-3B](https://huggingface.co/Qwen/Qwen2.5-Coder-3B) | **Avoid**; fills the Register's open "Qwen (bản khác)" warning |
| Qwen2.5-Coder 32B | 32B / ~20 GB | no (CPU offload) | Apache-2.0 | none | [Qwen/Qwen2.5-Coder-32B-Instruct](https://huggingface.co/Qwen/Qwen2.5-Coder-32B-Instruct) | Internal; slow on 16 GB |
| Qwen3-Coder 30B-A3B | MoE / ~18.6 GB | no (partial offload) | Apache-2.0 | none | **in Register** | — |
| Devstral Small 2 24B | 24B / ~15 GB | tight | Apache-2.0 | none (the 123B Devstral 2 is "modified MIT", a different model) | **in Register** | — |

### 2.3 Embedding models

| Model | Size | Fits | Licence (to verify) | Restrictions | Model card | Proposed class |
| --- | --- | --- | --- | --- | --- | --- |
| BGE-M3 | 567M | yes | MIT | none | **in Register** | — |
| Qwen3-Embedding 0.6B | 0.6B | yes | Apache-2.0 | none | [Qwen/Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) | Internal; alternative to BGE-M3 (RT-08 test) |
| nomic-embed-text v1.5 | 137M | yes | Apache-2.0 | none (training data and code are also open) | [nomic-ai/nomic-embed-text-v1.5](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5) | Internal; weak on Vietnamese, so not a BGE-M3 replacement for LFMAP |
| mxbai-embed-large v1 | 335M | yes | Apache-2.0 | none | [mixedbread-ai/mxbai-embed-large-v1](https://huggingface.co/mixedbread-ai/mxbai-embed-large-v1) | Internal; English-centred |
| EmbeddingGemma 300M | 300M | yes | Gemma Terms of Use | as Gemma 3 | [google/embeddinggemma-300m](https://huggingface.co/google/embeddinggemma-300m) | **Avoid** for Ship |

## 3. Reading the matrix

1. **Safe families for anything distributed:** Qwen3 (all sizes Apache-2.0), Phi-4 and Phi-4 mini (MIT), Mistral Nemo and Mistral Small (Apache-2.0), Qwen2.5-Coder 14B/32B (Apache-2.0), gpt-oss (Apache-2.0 + usage policy), BGE-M3 (MIT), Qwen3-Embedding, nomic and mxbai embeddings (Apache-2.0).
2. **Traps by size inside one family:** Qwen2.5-Coder 3B (research licence) against 14B/32B (Apache-2.0); Ministral 8B (research licence) against Mistral Nemo and Small (Apache-2.0); Devstral Small 2 24B (Apache-2.0) against Devstral 2 123B (modified MIT).
3. **Never in a shipped product:** Gemma (any size, including EmbeddingGemma), Llama, Ministral 8B, Qwen2.5-Coder 3B, any DeepSeek distill whose base is Llama. They may be used internally for development (the Register's Internal class) with the usage policy read once.
4. **Best fit for the open slots:** the Working-tier comparison model `qwen3:14b` is a plain Apache-2.0 row; for a second Leading candidate, Mistral Small 3.2 24B is the only new Apache-2.0 model in the 15 GB class, but it is tight at 8K context.

## 4. Proposed Register rows (to add after verification on DIEP-ANH)

Same columns as the Register table: Model | size / tag | licence | class | checked on.

```text
| Qwen3 | 4B, 8B, 14B (ollama `qwen3:4b|8b|14b`) | Apache-2.0 (HF Qwen/Qwen3-*) | Internal | _date, after `ollama show --license`_ |
| Phi-4, Phi-4 mini | 14B, 3.8B (ollama `phi4`, `phi4-mini`) | MIT (HF microsoft/phi-4, Phi-4-mini-instruct) | Internal | _date_ |
| Mistral Nemo, Mistral Small 3.2 | 12B, 24B | Apache-2.0 | Internal | _date_ |
| Qwen3-Embedding, nomic-embed-text, mxbai-embed-large | 0.6B, 137M, 335M | Apache-2.0 | Internal | _date_ |
| Qwen2.5-Coder | 3B | Qwen-research licence | Avoid | row to close the open "Qwen (bản khác)" line |
| Gemma 3, EmbeddingGemma | all sizes | Gemma Terms of Use | Avoid (Ship) | _date_ |
| Llama 3.x | 3B, 8B | Llama community licence | Avoid (Ship) | _date_ |
| Ministral | 8B (2410) | Mistral Research Licence | Avoid | _date_ |
```

## 5. Decision and what stays open

- Hùng approved this version of the matrix on 2026-11-06 and asked for a **monthly review** (first review 2026-12-06): re-check each row's licence text and tag, add new models that fit 16 GB, and report changes. Scheduled as a recurring task; see the review notes in this folder when it runs.

- **Verification on DIEP-ANH** (about 10 minutes: `ollama show --license <tag>` needs the tag pulled; otherwise read the Hugging Face card in a browser): the "to verify" status of every new row. Not urgent: no new model is planned for the product; this matrix prevents a wrong pick later.
- Completion criterion of RT-06 ("each row has a model-card link") is met by the link column; "licence read from the card" is not met until the verification above.
- To let Cloud verify next time: allow `huggingface.co` and `ollama.com` in the environment's network settings (docs: environment network access).

## 6. Project documentation updates (outside the repo)

- `04_License_Register.md`, "Model AI (weights)": add the section 4 rows once verified; close the "Qwen (họ, bản khác)" placeholder with the Qwen2.5-Coder 3B row.
- `commercial-replacements.md`: RT-06 "matrix drafted 2026-11-06, verification pending".

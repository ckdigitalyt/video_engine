# Provider Capabilities — V13 M1a

*Live-probed: 2026-09-20 20:11 UTC · mode: live (≤3 image calls) · prober: `tools/image_capability_audit.py` · key NAMES only, values stay in `.env` (gitignored).*

| provider | key | edit_image | generate_multi_ref | depth/edge | max res | edit latency |
|---|---|---|---|---|---|---|
| `gemini_image` | `GEMINI_API_KEY` (present) | ❌ failed | wired (2–14 refs, same endpoint) — not probed (budget) | unsupported (planned M3) | 1024-class output (model default) | 0.5s |
| `nvidia_nim` | `NVIDIA_API_KEY` (present) | ❌ failed | unsupported (kontext takes exactly one image) | unsupported (planned M3) | ≤1344 px (NIM allowed dims) | 1.1s |
| `siliconflow` | `SILICONFLOW_API_KEY` (present) | ❌ failed | wired (Qwen-Image-Edit-2509 image list) — not probed (budget) | unsupported (planned M3) | 1024-class (generations endpoint) | 1.0s |
| `pollinations` | `none (keyless)` (present) | unsupported → single-pass text→img fallback | unsupported → single-pass fallback | unsupported (planned M3) | 1280x720 verified (repo note 2026-08) | —s |
| `hf_serverless` | `HF_TOKEN` (present) | unsupported (inference endpoint is text→img only) | unsupported | unsupported (planned M3) | model-dependent (FLUX.1-schnell ≤1024) | —s |

## Probe detail

- **gemini_image**: edit=failed (0.5s) — ClientError: 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota, please check your plan and billing details. For
- **nvidia_nim**: edit=failed (1.1s) — HTTPError: HTTP Error 422: Unprocessable Entity
- **siliconflow**: edit=failed (1.0s) — RuntimeError: siliconflow edit failed: HTTP Error 401: Unauthorized
- **pollinations**: unsupported (inference endpoint is text→img only)
- **hf_serverless**: unsupported (inference endpoint is text→img only)

## Fallback rule (Contract 2)

Any provider without edit/multi-ref support raises `NotImplementedError`; `edit_image_with_fallback` / `generate_multi_ref_with_fallback` degrade to single-pass text→img and report `(path, edited=False)` so plate sidecars (M1b) can flag degraded stages. Endpoint failures degrade the same way — a failed op must never crash the factory or a render.

Honesty rule: providers whose live probe failed are recorded unsupported above; multi-ref rows marked "wired — not probed" have code paths but no live evidence in this run.

# Local LLM Provider With Ollama

## Status

Implemented as an optional local provider for Milestone 9A.

## Purpose

Ollama can generate scripts, scene plans, metadata, thumbnail concepts, and read-only safety
summaries. The default remains the deterministic fake/rules provider, so normal development and
tests do not require Ollama, a network connection, or a downloaded model.

## Provider Boundary

`TextGenerationProvider` remains the application contract. `OllamaTextGenerationProvider` is an
adapter using Ollama's local HTTP API. Application services receive provider interfaces and do not
import Ollama-specific behavior.

Requests carry:

* Prompt and optional system prompt
* Model and model version
* Provider settings
* Timeout
* Optional cancellation token
* Seed where supported

Failures use typed exceptions for connection, timeout, missing model, malformed response,
cancellation, and invalid structured output. There is no silent fallback after an explicitly
selected Ollama request fails.

## Structured Outputs

Scene plans, metadata, and thumbnail concepts use JSON mode and strict Pydantic validation. Output
must reference the selected project inputs. Invalid JSON, unknown fields, or mismatched source IDs
are rejected before persistence.

Generation fingerprints include provider, model, model version, provider settings, prompt/schema
versions, system-prompt hash, and source input hashes. Identical valid outputs are reused before a
new provider request is made.

## Safety Boundary

The deterministic Content Safety and Rights Engine remains authoritative. Ollama may summarize an
existing safety report for a human reviewer, but it cannot create or modify findings, approvals,
rights records, publishing gates, blockers, or gate status.

## Local Setup

Install Ollama separately, then pull a model appropriate for the target laptop:

```powershell
ollama pull qwen3:8b
ollama serve
python -m ai_media_os.cli check-llm-provider --provider ollama --model qwen3:8b
python -m ai_media_os.cli test-llm-generate --provider ollama --model qwen3:8b --prompt "Write one sentence about local AI."
```

Select Ollama per command with `--provider ollama`, or set
`AI_MEDIA_OS_TEXT_PROVIDER_DEFAULT=ollama`. Keep the default `fake` when Ollama is not installed.

## Known Limitations

* Ollama and model files are not installed or managed by this repository.
* Output quality and speed depend on the selected model and local hardware.
* Cancellation is checked before a synchronous request; the standard-library transport cannot
  interrupt an HTTP request already in progress.
* No remote or paid LLM provider is included.
* No automatic model download, GPU scheduling, publishing, or autonomous safety decision is added.

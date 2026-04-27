# Custodian Prompts

## Two prompt-loading mechanisms

This repo has two intentionally separate prompt-loading systems. They serve different needs and should not be merged.

### 1. Custodian (this directory)

YAML files here are loaded via `custodian/prompt_loader.py` using `load_prompt(path, **vars)`.

The loader supports **lens composition**: a prompt YAML can declare a `lenses` list naming shared fragments under `lenses/<name>.yaml`. Each lens is rendered first with the call-site variables, and its resolved text is substituted into the main template as `${lens_name}`. This lets agents modulate tone or epistemological stance (e.g., kind-of-knowing level) per visit without duplicating full prompts.

Call sites: `custodian/agents.py`, `custodian/supersession_parser.py`, `custodian/silo_synthesis.py`.

### 2. Extraction and Clustering

Prompt content for extraction and clustering lives under `config/prompts.yaml` (and sibling configs), loaded via `config/config_loader.py`. The active prompt set is selected by `get_settings().prompt_preset`, which switches between provider variants (e.g., `gemini`, `anthropic`) whose phrasing differs for the same logical instruction.

Call sites: `extraction/prompts.py`, `clustering/prompts.py`.

## Why keep them separate

Custodian prompts need lens composition (per-visit modulation). Extraction and clustering prompts need provider-preset switching (prompt phrasing differs across LLM providers). Merging them would require one mechanism to handle both concerns, which adds complexity with no benefit.

## Adding a new custodian prompt

1. Drop a `.yaml` file in this directory with a `system_prompt` key (a `string.Template`-style template).
2. Optionally add a `lenses` list naming fragments from `lenses/`.
3. Reference it via `load_prompt(PROMPTS_DIR / "your_file.yaml", **vars)`.

See `custodian/agents.py` for examples of how existing prompts are loaded at module level.

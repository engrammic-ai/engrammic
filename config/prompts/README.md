# config/prompts/

Two separate prompt systems live under this directory.

---

## Custodian YAML prompts (`custodian/`)

Each file is a YAML document with the shape:

```yaml
lenses:               # optional list of lens fragment names
  - injection_defense
system_prompt: |-
  You are ... ${injection_defense}
```

**Loader:** `src/context_service/custodian/prompt_loader.py` — `load_prompt(path, **vars)`.

**How it works:**
1. Lens fragments are resolved first from `custodian/lenses/<name>.yaml` (each has a `text` key).
2. The resolved lens text is substituted into the main `system_prompt` template as `${<lens_name>}`.
3. Additional `**vars` are substituted via `string.Template.safe_substitute`.

**Prompts in this directory:**

| File | Purpose |
|------|---------|
| `fast_pass.yaml` | Brief cluster reconnaissance — outputs `FastPassObservation` |
| `deep_pass.yaml` | Full cluster analysis — outputs `DeepPassObservation` |
| `plan.yaml` | Custodian visit planning — produces a structured visit plan |
| `stitch.yaml` | Cross-cluster synthesis from child findings |
| `silo_synthesis.yaml` | Silo-scope summary generation |
| `supersession.yaml` | Determines whether a new claim supersedes a prior one |

**Lenses:**

| File | Purpose |
|------|---------|
| `lenses/injection_defense.yaml` | Shared fragment injected to resist prompt injection in user content |

**When to add a prompt here:** any new Custodian agent phase that requires a distinct LLM call with its own system prompt. Name the file after the pass type and add it to the relevant agent in `custodian/agents.py`.

---

## Extraction and Clustering prompts (`config/prompts.yaml`)

Extraction and clustering prompts are **not** stored under this directory. They live in `config/prompts.yaml` (a flat YAML file at the config root) and are loaded via `config_loader.py` with provider-preset routing.

**Loader:** `src/context_service/extraction/prompts.py` and `src/context_service/clustering/prompts.py`, both calling `load_config()` with a `prompt_preset` setting (default: `"gemini"`).

**How it works:**
1. `get_settings().prompt_preset` selects the active preset (e.g. `"gemini"`, `"groq"`).
2. The loader looks up `extraction.<preset>` or `clustering.<preset>` in `config/prompts.yaml`.
3. Falls back to the `gemini` preset if the selected preset is not present.

**When to add a prompt here:** when adding a new LLM provider preset for extraction or clustering, or tuning the system/user template for an existing preset. Edit `config/prompts.yaml` directly — do not add YAML files to this directory for those systems.

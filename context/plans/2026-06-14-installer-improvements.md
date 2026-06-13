# Installer Improvements Plan

**Date:** 2026-06-14
**Scope:** mcp-client installer UX and reliability
**Effort:** ~4 days

## Context

Review of `/home/novusedge/Projects/delta-prime/mcp-client` identified gaps in error handling, validation, and edge cases. Self-hosted flow is thorough but needs polish before wider distribution.

## Phase 1: Critical Validation (1.5 days)

### 1.1 Add disk space check with tier-aware estimates
**File:** `installer-cli/src/selfhost.rs`
**Why:** Models need significant disk. Silent failures during download frustrate users.

**Disk estimates by tier:**

| Tier | LLM Model | LLM Size | Embedding | Reranker | DBs/Other | Total |
|------|-----------|----------|-----------|----------|-----------|-------|
| lite | phi4-mini | ~2.4GB | nomic-embed-v1.5 ~270MB | none | ~2GB | **~5GB** |
| standard | gemma4:12b | ~8GB | nomic-embed-v2-moe ~700MB | bge-reranker-v2-m3 ~1GB | ~3GB | **~13GB** |
| pro | gemma4:26b | ~16GB | nomic-embed-v2-moe ~700MB | bge-reranker-v2-m3 ~1GB | ~4GB | **~22GB** |

Add 20% headroom buffer. Round up to:
- **lite**: 8GB minimum
- **standard**: 20GB minimum  
- **pro**: 30GB minimum

```rust
fn get_required_disk_gb(tier: Tier) -> u64 {
    match tier {
        Tier::Lite => 8,
        Tier::Standard => 20,
        Tier::Pro => 30,
    }
}

fn check_disk_space(path: &Path, tier: Tier) -> Result<()> {
    let available = fs2::available_space(path)? / (1024 * 1024 * 1024);
    let required = get_required_disk_gb(tier);
    if available < required {
        bail!("Need {}GB disk space for {} tier, only {}GB available", 
              required, tier, available);
    }
    Ok(())
}
```

Run after tier selection, before any downloads. Show breakdown:
```
Selected: standard tier
  LLM (gemma4:12b):     ~8GB
  Embeddings (TEI):     ~700MB
  Reranker (TEI):       ~1GB
  Databases + cache:    ~3GB
  Buffer:               ~7GB
  ─────────────────────────
  Total required:       20GB
  Available:            45GB ✓
```

### 1.2 Port conflict detection + custom port selection
**File:** `installer-cli/src/selfhost.rs`
**Why:** Services fail silently if ports already in use. Users should pick their own if defaults conflict.

**Default ports:**
| Port | Service |
|------|---------|
| 8000 | Engrammic API |
| 11434 | Ollama |
| 8080 | TEI embeddings |
| 8081/8082 | TEI reranker |
| 5432 | Postgres |
| 6333 | Qdrant |
| 7687 | Memgraph |
| 6379 | Redis |

**Flow:**
1. Check default ports
2. If conflict, offer to pick new port or skip (if service already running externally)
3. Store chosen ports in config, use in generated compose

```rust
struct PortConfig {
    api: u16,
    ollama: u16,
    tei_embed: u16,
    tei_rerank: u16,
    postgres: u16,
    qdrant: u16,
    memgraph: u16,
    redis: u16,
}

impl PortConfig {
    fn defaults() -> Self {
        Self { api: 8000, ollama: 11434, tei_embed: 8080, tei_rerank: 8081, 
               postgres: 5432, qdrant: 6333, memgraph: 7687, redis: 6379 }
    }
}

fn check_and_resolve_ports(defaults: PortConfig) -> Result<PortConfig> {
    let mut config = defaults;
    
    for (name, port, field) in [
        ("API", config.api, &mut config.api),
        ("Postgres", config.postgres, &mut config.postgres),
        // ... etc
    ] {
        if !check_port_available(*port) {
            println!("Port {} ({}) is in use.", port, name);
            let choice = prompt("Enter new port, or 'skip' to use existing service: ")?;
            if choice == "skip" {
                // Mark as external, don't start this container
            } else {
                *field = choice.parse()?;
            }
        }
    }
    Ok(config)
}
```

**UI example:**
```
Port Configuration
──────────────────
Service          Default    Status       Your Port
─────────────────────────────────────────────────────
API              8000       ✓ free       [8000]
Ollama           11434      ✓ free       [11434]
TEI Embeddings   8080       ✓ free       [8080]
TEI Reranker     8081       ✓ free       [8081]
Postgres         5432       ✗ IN USE     [    ]
Qdrant           6333       ✓ free       [6333]
Memgraph         7687       ✓ free       [7687]
Redis            6379       ✓ free       [6379]

Edit ports? [y/N]: y

Postgres (5432 in use):
  [1] Use different port: ____
  [2] Use external Postgres (already running)
  [3] Skip (I'll fix the conflict myself)
  
Choice: 2
  Host [localhost]: 
  Port [5432]: 
  User [engrammic]: 
  Password: ****

─────────────────────────────────────────────────────
Final configuration:
  API:        localhost:8000
  Ollama:     localhost:11434  
  TEI:        localhost:8080, localhost:8081
  Postgres:   localhost:5432 (external)
  Qdrant:     localhost:6333
  Memgraph:   localhost:7687
  Redis:      localhost:6379

Proceed? [Y/n]: 
```

**Quick mode:** `engrammic selfhost --accept-defaults` skips interactive port config, fails on conflicts.

**Generated compose respects chosen ports:**
```yaml
services:
  app:
    ports:
      - "${API_PORT:-8000}:8000"
  postgres:
    ports:
      - "${POSTGRES_PORT:-5432}:5432"
```

**Config saved to `.engrammic/ports.env`:**
```bash
API_PORT=8000
POSTGRES_PORT=5433
POSTGRES_EXTERNAL=true
POSTGRES_HOST=localhost
```

### 1.3 GPU/VRAM detection for standard/pro
**File:** `installer-cli/src/selfhost.rs`
**Why:** Standard (24GB) and Pro (48GB) recommend GPU. Check VRAM if GPU detected.

```rust
fn check_gpu() -> Option<GpuInfo> {
    // Try nvidia-smi first
    let output = Command::new("nvidia-smi")
        .args(["--query-gpu=memory.total", "--format=csv,noheader,nounits"])
        .output().ok()?;
    // Parse VRAM in MB
}
```

Show warning if:
- Standard tier + no GPU: "Standard tier works best with GPU (8GB+ VRAM). CPU-only will be slow."
- Pro tier + <16GB VRAM: "Pro tier recommends 16GB+ VRAM for gemma4:26b."

### 1.4 Existing Ollama detection
**File:** `installer-cli/src/selfhost.rs`
**Why:** User may have Ollama running outside Docker. Offer to reuse it.

```rust
fn detect_existing_ollama() -> Option<String> {
    // Check if Ollama is running on default port
    if let Ok(resp) = reqwest::blocking::get("http://localhost:11434/api/tags") {
        return Some("localhost:11434".into());
    }
    None
}
```

Prompt:
```
Detected existing Ollama at localhost:11434
Use existing Ollama instead of Docker container? [Y/n]
```

### 1.5 Improve Docker prerequisite errors
**File:** `installer-cli/src/selfhost.rs`
**Why:** Current errors say "Docker not found" but don't suggest fixes.

Add platform-specific hints:
- Linux: "Install via `curl -fsSL https://get.docker.com | sh`"
- macOS: "Install Docker Desktop from docker.com/products/docker-desktop"
- Windows: "Install Docker Desktop and enable WSL2 backend"

### 1.6 Fix memory detection fallback
**File:** `installer-cli/src/selfhost.rs`
**Why:** `get_available_memory_gb()` returns 0 on unsupported platforms.

Add Windows support via `sysinfo` crate, or warn explicitly.

## Phase 2: Error Messaging & YAML Fix (0.5 day)

### 2.1 Replace grep YAML parsing
**File:** `installer-cli/src/docker.rs:78-80`
**Why:** Current grep-based service detection breaks on comments/anchors.

Better approach: Use `docker compose config` to get normalized YAML:
```rust
fn get_compose_services(file: &Path) -> Result<Vec<String>> {
    let output = Command::new("docker")
        .args(["compose", "-f", file.to_str().unwrap(), "config", "--services"])
        .output()?;
    // Parse one service per line
}
```

### 2.2 Replace silent unwraps
**File:** `installer-cli/src/main.rs`
**Lines:** 147, 291, 303, 907

Replace `.unwrap_or_default()` with explicit warnings:
```rust
.unwrap_or_else(|e| {
    warn!("Config load failed: {e}, using defaults");
    Default::default()
})
```

### 2.3 TTY recovery hint
**File:** `installer-cli/src/main.rs:47`

When TTY not detected:
```
"Interactive mode required. If piping, use: curl -fsSL ... | bash -i"
```

### 2.4 License key clarity
**File:** `installer-cli/src/selfhost.rs:107-108`

Change prompt to:
```
"Enter license key (leave blank to configure later - app won't start without one):"
```

## Phase 3: Robustness (0.5 day)

### 3.1 Validate write permissions before install
**File:** `installer-cli/src/skills.rs`

Before proceeding:
```rust
fn validate_dest(path: &Path) -> Result<()> {
    std::fs::create_dir_all(path)?;
    let test_file = path.join(".write_test");
    std::fs::write(&test_file, "")?;
    std::fs::remove_file(test_file)?;
    Ok(())
}
```

### 3.2 Manifest partial failure handling
**File:** `installer-cli/src/manifest.rs`

Add `status: complete | partial` field. Only mark `complete` when full flow succeeds.

### 3.3 Download retry/resume
**File:** `installer-cli/src/selfhost.rs`
**Why:** Large model downloads can stall. Network timeouts frustrate users.

- Add timeout (30s idle, 10min total per file)
- Retry up to 3 times on failure
- Consider resume support via HTTP Range header for Ollama pulls

## Phase 4: Polish & Podman (1.5 days)

### 4.1 Podman support (documented, not auto-detected)
**Why:** Enterprise users want Podman but it has quirks (SELinux, network naming, GPU syntax). Don't auto-detect to avoid surprises.

**Approach:** Use `podman system service` for Docker-compatible socket:
```bash
# User runs this once
podman system service --time=0 unix:///tmp/podman.sock &
export DOCKER_HOST=unix:///tmp/podman.sock
```

Document in README, don't auto-detect. Compose files work as-is via socket.

**GPU adjustment for Podman:**
```yaml
# Docker
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: all
          capabilities: [gpu]

# Podman (CDI)
devices:
  - nvidia.com/gpu=all
```

Add `--podman` flag that:
1. Skips Docker daemon check
2. Uses Podman GPU syntax in generated compose
3. Adds `:Z` suffix to volumes for SELinux

### 4.2 Windows progress feedback
**File:** `installer-cli/assets/install.ps1`

Add progress output between downloads:
```powershell
Write-Host "Downloading installer (1/2)..."
# download
Write-Host "Downloading skills bundle (2/2)..."
```

### 4.3 Ctrl+C TTY restore
**File:** `installer-cli/src/main.rs:93-96`

```rust
ctrlc::set_handler(|| {
    crossterm::terminal::disable_raw_mode().ok();
    std::process::exit(130);
})?;
```

### 4.4 README improvements
**File:** `installer/README.md`

Add:
- Link to skills catalog
- Podman setup instructions
- Offline/airgapped setup guide (brief)

## Deferred

- **Full Podman auto-detection**: Too many edge cases (SELinux, rootless networking). Document manual setup instead.
- **Offline mode**: Lower priority until enterprise asks
- **Status command location clarity**: Nice-to-have

## Success Criteria

1. `engrammic selfhost` on fresh Ubuntu 22.04 with 8GB RAM, 15GB disk gives clear error before downloading anything
2. Port conflicts detected and reported with actionable message
3. GPU/VRAM check warns on standard/pro without adequate hardware
4. All `.unwrap_or_default()` replaced with logged fallbacks
5. `docker compose config` used instead of grep for YAML parsing
6. Windows install shows progress during download
7. Podman works via documented socket approach

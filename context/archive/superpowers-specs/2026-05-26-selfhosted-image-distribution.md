# Self-Hosted Image Distribution

**Status:** Draft (reviewed)
**Author:** Claude
**Date:** 2026-05-26

## Goal

Enable self-hosted customers to pull Docker images from a public registry while protecting source code through bytecode compilation.

## Background

Current state:
- Docker images built via Cloud Build, pushed to private GCP Artifact Registry
- Images contain .py source files (readable if container is inspected)
- Self-hosted users cannot pull images without GCP credentials

Desired state:
- Public GCP Artifact Registry for self-hosted images
- Bytecode-compiled images (.pyc) protect source code
- License validation remains the primary access control

## Design

### Registry Structure

```
europe-north1-docker.pkg.dev/engrammic/
  engrammic/           # existing, private (internal deploys)
    engrammic-api
    engrammic-beacon
    engrammic-dagster
  selfhosted/          # new, public
    engrammic-api
    engrammic-beacon
```

**IAM:** `selfhosted` repository gets `roles/artifactregistry.reader` for `allUsers`.

### Image Variants

| Image | Internal | Self-Hosted |
|-------|----------|-------------|
| engrammic-api | .py source, debug-friendly | .pyc bytecode only |
| engrammic-beacon | .py source | .pyc bytecode only |
| engrammic-dagster | .py source | Not distributed |

**Dagster exclusion:** SAGE (Custodian, Synthesizer, Groundskeeper) requires LLM API keys and runs as background jobs. Self-hosted deployments operate in "passive mode" without SAGE. The dagster service will be removed from `docker-compose.selfhosted.yml`.

### Bytecode Compilation

```dockerfile
# Compile all .py to .pyc (in-place with -b flag)
RUN python -m compileall -b -q /app/src && \
    find /app/src -name "*.py" -type f -delete
```

**Alembic migrations:** Keep as .py source files. Migrations are not IP-sensitive and need to be readable for debugging failed upgrades. Only compile `/app/src`.

**Trade-offs:**
- .pyc is decompilable with tools like pycdc/uncompyle6
- Adds friction, prevents casual source browsing
- License validation is the real protection
- Alternative (Cython) adds build complexity, not worth it for MVP

### Healthchecks

Use Python-based healthchecks (not curl) since slim images don't include curl:

```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
```

Update `docker-compose.selfhosted.yml` to use exec-based healthchecks:

```yaml
healthcheck:
  test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
  interval: 30s
  timeout: 5s
  retries: 3
```

### Tagging Strategy

```
selfhosted/engrammic-api:v0.1.0           # semver release (recommended)
selfhosted/engrammic-api:v0.1.0-abc1234   # semver + commit (debugging)
```

**No `latest` tag** for self-hosted images. Customers must pin to semver tags to avoid accidental upgrades.

### Version Synchronization

All artifacts share a single version source: `src/context_service/__init__.py` contains `__version__`.

On release:
1. Bump version in `__init__.py`
2. Tag commit with `v{version}`
3. Push to `release` branch triggers:
   - PyPI publish (engrammic-primitives)
   - Self-hosted image publish (API + beacon)

The publish workflow reads version from the Python source, ensuring consistency.

### Upgrade Guidance

Self-hosted customers upgrade via:

```bash
cd engrammic
docker compose pull
docker compose up -d
```

**Version check:** The API container checks `/versions` endpoint on startup and every 24h, logging warnings for deprecated versions (shipped in phase 2).

**Migration handling:** If schema changes require migrations:
1. Release notes will document migration steps
2. Container logs error if migrations needed but not run
3. Customer runs: `docker compose exec api alembic upgrade head`

### CI/CD

**New workflow:** `.github/workflows/publish-selfhosted.yml`

**Triggers:**
- Push to `release` branch (same as PyPI publishing)
- Manual workflow_dispatch with version input

**Jobs:**
1. Build selfhosted API image with bytecode compilation
2. Build selfhosted beacon image with bytecode compilation
3. Push to public AR with version tags
4. Verify images are publicly pullable

**Secrets required:**
- Existing `GCP_WORKLOAD_IDENTITY_PROVIDER`
- Existing `GCP_SERVICE_ACCOUNT`

### File Changes

**New files:**
```
docker/
  Dockerfile.selfhosted.api      # bytecode-compiled API
  Dockerfile.selfhosted.beacon   # bytecode-compiled beacon

.github/workflows/
  publish-selfhosted.yml         # publish to public AR
```

**Modified files:**
```
docker/docker-compose.selfhosted.yml
  - Update image refs: europe-north1-docker.pkg.dev/engrammic/selfhosted/engrammic-api:v0.1.0
  - Remove dagster service
  - Fix healthchecks to use python instead of curl
```

### Infra Changes (Manual)

1. Create `selfhosted` repository in GCP Artifact Registry (europe-north1)
2. Grant `allUsers` the `roles/artifactregistry.reader` role on `selfhosted` repo only
3. Verify public pull works: `docker pull europe-north1-docker.pkg.dev/engrammic/selfhosted/engrammic-api:v0.1.0`

## Security Considerations

1. **Source protection:** Bytecode adds friction but is not cryptographic protection. License validation + legal terms are the real controls.

2. **Supply chain:** Images are built in Cloud Build (trusted environment), signed commits only.

3. **Vulnerability scanning:** Same scanning as internal images (if enabled in AR).

4. **No secrets in images:** License keys are runtime env vars, not baked in.

5. **Public vs private repos:** Only `selfhosted/` is public. Internal `engrammic/` repo remains private.

## Out of Scope

- Docker Hub mirroring (deferred, adds maintenance burden)
- Cython compilation (complexity vs. benefit)
- Image signing with cosign/sigstore (future consideration)
- ARM64 builds (can add later if requested)
- Multi-region registries (customers can use GCP's geo-replication if needed)

## Success Criteria

1. Self-hosted user can `docker pull` without GCP credentials
2. Pulled image contains .pyc files, no .py source in `/app/src`
3. Alembic migrations remain as .py for debuggability
4. Image runs correctly with valid license key
5. Image refuses to start without valid license key
6. Version check against beacon works from self-hosted container
7. No dagster service in self-hosted compose
8. Healthchecks work without curl

## Implementation Plan

1. Create `Dockerfile.selfhosted.api` with bytecode compilation (keep alembic as .py)
2. Create `Dockerfile.selfhosted.beacon` with bytecode compilation
3. Update `docker-compose.selfhosted.yml`:
   - Change image refs to `selfhosted/` registry
   - Remove dagster service
   - Fix healthchecks to use python
4. Create `publish-selfhosted.yml` workflow
5. Create `selfhosted` AR repository (manual, GCP Console)
6. Grant public read access (manual, IAM)
7. Test full flow: build, push, pull, run with license
8. Update quickstart docs with correct image paths

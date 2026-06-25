# Benchmark VM Setup Reference

Quick reference for setting up the BEAM benchmark environment.

## Infrastructure

VMs managed by Pulumi (stack: `benchmark`):
- `engrammic-benchmark-benchmark-devbox` - runs somnus, Engrammic services
- `engrammic-benchmark-benchmark-gpu` - runs TEI embeddings/reranker

### Key config (infra/Pulumi.benchmark.yaml)

```yaml
benchmark:use_spot: "false"  # MUST be false for long runs
benchmark:benchmark_devbox_instance_type: n2-standard-16
```

## Quick Start (from scratch)

```bash
# 1. Ensure VMs are non-preemptible and running
cd infra && pulumi stack select benchmark
pulumi up  # if config changed

# 2. SSH to devbox
gcloud compute ssh engrammic-benchmark-benchmark-devbox --zone=us-west1-b --tunnel-through-iap

# 3. On devbox: start services
cd ~/benchmark
sudo docker compose up -d

# 4. On GPU VM: start TEI (use turing-1.2, NOT 1.5 - has URL bug)
gcloud compute ssh engrammic-benchmark-benchmark-gpu --zone=us-west1-b --tunnel-through-iap
sudo docker run -d --gpus all --network host --name tei-embeddings \
  ghcr.io/huggingface/text-embeddings-inference:turing-1.2 \
  --model-id BAAI/bge-m3 --pooling cls --port 8080

sudo docker run -d --gpus all --network host --name tei-reranker \
  ghcr.io/huggingface/text-embeddings-inference:turing-1.2 \
  --model-id BAAI/bge-reranker-base --port 8081

# 5. Run benchmark (back on devbox)
cd ~/somnus
~/.local/bin/uv run somnus bench run beam --scale 1M --engrammic-url http://localhost:8000

# For overnight runs:
nohup ~/.local/bin/uv run somnus bench run beam --scale 1M --engrammic-url http://localhost:8000 > beam-1m.log 2>&1 &
```

## Troubleshooting

### TEI fails with "relative URL without a base"
Use `turing-1.2` image, not `1.5` or `latest`. Bug in hf-hub crate.

### Postgres "directory not empty" error
```bash
sudo rm -rf /mnt/postgres/data/*
```
Or use docker volume instead of host mount.

### Qdrant dimension mismatch
```bash
curl -X DELETE http://localhost:6333/collections/context_vectors
sudo docker restart engrammic-app
```

### App can't resolve hostnames
Docker compose services need to be on same network. Check `docker compose ps`.

## Files

- Devbox docker-compose: `~/benchmark/docker-compose.yml`
- Somnus repo: `~/somnus/`
- Results DB: `~/somnus/results/benchmarks.db`
- SSH keys: copied from local `~/.ssh/id_ed25519` for GitHub access

## GPU VM IPs

After Pulumi recreate, IPs change. Check:
```bash
pulumi stack output gpu_ip
```
Update TEI_URL in docker-compose.yml if needed.

## Fast Seeding

Bypasses MCP for 10-50x speedup. Use for large scale benchmarks.

```bash
# Fast seed (uses TEI for embeddings)
cd ~/somnus
nohup ~/.local/bin/uv run somnus bench seed-fast beam --scale 1M --silo beam-1m-fast \
  --tei-url http://10.0.1.7:8080 > seed-fast.log 2>&1 &

# Then run eval with skip-seed
nohup ~/.local/bin/uv run somnus bench run beam --scale 1M --skip-seed --silo beam-1m-fast \
  --engrammic-url http://localhost:8000 --parallel --max-concurrent 6 > eval-1m.log 2>&1 &
```

Key flags:
- `--embed-batch 32` (default for TEI, 200 for Vertex)
- `--embed-concurrency 10` (parallel embedding requests)
- `--qdrant-batch 2000` (points per upsert)

## Logs

```bash
# Fast seeding progress
tail -f ~/somnus/seed-fast.log

# Eval progress
tail -f ~/somnus/eval-1m.log

# GPU usage (from devbox)
gcloud compute ssh engrammic-benchmark-benchmark-gpu --zone=us-west1-b --command="nvidia-smi"
```

## Estimated Times

- TEI model download: ~2 min each
- BEAM 100K seeding (MCP): ~1 min per question
- BEAM 1M fast seeding: ~11 hours (46k batches @ ~850ms/batch)
- BEAM 1M eval: ~4-6 hours (700 questions, parallelized)

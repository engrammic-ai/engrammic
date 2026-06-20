"""Benchmark environment Pulumi entrypoint.

Spin up a fully self-hosted benchmark environment with GPU inference.

Usage:
    cd infra
    pulumi stack select benchmark
    pulumi up --config-file Pulumi.benchmark.yaml

    # Or with different GPU tier:
    pulumi up --config benchmark:gpu_tier=l4 --config benchmark:llm_model=qwen-14b

Configuration options (via --config or Pulumi.benchmark.yaml):
    benchmark:gpu_tier        - t4 (16GB), l4 (24GB), a100-40 (40GB)
    benchmark:embedding_model - bge-m3, nomic
    benchmark:reranker_model  - bge-reranker-base, bge-reranker-v2-m3
    benchmark:llm_model       - gemini-3.5-flash (via Vertex AI, uses SA auth)
    benchmark:use_spot        - true/false (spot instances are cheaper but can be preempted)
    benchmark:tailscale       - true/false (enable Tailscale for SSH access)

LLM access:
    Uses Vertex AI with service account auth (no local vLLM).
    Endpoint: https://aiplatform.googleapis.com/v1/projects/PROJECT/locations/global/publishers/google/models/MODEL:generateContent

After deployment:
    # SSH to dev-box
    tailscale ssh benchmark-dev-box

    # Run benchmark
    cd ~/Projects/delta-prime/somnus
    uv run somnus bench run beam --engrammic-url http://benchmark-dev-box:8000 \\
        --parallel --max-concurrent 8 -o results/beam-1m.json
"""

import pulumi

from components.benchmark import BenchmarkEnvironment

# Create the benchmark environment
benchmark = BenchmarkEnvironment("benchmark")

# Export outputs
pulumi.export("gpu_ip", benchmark.gpu.internal_ip)
pulumi.export("devbox_ip", benchmark.devbox.internal_ip)
pulumi.export("tei_embeddings_url", pulumi.Output.concat("http://", benchmark.gpu.internal_ip, ":8080"))
pulumi.export("tei_reranker_url", pulumi.Output.concat("http://", benchmark.gpu.internal_ip, ":8081"))
pulumi.export("llm_endpoint", "https://aiplatform.googleapis.com/v1/projects/engrammic/locations/global/publishers/google/models/gemini-3.5-flash:generateContent")
pulumi.export("engrammic_url", pulumi.Output.concat("http://", benchmark.devbox.internal_ip, ":8000"))
pulumi.export("dagster_url", pulumi.Output.concat("http://", benchmark.devbox.internal_ip, ":3002"))

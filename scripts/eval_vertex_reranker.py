#!/usr/bin/env python3
"""Quick evaluation of Vertex AI semantic reranker for entailment cases."""

import asyncio
import os

import litellm

# Test cases: (query, documents, expected_top_doc_index)
# Each tests whether the reranker understands entailment, not just similarity
TEST_CASES = [
    {
        "name": "rejected_equivalence",
        "query": "what was rejected?",
        "documents": [
            "The motion for summary judgment was granted in favor of the defendant.",
            "Failure to warn theory is no longer viable after the court's ruling.",
            "The plaintiff filed an amended complaint on Tuesday.",
            "Defense counsel requested a continuance which was accepted.",
        ],
        "expected_top": 1,  # "no longer viable" = rejected
        "rationale": "'no longer viable' semantically means rejected",
    },
    {
        "name": "negation_understanding",
        "query": "what failed?",
        "documents": [
            "The authentication succeeded after retry.",
            "The database connection was established successfully.",
            "The payment processing did not complete as expected.",
            "All tests passed in the CI pipeline.",
        ],
        "expected_top": 2,  # "did not complete" = failed
        "rationale": "'did not complete' is a form of failure",
    },
    {
        "name": "causal_entailment",
        "query": "why did the system crash?",
        "documents": [
            "The system was updated to version 2.5 yesterday.",
            "Memory usage exceeded 95% causing the OOM killer to terminate processes.",
            "The system has been running for 45 days.",
            "Disk space is at 60% capacity.",
        ],
        "expected_top": 1,  # OOM = cause of crash
        "rationale": "OOM killer terminating processes causes crashes",
    },
    {
        "name": "temporal_equivalence",
        "query": "what was postponed?",
        "documents": [
            "The meeting was cancelled entirely.",
            "The deployment will proceed as scheduled on Friday.",
            "The release was pushed back to next quarter.",
            "The feature shipped ahead of schedule.",
        ],
        "expected_top": 2,  # "pushed back" = postponed
        "rationale": "'pushed back' means postponed",
    },
    {
        "name": "approval_status",
        "query": "what got approved?",
        "documents": [
            "The PR is still under review.",
            "The budget request was denied by finance.",
            "Leadership gave the green light on the new initiative.",
            "The proposal is pending stakeholder feedback.",
        ],
        "expected_top": 2,  # "green light" = approved
        "rationale": "'gave the green light' means approved",
    },
]


async def run_rerank(model: str, query: str, documents: list[str]) -> list[dict]:
    """Run reranking and return results."""
    response = await litellm.arerank(
        model=model,
        query=query,
        documents=documents,
        top_n=len(documents),
    )
    return [
        {"index": r["index"], "score": r["relevance_score"], "text": documents[r["index"]][:60]}
        for r in response.results
    ]


async def evaluate_model(model: str) -> dict:
    """Evaluate a reranker model on all test cases."""
    results = {"model": model, "passed": 0, "failed": 0, "details": []}

    for tc in TEST_CASES:
        try:
            ranked = await run_rerank(model, tc["query"], tc["documents"])
            top_index = ranked[0]["index"]
            passed = top_index == tc["expected_top"]

            results["details"].append(
                {
                    "name": tc["name"],
                    "query": tc["query"],
                    "passed": passed,
                    "expected": tc["expected_top"],
                    "got": top_index,
                    "expected_doc": tc["documents"][tc["expected_top"]][:50],
                    "got_doc": tc["documents"][top_index][:50],
                    "scores": [(r["index"], round(r["score"], 3)) for r in ranked],
                }
            )

            if passed:
                results["passed"] += 1
            else:
                results["failed"] += 1

        except Exception as e:
            results["details"].append(
                {
                    "name": tc["name"],
                    "error": str(e),
                }
            )
            results["failed"] += 1

    return results


def print_results(results: dict) -> None:
    """Print evaluation results."""
    print(f"\n{'=' * 60}")
    print(f"Model: {results['model']}")
    print(f"Passed: {results['passed']}/{results['passed'] + results['failed']}")
    print(f"{'=' * 60}\n")

    for detail in results["details"]:
        if "error" in detail:
            print(f"[ERROR] {detail['name']}: {detail['error']}")
            continue

        status = "[PASS]" if detail["passed"] else "[FAIL]"
        print(f"{status} {detail['name']}")
        print(f"  Query: {detail['query']}")
        if not detail["passed"]:
            print(f"  Expected: [{detail['expected']}] {detail['expected_doc']}...")
            print(f"  Got:      [{detail['got']}] {detail['got_doc']}...")
        print(f"  Scores: {detail['scores']}")
        print()


async def main():
    # Ensure Vertex AI credentials are available
    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") and not os.environ.get(
        "GOOGLE_CLOUD_PROJECT"
    ):
        print("Warning: GOOGLE_APPLICATION_CREDENTIALS or GOOGLE_CLOUD_PROJECT not set")
        print("Make sure you're authenticated with gcloud or have credentials configured\n")

    models_to_test = [
        "vertex_ai/semantic-ranker-default@latest",
        # "vertex_ai/semantic-ranker-fast@latest",  # uncomment to compare
    ]

    for model in models_to_test:
        print(f"Testing {model}...")
        results = await evaluate_model(model)
        print_results(results)


if __name__ == "__main__":
    asyncio.run(main())

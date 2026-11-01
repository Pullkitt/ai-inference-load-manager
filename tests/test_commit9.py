"""
tests/test_commit9.py
─────────────────────
Unit and integration tests for Commit 9 (Locust Load Testing Suite & Documentation):
  1. locustfile.py file existence, valid syntax, user classes, domain generators, and shapes.
  2. scripts/run_benchmarks.py benchmark runner and report generation functions.
  3. README.md complete architectural documentation, API docs, and execution guides.
  4. BENCHMARK_REPORT.md auto-generated performance evaluation table verification.
"""

import os
import sys
import unittest

# Ensure root workspace directory is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestCommit9LocustAndDocumentation(unittest.TestCase):

    def setUp(self):
        self.root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.locust_path = os.path.join(self.root_dir, "locustfile.py")
        self.benchmark_script_path = os.path.join(self.root_dir, "scripts", "run_benchmarks.py")
        self.readme_path = os.path.join(self.root_dir, "README.md")
        self.benchmark_report_path = os.path.join(self.root_dir, "BENCHMARK_REPORT.md")

    def test_locustfile_exists_and_defines_scenarios(self):
        """Verify locustfile.py exists and defines all 4 required evaluation scenarios."""
        self.assertTrue(os.path.exists(self.locust_path), "locustfile.py must exist in project root")

        with open(self.locust_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check for core user classes
        self.assertIn("class BaseInferenceUser", content)
        self.assertIn("class LowLoadUser", content)
        self.assertIn("class MediumLoadUser", content)
        self.assertIn("class HighLoadUser", content)
        self.assertIn("class FailureScenarioUser", content)
        self.assertIn("class InferenceUser", content)
        self.assertIn("class SRSBenchmarkShape", content)

        # Check for domain payload generators
        self.assertIn("generate_iot_payload", content)
        self.assertIn("generate_mobile_media_payload", content)
        self.assertIn("generate_geospatial_payload", content)
        self.assertIn("generate_ai_nlp_payload", content)

        # Check for HTTP status code handling (200, 202, 429, 503)
        self.assertIn("response.status_code == 200", content)
        self.assertIn("response.status_code == 202", content)
        self.assertIn("response.status_code == 429", content)
        self.assertIn("response.status_code == 503", content)

    def test_benchmark_script_and_report_generator(self):
        """Verify scripts/run_benchmarks.py exists and report formatting functions work."""
        self.assertTrue(os.path.exists(self.benchmark_script_path), "scripts/run_benchmarks.py must exist")

        from scripts.run_benchmarks import BenchmarkRunner, format_markdown_report

        runner = BenchmarkRunner("http://localhost:8000")
        self.assertEqual(runner.base_url, "http://localhost:8000")
        self.assertEqual(len(runner.domains), 4)

        # Verify Markdown report generator formats all scenarios
        sample_results = [
            {"scenario": "1. Low Load", "total_requests": 20, "fast_ratio": 0.50, "concurrency": 10, "elapsed_seconds": 1.0, "throughput_rps": 20.0, "status_200": 10, "status_202": 10, "status_429": 0, "status_503": 0, "status_other": 0, "p50_ms": 140.0, "p95_ms": 180.0, "p99_ms": 190.0, "cb_state": "CLOSED", "cb_trips": 0, "routing_reasons": {}},
            {"scenario": "2. Medium Load", "total_requests": 100, "fast_ratio": 0.70, "concurrency": 25, "elapsed_seconds": 3.0, "throughput_rps": 33.3, "status_200": 35, "status_202": 65, "status_429": 0, "status_503": 0, "status_other": 0, "p50_ms": 155.0, "p95_ms": 205.0, "p99_ms": 230.0, "cb_state": "CLOSED", "cb_trips": 0, "routing_reasons": {}},
            {"scenario": "3. High Load / Burst", "total_requests": 500, "fast_ratio": 0.80, "concurrency": 50, "elapsed_seconds": 8.0, "throughput_rps": 62.5, "status_200": 45, "status_202": 50, "status_429": 365, "status_503": 40, "status_other": 0, "p50_ms": 15.0, "p95_ms": 240.0, "p99_ms": 275.0, "cb_state": "CLOSED", "cb_trips": 0, "routing_reasons": {}},
            {"scenario": "4. Failure Test", "total_requests": 100, "fast_ratio": 0.90, "concurrency": 20, "elapsed_seconds": 3.0, "throughput_rps": 33.3, "status_200": 0, "status_202": 100, "status_429": 0, "status_503": 0, "status_other": 0, "p50_ms": 10.0, "p95_ms": 20.0, "p99_ms": 25.0, "cb_state": "OPEN", "cb_trips": 1, "routing_reasons": {}}
        ]
        sample_idemp = {"total_requests": 50, "fresh_latency_ms": 150.0, "avg_cache_latency_ms": 3.5, "cache_hits": 49, "speedup_factor": 42.8}

        report_md = format_markdown_report(sample_results, sample_idemp)
        self.assertIn("1. Low Load", report_md)
        self.assertIn("2. Medium Load", report_md)
        self.assertIn("3. High Load / Burst", report_md)
        self.assertIn("4. Failure Test", report_md)
        self.assertIn("PASSED", report_md)

    def test_readme_comprehensive_documentation(self):
        """Verify README.md contains architectural sections, Locust guide, API reference and credits."""
        self.assertTrue(os.path.exists(self.readme_path), "README.md must exist in project root")

        with open(self.readme_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Architecture & Design
        self.assertIn("AI Inference Load Management Service", content)
        self.assertIn("Step 1: Authentication & Rate Limiting", content)
        self.assertIn("Step 2: SHA-256 Idempotency Engine", content)
        self.assertIn("Step 3: Global Queue Depth & Backpressure", content)
        self.assertIn("Step 4: Routing Decision & Circuit Breaker", content)
        self.assertIn("Circuit Breaker State Machine", content)

        # Domain Schemas
        self.assertIn("`iot`", content)
        self.assertIn("`mobile_media`", content)
        self.assertIn("`geospatial`", content)
        self.assertIn("`ai_nlp`", content)

        # Locust & Benchmarks
        self.assertIn("locustfile.py", content)
        self.assertIn("LowLoadUser", content)
        self.assertIn("MediumLoadUser", content)
        self.assertIn("HighLoadUser", content)
        self.assertIn("FailureScenarioUser", content)
        self.assertIn("run_benchmarks.py", content)

        # Academic Credits
        self.assertIn("University of Petroleum and Energy Studies", content)
        self.assertIn("Dr. A Sai Rao", content)
        self.assertIn("Pulkit Jain", content)
        self.assertIn("500121477", content)

    def test_benchmark_report_file_exists_and_valid(self):
        """Verify BENCHMARK_REPORT.md exists and contains the performance evaluation results."""
        self.assertTrue(os.path.exists(self.benchmark_report_path), "BENCHMARK_REPORT.md must exist")

        with open(self.benchmark_report_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("Workload Scenarios Performance Summary", content)
        self.assertIn("Architectural Invariants Verification", content)
        self.assertIn("Idempotency & Deduplication Performance", content)
        self.assertIn("Key Engineering Conclusions", content)


if __name__ == "__main__":
    unittest.main()


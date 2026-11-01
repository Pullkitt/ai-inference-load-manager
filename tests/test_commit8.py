"""
tests/test_commit8.py
─────────────────────
Unit tests for Commit 8 (Live Monitoring Dashboard):
  1. Static HTML dashboard file existence and structure verification
  2. GET / and GET /dashboard routing returns 200 with text/html
  3. Key UI components present in index.html (Circuit Breaker badge, Telemetry cards,
     Fault Injection button, Idempotency Demo button, and Traffic Simulator panel)
"""

import os
import sys
import unittest

# Ensure root workspace directory is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from app.main import app


class TestCommit8Dashboard(unittest.TestCase):

    def setUp(self):
        self.static_dir = os.path.join(os.path.dirname(__file__), "..", "app", "static")
        self.index_path = os.path.join(self.static_dir, "index.html")

    def test_dashboard_file_exists_and_contains_core_elements(self):
        """Verify index.html exists and contains the required UI elements."""
        self.assertTrue(os.path.exists(self.index_path), "index.html must exist in app/static")

        with open(self.index_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check for core ops-tool components with utilitarian labels
        self.assertIn("System status", content)
        self.assertIn("Circuit breaker", content)
        self.assertIn("Fast model slots in use", content)
        self.assertIn("Queue depth", content)
        self.assertIn("Latency p50 / p95", content)
        self.assertIn("Duplicate requests served from cache", content)
        self.assertIn("Inject fast model faults", content)
        self.assertIn("Run duplicate request test", content)
        self.assertIn("Recent requests", content)

    def test_no_emojis_in_dashboard(self):
        """Verify that all AI-cliché emojis have been stripped from the dashboard."""
        with open(self.index_path, "r", encoding="utf-8") as f:
            content = f.read()

        banned_emojis = ["⚡", "⚙", "🚀", "💥", "♻", "🟢", "🟡", "🔴", "🧹", "📋", "🔥", "✨"]
        for emoji in banned_emojis:
            self.assertNotIn(emoji, content, f"Banned emoji '{emoji}' found in index.html")

    def test_dashboard_route_serves_html(self):
        """Verify GET / and GET /dashboard endpoints return HTML with 200 OK."""
        from unittest.mock import AsyncMock, patch

        with patch("app.main.connect_mongodb", new_callable=AsyncMock), \
             patch("app.main.connect_redis", new_callable=AsyncMock), \
             patch("app.main.disconnect_mongodb", new_callable=AsyncMock), \
             patch("app.main.disconnect_redis", new_callable=AsyncMock), \
             patch("app.crud.users.ensure_indexes", new_callable=AsyncMock), \
             patch("app.crud.inference.ensure_indexes", new_callable=AsyncMock), \
             patch("app.main.get_db"):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp_root = client.get("/")
                self.assertEqual(resp_root.status_code, 200)
                self.assertIn("text/html", resp_root.headers.get("content-type", ""))
                self.assertIn("AI Inference Load Management", resp_root.text)

                resp_alias = client.get("/dashboard")
                self.assertEqual(resp_alias.status_code, 200)
                self.assertIn("text/html", resp_alias.headers.get("content-type", ""))


if __name__ == "__main__":
    unittest.main()

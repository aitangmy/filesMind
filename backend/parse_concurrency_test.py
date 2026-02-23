import asyncio
import os
import sys
import unittest
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse_concurrency as pc  # noqa: E402


class ParseConcurrencyPolicyTests(unittest.TestCase):
    def test_compute_recommended_parse_limit_by_thermal_level(self):
        base = 4
        self.assertEqual(pc.compute_recommended_parse_limit(base, {"thermal_level": "nominal"}), 4)
        self.assertEqual(pc.compute_recommended_parse_limit(base, {"thermal_level": "fair"}), 3)
        self.assertEqual(pc.compute_recommended_parse_limit(base, {"thermal_level": "serious"}), 2)
        self.assertEqual(pc.compute_recommended_parse_limit(base, {"thermal_level": "critical"}), 1)

    def test_compute_recommended_parse_limit_with_low_power_mode(self):
        base = 4
        state = {"thermal_level": "nominal", "low_power_mode": True}
        self.assertEqual(pc.compute_recommended_parse_limit(base, state), 2)


class AdaptiveParseLimiterTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_runtime_updates_limit(self):
        limiter = pc.AdaptiveParseLimiter(base_limit=4, refresh_interval_seconds=1.0)

        snapshot = {
            "platform": "macos",
            "thermal_level": "serious",
            "cpu_speed_limit": 68,
            "low_power_mode": False,
        }
        with patch.object(pc, "snapshot_macos_runtime_state", return_value=snapshot):
            metrics = await limiter.refresh_runtime_if_needed(force=True)

        self.assertEqual(limiter.current_limit, 2)
        self.assertEqual(metrics["current_limit"], 2)
        self.assertEqual(metrics["runtime"]["thermal_level"], "serious")

    async def test_slot_respects_dynamic_limit(self):
        limiter = pc.AdaptiveParseLimiter(base_limit=3, refresh_interval_seconds=1.0)

        snapshot = {
            "platform": "macos",
            "thermal_level": "critical",
            "cpu_speed_limit": 45,
            "low_power_mode": False,
        }
        with patch.object(pc, "snapshot_macos_runtime_state", return_value=snapshot):
            await limiter.refresh_runtime_if_needed(force=True)

        max_inflight = 0
        lock = asyncio.Lock()

        async def worker():
            nonlocal max_inflight
            async with limiter.slot():
                async with lock:
                    max_inflight = max(max_inflight, limiter.snapshot()["inflight"])
                await asyncio.sleep(0.02)

        await asyncio.gather(*(worker() for _ in range(4)))
        self.assertEqual(limiter.current_limit, 1)
        self.assertEqual(max_inflight, 1)

    async def test_refresh_runtime_prefers_runtime_hint(self):
        limiter = pc.AdaptiveParseLimiter(base_limit=4, refresh_interval_seconds=1.0)

        hint = {
            "platform": "macos",
            "thermal_level": "critical",
            "cpu_speed_limit": 40,
            "low_power_mode": False,
            "source": "desktop_hint",
            "timestamp_ms": 123456789,
        }
        fallback_snapshot = {
            "platform": "macos",
            "thermal_level": "nominal",
            "cpu_speed_limit": 100,
            "low_power_mode": False,
            "source": "pmset",
        }

        with patch.object(pc, "get_runtime_hint", return_value=hint), patch.object(
            pc, "snapshot_macos_runtime_state", return_value=fallback_snapshot
        ) as fallback:
            metrics = await limiter.refresh_runtime_if_needed(force=True)

        self.assertEqual(limiter.current_limit, 1)
        self.assertEqual(metrics["runtime"]["source"], "desktop_hint")
        fallback.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)

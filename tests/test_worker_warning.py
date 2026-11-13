"""Ko'p worker rejimida startup ogohlantirishi testlari.

Talab: ``WEB_CONCURRENCY`` yoki ``--workers N`` bilan ishga tushirilsa,
startupda rate limiter va per-user lock jarayonlararo umumiy emasligi
haqida aniq WARNING log chiqishi kerak.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("BOT_TOKEN", "")
os.environ.setdefault("SUPABASE_URL", "")
os.environ.setdefault("SUPABASE_KEY", "")

from fastapi.testclient import TestClient  # noqa: E402

from api import server  # noqa: E402


def _clean_env() -> dict[str, str]:
    """Worker haqidagi barcha muhit o'zgaruvchilarini bo'shatadi."""
    return {name: "" for name in server.WORKER_ENV_VARS}


class WorkerCountTest(unittest.TestCase):
    """Worker sonini aniqlash: env va CLI argumentlari."""

    def test_env_variable_is_detected(self) -> None:
        with mock.patch.dict(os.environ, {**_clean_env(), "WEB_CONCURRENCY": "4"}):
            with mock.patch.object(sys, "argv", ["python", "-m", "uvicorn"]):
                self.assertEqual(server.worker_process_count(), 4)

    def test_gunicorn_env_is_detected(self) -> None:
        with mock.patch.dict(os.environ, {**_clean_env(), "GUNICORN_WORKERS": "3"}):
            with mock.patch.object(sys, "argv", ["gunicorn", "api.server:app"]):
                self.assertEqual(server.worker_process_count(), 3)

    def test_uvicorn_workers_flag_is_detected(self) -> None:
        with mock.patch.dict(os.environ, _clean_env()):
            with mock.patch.object(
                sys, "argv", ["uvicorn", "api.server:app", "--workers", "2"]
            ):
                self.assertEqual(server.worker_process_count(), 2)
            with mock.patch.object(
                sys, "argv", ["uvicorn", "api.server:app", "--workers=5"]
            ):
                self.assertEqual(server.worker_process_count(), 5)

    def test_single_worker_by_default(self) -> None:
        with mock.patch.dict(os.environ, _clean_env()):
            with mock.patch.object(sys, "argv", ["python", "-m", "unittest"]):
                self.assertEqual(server.worker_process_count(), 1)


class WorkerWarningTest(unittest.TestCase):
    """Ogohlantirish matni va lifespan'ga ulanishi."""

    def test_warning_is_logged_for_multiple_workers(self) -> None:
        with mock.patch.dict(os.environ, {**_clean_env(), "WEB_CONCURRENCY": "2"}):
            with mock.patch.object(sys, "argv", ["uvicorn", "api.server:app"]):
                with self.assertLogs(server.logger, level="WARNING") as captured:
                    workers = server.warn_about_multiple_workers()
        self.assertEqual(workers, 2)
        message = "\n".join(captured.output)
        self.assertIn("rate limiter", message)
        self.assertIn("per-user lock", message)
        self.assertIn("jarayonlar o'rtasida umumiy emas", message)
        self.assertIn("2×2", message)

    def test_no_warning_for_single_worker(self) -> None:
        with mock.patch.dict(os.environ, _clean_env()):
            with mock.patch.object(sys, "argv", ["python", "-m", "unittest"]):
                with self.assertLogs(server.logger, level="INFO") as captured:
                    workers = server.warn_about_multiple_workers()
        self.assertEqual(workers, 1)
        self.assertFalse(
            [line for line in captured.output if "WARNING" in line],
            captured.output,
        )

    def test_lifespan_calls_the_check(self) -> None:
        """Startup (lifespan) davomida tekshiruv chaqirilishi shart."""
        env = mock.patch.dict(
            os.environ,
            {
                **_clean_env(),
                "WEB_CONCURRENCY": "2",
                "ALLOW_GUEST_AUTH": "true",
                "ALLOW_IN_MEMORY_FALLBACK": "true",
                "BOT_TOKEN": "",
            },
        )
        env.start()
        self.addCleanup(env.stop)

        with mock.patch.object(server, "warn_about_multiple_workers") as check:
            with TestClient(server.app):
                pass
        check.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()

import logging
import sync.cancel as cancel
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class SyncJob:
    """
    Base orchestration wrapper for ALL sync jobs.
    Eliminates repeated:
    - cancel handling
    - try/except/finally
    - result reporting
    - logging boilerplate
    """

    job_name: str = "unnamed-sync"

    def run_full(self):
        return self._run(mode="full")

    def run_incremental(self):
        return self._run(mode="incremental")

    def _run(self, mode: str):
        cancel.reset()
        cancel.set_running(f"{self.job_name} — {mode}")

        logger.info(f"{self.job_name}: {mode} sync starting")

        try:
            result = self._execute(mode)

            if not cancel.cancelled():
                self._update_state(mode)

            cancel.set_result(
                "cancelled" if cancel.cancelled() else "completed",
                f"{self.job_name} — {mode}",
                counts=result,
            )

            return result

        except Exception as e:
            cancel.set_result(
                "failed",
                f"{self.job_name} — {mode}",
                detail=str(e),
            )
            logger.error(f"{self.job_name} failed: {e}")
            raise

        finally:
            cancel.clear_running()

    # ── override these ─────────────────────────────

    def _execute(self, mode: str) -> dict:
        raise NotImplementedError

    def _update_state(self, mode: str) -> None:
        """Optional override for DB sync state updates."""
        pass
import json
import os
import time

import requests
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from config.sources import SourceConfig
from extractors.base import BaseExtractor, RawDoc

log = structlog.get_logger()

APIFY_BASE = "https://api.apify.com/v2"
POLL_INTERVAL = 10  # seconds between run-status checks
RUN_TIMEOUT = 300   # max seconds to wait for actor to finish


class ApifyExtractor(BaseExtractor):
    """Triggers an Apify actor run, waits for it to finish, returns dataset items
    as pretty-printed JSON text so the LLM parser can process them like any doc.

    Requires APIFY_TOKEN in env.
    """

    def _token(self) -> str:
        tok = os.getenv("APIFY_TOKEN", "").strip()
        if not tok:
            raise RuntimeError(
                "APIFY_TOKEN not set. Get a free token at https://apify.com → Settings → Integrations."
            )
        return tok

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    def _start_run(self, actor_id: str, run_input: dict, token: str) -> str:
        """Start an actor run and return the run ID."""
        url = f"{APIFY_BASE}/acts/{actor_id}/runs"
        resp = requests.post(
            url,
            params={"token": token},
            json=run_input,
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        run_id = resp.json()["data"]["id"]
        log.info("apify.run_started", actor=actor_id, run_id=run_id)
        return run_id

    def _wait_for_run(self, run_id: str, token: str) -> str:
        """Poll until run status is SUCCEEDED/FAILED/ABORTED. Returns final status."""
        url = f"{APIFY_BASE}/actor-runs/{run_id}"
        deadline = time.time() + RUN_TIMEOUT
        while time.time() < deadline:
            resp = requests.get(url, params={"token": token}, timeout=15)
            resp.raise_for_status()
            status = resp.json()["data"]["status"]
            log.info("apify.run_status", run_id=run_id, status=status)
            if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                return status
            time.sleep(POLL_INTERVAL)
        return "TIMEOUT"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    def _fetch_dataset(self, run_id: str, token: str) -> list[dict]:
        """Fetch all dataset items from a completed run."""
        url = f"{APIFY_BASE}/actor-runs/{run_id}/dataset/items"
        resp = requests.get(
            url,
            params={"token": token, "format": "json", "limit": 1000},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()

    def extract(self, source: SourceConfig) -> RawDoc:
        token = self._token()
        actor_id = source.api_params.get("actor_id")
        if not actor_id:
            log.error("apify.missing_actor_id", source=source.key)
            return RawDoc(source.key, source.url, "", self.today_iso())

        run_input = source.api_params.get("run_input", {})
        log.info("apify.starting", source=source.key, actor=actor_id, input=run_input)

        try:
            run_id = self._start_run(actor_id, run_input, token)
        except Exception as e:
            log.error("apify.start_failed", source=source.key, error=str(e))
            return RawDoc(source.key, source.url, "", self.today_iso())

        status = self._wait_for_run(run_id, token)
        if status != "SUCCEEDED":
            log.error("apify.run_not_succeeded", run_id=run_id, status=status)
            return RawDoc(source.key, source.url, "", self.today_iso())

        try:
            items = self._fetch_dataset(run_id, token)
        except Exception as e:
            log.error("apify.dataset_failed", run_id=run_id, error=str(e))
            return RawDoc(source.key, source.url, "", self.today_iso())

        text = json.dumps(items, indent=2)[:120_000]
        log.info("apify.done", source=source.key, items=len(items), chars=len(text))
        return RawDoc(source.key, source.url, text, self.today_iso())

"""
worker/worker.py — Background Inference Worker (Placeholder for Commit 1)

Full implementation (BRPOP loop, Slow Model simulation, MongoDB writes)
will be added in Commit 6.

This placeholder exists so Docker Compose can build and start the worker
container without errors during early milestone verification.
"""

import asyncio
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("worker")


async def main() -> None:
    logger.info("🔧  Worker process started (placeholder — full impl in Commit 6).")
    logger.info("    Waiting for tasks on inference_queue... (no-op for now)")
    # Keep process alive so Docker does not restart-loop
    while True:
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())


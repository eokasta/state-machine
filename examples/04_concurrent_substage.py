"""Scenario 04: process items concurrently with independent retries."""

from __future__ import annotations

import asyncio

import state_machine as sm


def main() -> None:
    app = sm.Application(
        config=sm.ApplicationConfig(
            database_url="sqlite:///examples/04_concurrent_substage.sqlite3"
        )
    )

    @app.substage(retry=sm.StageRetry(max_retries=1, retry_on=(TimeoutError,)))
    class EnrichItem(sm.SubStage):
        async def execute(self, context: sm.SubStageContext) -> None:
            await asyncio.sleep(0.05)
            if context.item["name"] == "beta" and context.attempt_number == 1:
                raise TimeoutError("source is temporarily unavailable")
            context.item["enriched"] = True

    @app.stage(concurrency=3)
    async def enrich_catalog(context: sm.StageContext) -> None:
        result = await context.amap_substage(
            EnrichItem,
            [{"name": "alpha"}, {"name": "beta"}, {"name": "gamma"}],
        )
        context.data["successful_items"] = result.succeeded
        context.data["attempts_per_item"] = [
            item.attempts for item in result.iter_results()
        ]

    try:
        result = app.run()
        print(f"Processed items: {result.data['successful_items']}")
        print(f"Attempts per item: {result.data['attempts_per_item']}")
    finally:
        app.close()


if __name__ == "__main__":
    main()

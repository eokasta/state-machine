"""Scenario 05: workers, partial results, and a final report."""

from __future__ import annotations

import logging

import state_machine as sm

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    app = sm.Application(
        config=sm.ApplicationConfig(
            database_url="sqlite:///examples/05_complete_workflow.sqlite3"
        )
    )

    @app.substage(retry=sm.StageRetry(max_retries=1, retry_on=(ValueError,)))
    class ValidateOrder(sm.SubStage):
        def setup(self, context: sm.WorkerContext) -> None:
            self.worker_id = context.worker_id
            logger.info("Worker %s started", self.worker_id)

        def execute(self, context: sm.SubStageContext) -> None:
            if not context.item.get("email"):
                raise ValueError("order has no email")
            context.item["worker_id"] = self.worker_id
            context.item["validated"] = True

        def cleanup(self, _: sm.WorkerContext) -> None:
            logger.info("Worker %s finished", self.worker_id)

    @app.stage(priority=0, concurrency=2)
    async def validate_orders(context: sm.StageContext) -> None:
        orders = context.data["orders"]
        result = await context.amap_substage(ValidateOrder, orders)
        context.data["valid_orders"] = result.succeeded
        context.data["failures"] = [
            {
                "order_id": orders[item.index]["id"],
                "error": item.error_message,
                "attempts": item.attempts,
            }
            for item in result.iter_results()
            if item.status is sm.AttemptStatus.FAILED
        ]

    @app.stage(priority=10)
    def report_result(context: sm.StageContext) -> None:
        logger.info("Valid orders: %s", context.data["valid_orders"])
        for failure in context.data["failures"]:
            logger.info(
                "Order %s failed after %s attempt(s): %s",
                failure["order_id"],
                failure["attempts"],
                failure["error"],
            )

    try:
        app.run(
            data={
                "orders": [
                    {"id": "A-100", "email": "ada@example.com"},
                    {"id": "A-101"},
                    {"id": "A-102", "email": "grace@example.com"},
                ]
            }
        )
    finally:
        app.close()


if __name__ == "__main__":
    main()

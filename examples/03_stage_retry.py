"""Scenario 03: retry a stage after a transient failure."""

import state_machine as sm


def main() -> None:
    app = sm.Application(config=sm.ApplicationConfig(database_url="sqlite://"))
    calls = 0

    @app.stage(
        retry=sm.StageRetry(
            max_retries=2,
            interval_seconds=0.1,
            retry_on=(ConnectionError,),
        )
    )
    def fetch_service(context: sm.StageContext) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("service is temporarily unavailable")
        context.data["response"] = "service answered on the second attempt"

    try:
        result = app.run()
        print(result.data["response"])
        print(f"Attempts executed: {calls}")
    finally:
        app.close()


if __name__ == "__main__":
    main()

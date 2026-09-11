"""Scenario 02: order stages by priority and share context."""

import state_machine as sm


def main() -> None:
    app = sm.Application(config=sm.ApplicationConfig(database_url="sqlite://"))

    @app.stage(priority=20)
    def publish_summary(context: sm.StageContext) -> None:
        print(f"Summary: {context.data['total']} items prepared.")

    @app.stage(priority=10)
    def prepare(context: sm.StageContext) -> None:
        context.data["total"] = len(context.data["items"])

    try:
        result = app.run(data={"items": ["apple", "banana", "orange"]})
        print(result.data)
    finally:
        app.close()


if __name__ == "__main__":
    main()

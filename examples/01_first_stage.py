"""Scenario 01: execute one stage and return data through the context."""

import state_machine as sm


def main() -> None:
    app = sm.Application(config=sm.ApplicationConfig(database_url="sqlite://"))

    @app.stage()
    def greet(context: sm.StageContext) -> None:
        context.data["message"] = f"Hello, {context.data['name']}!"

    try:
        result = app.run(data={"name": "Ada"})
        print(result.data["message"])
    finally:
        app.close()


if __name__ == "__main__":
    main()

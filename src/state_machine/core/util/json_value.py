"""JSON-compatible value type used for persisted snapshots."""

type JsonValue = (
    bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None
)

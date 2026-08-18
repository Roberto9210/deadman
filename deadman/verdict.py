from dataclasses import dataclass


@dataclass(frozen=True)
class Verdict:
    """Result of a check. `code` is a stable UPPER_SNAKE identifier meant for
    machines; `reason` is for humans and may include the offending values."""

    allowed: bool
    code: str
    reason: str = ""

    @classmethod
    def allow(cls, code: str = "OK", reason: str = "") -> "Verdict":
        return cls(True, code, reason)

    @classmethod
    def deny(cls, code: str, reason: str = "") -> "Verdict":
        return cls(False, code, reason)

    def __bool__(self) -> bool:  # `if verdict:` reads as "allowed"
        return self.allowed

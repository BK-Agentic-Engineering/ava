from dataclasses import asdict, dataclass


class ContextLimit(ValueError):
    pass


class TokenLimit(ValueError):
    pass


def remaining_context(input_tokens, limit):
    if input_tokens >= limit:
        raise ContextLimit(f"Input {input_tokens} tokens reaches context limit {limit}")
    return limit - input_tokens


@dataclass(frozen=True)
class Budget:
    # Project baseline on the local 8 GB GPU, not a certified organizer limit.
    seconds: float = 30
    context_tokens: int = 16384
    output_tokens: int = 512

    def __post_init__(self):
        if self.seconds < 0 or self.context_tokens < 1 or self.output_tokens < 0:
            raise ValueError("Budget requires nonnegative time/output and positive context")

    def to_dict(self):
        return asdict(self)


# Chunked prefill bounds activation memory; it does not truncate the input.
PREFILL_CHUNK = 512

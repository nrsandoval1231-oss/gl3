"""Conservative request cost ceilings for bounded OpenAI provider calls."""

from decimal import Decimal

OPENAI_MAX_INPUT_TOKENS = 272_000
OPENAI_CACHE_WRITE_USD_PER_MILLION = Decimal("2.50")
OPENAI_CACHE_READ_USD_PER_MILLION = Decimal("0.10")
OPENAI_ORDINARY_INPUT_USD_PER_MILLION = Decimal("2.00")
OPENAI_OUTPUT_USD_PER_MILLION = Decimal("10.00")
OPENAI_SERVICE_TIER = "default"
OPENAI_PROMPT_CACHE_TTL = "30m"


def openai_request_cost_ceiling(
    request_bytes: int,
    max_output_tokens: int,
    *,
    input_rate_usd_per_million: Decimal = OPENAI_CACHE_WRITE_USD_PER_MILLION,
    output_rate_usd_per_million: Decimal = OPENAI_OUTPUT_USD_PER_MILLION,
) -> Decimal:
    """Reserve worst-case cache writes, using serialized bytes as an input-token upper bound.

    All enabled request bodies are UTF-8 serialized, so their byte count conservatively
    bounds input tokens. The output cap is included in the 272k combined context limit.
    """
    if type(request_bytes) is not int or request_bytes <= 0:
        return Decimal("0")
    return openai_cost_ceiling_from_tokens(
        request_bytes,
        max_output_tokens,
        input_rate_usd_per_million=input_rate_usd_per_million,
        output_rate_usd_per_million=output_rate_usd_per_million,
    )


def openai_cost_ceiling_from_tokens(
    input_tokens: int,
    max_output_tokens: int,
    *,
    input_rate_usd_per_million: Decimal = OPENAI_CACHE_WRITE_USD_PER_MILLION,
    output_rate_usd_per_million: Decimal = OPENAI_OUTPUT_USD_PER_MILLION,
) -> Decimal:
    """Reserve from an exact preflight token count and refuse oversized contexts."""
    if (
        type(input_tokens) is not int
        or type(max_output_tokens) is not int
        or input_tokens <= 0
        or max_output_tokens <= 0
        or input_tokens + max_output_tokens > OPENAI_MAX_INPUT_TOKENS
        or input_rate_usd_per_million <= 0
        or output_rate_usd_per_million < 0
    ):
        return Decimal("0")
    return (
        Decimal(input_tokens) * input_rate_usd_per_million
        + Decimal(max_output_tokens) * output_rate_usd_per_million
    ) / Decimal(1_000_000)

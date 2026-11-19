"""The model the pipeline actually runs must have a confirmed price, or every run shows no cost."""
from pipeline.token_tracker import Pricing


def test_default_provider_model_is_priced():
    p = Pricing.load()
    toks = {"input_tokens": 1000, "output_tokens": 1000, "cache_read_tokens": 1000, "cache_write_tokens": 0}
    for provider in ("openai", "foundry"):
        assert p.cost(provider, "gpt-6-astra", toks) is not None, provider

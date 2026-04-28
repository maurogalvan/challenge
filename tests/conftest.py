import pytest


@pytest.fixture(autouse=True)
def zero_provider_latency(monkeypatch):
    def noop(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr("jobs.providers.base.sleep_ms_ranged", noop)

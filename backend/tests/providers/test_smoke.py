import asyncio

import pytest

from providers import smoke


def test_smoke_refuses_without_accept_cost(monkeypatch, capsys) -> None:
    monkeypatch.setenv("YOUCAM_API_KEY", "test-key")
    assert smoke.main(["--provider", "youcam"]) == 2
    assert "--i-accept-cost" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("provider", "key_name"),
    [("youcam", "YOUCAM_API_KEY"), ("gemini", "GEMINI_API_KEY")],
)
def test_smoke_refuses_without_provider_key(provider, key_name, monkeypatch, capsys) -> None:
    monkeypatch.delenv(key_name, raising=False)
    assert smoke.main(["--provider", provider, "--i-accept-cost"]) == 2
    assert key_name in capsys.readouterr().err


def test_smoke_refuses_output_outside_local(monkeypatch, capsys) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    assert (
        smoke.main(
            [
                "--provider",
                "gemini",
                "--i-accept-cost",
                "--out",
                "/tmp/provider-result.png",  # noqa: S108 — smoke-test output path
            ]
        )
        == 2
    )
    assert ".local" in capsys.readouterr().err


def test_youcam_submit_cap_rejects_second_call_before_provider_request(
    monkeypatch,
) -> None:
    class Provider:
        def __init__(self):
            self.calls = 0

        async def submit(self, *args):
            self.calls += 1

    provider = Provider()
    monkeypatch.setattr(smoke, "_youcam_submit_attempted", False)
    asyncio.run(smoke._submit_youcam_once(provider, None, None, "upper_body"))  # type: ignore[arg-type]
    with pytest.raises(RuntimeError):
        asyncio.run(smoke._submit_youcam_once(provider, None, None, "upper_body"))  # type: ignore[arg-type]
    assert provider.calls == 1

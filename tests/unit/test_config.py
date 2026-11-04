import pytest
from pydantic import ValidationError

from email_classifier.config import Settings

ENV_VARS = (
    "LLM_API_KEY",
    "LLM_MODEL",
    "LLM_TIMEOUT_SECONDS",
    "LLM_MAX_RETRIES",
    "VAULT_KEY",
    "HUMAN_REVIEW_THRESHOLD",
    "LOG_LEVEL",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def make_settings() -> Settings:
    return Settings(_env_file=None)


def test_defaults() -> None:
    settings = make_settings()

    assert settings.llm_api_key is None
    assert settings.llm_model is None
    assert settings.human_review_threshold == 0.7
    assert settings.log_level == "INFO"


def test_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "some-model")
    monkeypatch.setenv("HUMAN_REVIEW_THRESHOLD", "0.85")

    settings = make_settings()

    assert settings.llm_model == "some-model"
    assert settings.human_review_threshold == 0.85


def test_secrets_are_masked_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "sk-very-secret")
    monkeypatch.setenv("VAULT_KEY", "vault-very-secret")

    settings = make_settings()

    assert "very-secret" not in repr(settings)
    assert settings.llm_api_key is not None
    assert settings.llm_api_key.get_secret_value() == "sk-very-secret"


@pytest.mark.parametrize("value", ["-0.1", "1.5"])
def test_rejects_threshold_out_of_range(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("HUMAN_REVIEW_THRESHOLD", value)

    with pytest.raises(ValidationError):
        make_settings()

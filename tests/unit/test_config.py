import pytest
from pydantic import ValidationError

from email_classifier.config import Settings

ENV_VARS = (
    "OLLAMA_BASE_URL",
    "OLLAMA_MODEL",
    "LLM_TIMEOUT_SECONDS",
    "LLM_TEMPERATURE",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_TIMEOUT_SECONDS",
    "MAIL_FROM",
    "LOG_LEVEL",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def make_settings() -> Settings:
    return Settings(_env_file=None)


def test_defaults_work_without_any_env() -> None:
    settings = make_settings()

    assert settings.ollama_base_url == "http://localhost:11434"
    assert settings.ollama_model == "qwen2.5:3b"
    assert settings.llm_temperature == 0.0
    assert settings.smtp_host == "localhost"
    assert settings.smtp_port == 1025
    assert settings.mail_from == "router@example.com"
    assert settings.log_level == "INFO"


def test_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2:3b")
    monkeypatch.setenv("SMTP_HOST", "mailpit")
    monkeypatch.setenv("SMTP_PORT", "2525")

    settings = make_settings()

    assert settings.ollama_base_url == "http://ollama:11434"
    assert settings.ollama_model == "llama3.2:3b"
    assert settings.smtp_host == "mailpit"
    assert settings.smtp_port == 2525


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SMTP_PORT", "0"),
        ("SMTP_PORT", "70000"),
        ("LLM_TIMEOUT_SECONDS", "0"),
        ("LLM_TEMPERATURE", "-1"),
        ("MAIL_FROM", "not-an-email"),
        ("LOG_LEVEL", "VERBOSE"),
    ],
)
def test_rejects_invalid_values(monkeypatch: pytest.MonkeyPatch, name: str, value: str) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        make_settings()

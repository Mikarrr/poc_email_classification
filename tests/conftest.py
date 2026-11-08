import pytest

from tests.fakes import FakeMailer


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def fake_mailer() -> FakeMailer:
    return FakeMailer()

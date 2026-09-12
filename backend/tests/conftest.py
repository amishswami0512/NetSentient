import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from app import create_app  # noqa: E402
from services.state_service import state  # noqa: E402


@pytest.fixture
def app():
    flask_app = create_app()
    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture
def client(app):
    state.reset()
    with app.test_client() as test_client:
        yield test_client
    state.reset()

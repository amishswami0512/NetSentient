import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from app import create_app  # noqa: E402
from services.classifier_service import BaseClassifier, ClassificationResult, set_classifier  # noqa: E402
from services.state_service import state  # noqa: E402


class TestClassifier(BaseClassifier):
    def classify(self, text: str) -> ClassificationResult:
        normalized = text.lower()
        if "icu" in normalized or "oxygen" in normalized or "anomaly" in normalized:
            return ClassificationResult("critical_sensor", 0.9, 7, "test classification", "test")
        if any(term in normalized for term in ("ambulance", "emergency", "evacuate", "fire", "code-blue")):
            return ClassificationResult("emergency", 0.9, 10, "test classification", "test")
        if "video" in normalized or "call" in normalized or "stream" in normalized:
            return ClassificationResult("video", 0.9, 4, "test classification", "test")
        if "file" in normalized or "upload" in normalized:
            return ClassificationResult("file", 0.9, 2, "test classification", "test")
        return ClassificationResult("background", 0.3, 1, "test classification", "test")


@pytest.fixture
def app():
    flask_app = create_app()
    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture
def client(app):
    state.reset()
    # HTTP tests remain deterministic and do not require an external Gemini key.
    set_classifier(TestClassifier())
    with app.test_client() as test_client:
        yield test_client
    state.reset()

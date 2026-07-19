from types import SimpleNamespace

import pytest

from assetflow.core.config import Settings
from assetflow.core.errors import RateLimitError
from assetflow.core.security import hash_password
from assetflow.db.models import Asset, Comment, Project, User, Workspace
from assetflow.services.creative_ai import CreativeAIService


def feedback_asset(db):
    user = User(
        email="ai-designer@example.com",
        name="AI Designer",
        password_hash=hash_password("strong-password"),
    )
    workspace = Workspace(name="AI Studio", slug="ai-studio")
    db.add_all([user, workspace])
    db.flush()
    project = Project(workspace_id=workspace.id, name="AI launch")
    db.add(project)
    db.flush()
    asset = Asset(project_id=project.id, title="Campaign", assigned_designer_id=user.id)
    db.add(asset)
    db.flush()
    db.add(
        Comment(
            asset_id=asset.id,
            guest_name="Client",
            guest_role="client",
            body="Please increase the logo spacing and deepen the green.",
        )
    )
    db.commit()
    return asset, user


def test_openai_task_extraction_uses_structured_output(monkeypatch, db):
    asset, user = feedback_asset(db)
    captured = {}

    class FakeResponses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                output_text='["Increase the logo spacing", "Use a deeper brand green"]'
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.responses = FakeResponses()

    monkeypatch.setattr("assetflow.services.creative_ai.OpenAI", FakeOpenAI)
    settings = Settings(environment="test", OPENAI_API_KEY="test-key", openai_model="test-model")
    tasks = CreativeAIService(db, settings).extract_tasks(asset, user)

    assert [task.text for task in tasks] == [
        "Increase the logo spacing",
        "Use a deeper brand green",
    ]
    assert captured["model"] == "test-model"
    assert captured["store"] is False
    assert captured["client"]["api_key"] == "test-key"
    assert "untrusted content" in captured["input"]


def test_blank_openai_key_never_creates_a_client(monkeypatch, db):
    asset, user = feedback_asset(db)

    def unexpected_client(**_):
        raise AssertionError("OpenAI must not be called with a blank key")

    monkeypatch.setattr("assetflow.services.creative_ai.OpenAI", unexpected_client)
    settings = Settings(environment="test", OPENAI_API_KEY="")
    tasks = CreativeAIService(db, settings).extract_tasks(asset, user)

    assert [task.text for task in tasks] == [
        "Increase the logo spacing and deepen the green",
    ]


def test_openai_summary_is_real_bounded_and_not_stored(monkeypatch, db):
    asset, user = feedback_asset(db)
    captured = {}

    class FakeResponses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                output_text=(
                    '{"summary":"Refine the identity spacing and deepen the green.",'
                    '"actions":["Increase logo clear space","Use the deeper green"],'
                    '"themes":["Brand","Colour"]}'
                )
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.responses = FakeResponses()

    monkeypatch.setattr("assetflow.services.creative_ai.OpenAI", FakeOpenAI)
    settings = Settings(environment="test", OPENAI_API_KEY="test-key")
    result = CreativeAIService(db, settings).summarize(asset, user)

    assert result["available"] is True
    assert result["model"] == "gpt-4o-mini"
    assert result["themes"] == ["Brand", "Colour"]
    assert captured["max_output_tokens"] == 180
    assert captured["store"] is False
    assert captured["client"]["max_retries"] == 1
    assert captured["client"]["timeout"] == 10.0
    assert "untrusted data" in captured["input"]


def test_ai_actions_have_a_persisted_cooldown(monkeypatch, db):
    asset, user = feedback_asset(db)

    class FakeResponses:
        def create(self, **_):
            return SimpleNamespace(
                output_text='{"summary":"Clear direction.","actions":[],"themes":[]}'
            )

    class FakeOpenAI:
        def __init__(self, **_):
            self.responses = FakeResponses()

    monkeypatch.setattr("assetflow.services.creative_ai.OpenAI", FakeOpenAI)
    settings = Settings(environment="test", OPENAI_API_KEY="test-key")
    service = CreativeAIService(db, settings)
    assert service.summarize(asset, user)["available"] is True
    with pytest.raises(RateLimitError):
        service.summarize(asset, user)


def test_failed_ai_request_does_not_consume_cooldown(monkeypatch, db):
    asset, user = feedback_asset(db)

    class SimulatedConnectionError(Exception):
        pass

    class FailingResponses:
        def create(self, **_):
            raise SimulatedConnectionError("simulated connection outage")

    class FakeOpenAI:
        def __init__(self, **_):
            self.responses = FailingResponses()

    monkeypatch.setattr("assetflow.services.creative_ai.OpenAI", FakeOpenAI)
    monkeypatch.setattr(
        "assetflow.services.creative_ai.openai.APIConnectionError",
        SimulatedConnectionError,
    )
    settings = Settings(environment="test", OPENAI_API_KEY="test-key")
    service = CreativeAIService(db, settings)

    assert service.summarize(asset, user)["available"] is False
    assert service.summarize(asset, user)["available"] is False

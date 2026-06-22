from __future__ import annotations

import json

import pytest

from pytest_drift import ci
from pytest_drift.pandas_utils import ComparisonResult


@pytest.fixture
def gitlab_env(monkeypatch):
    monkeypatch.setenv("GITLAB_CI", "true")
    monkeypatch.setenv("CI_MERGE_REQUEST_IID", "7")
    monkeypatch.setenv("CI_PROJECT_ID", "42")
    monkeypatch.setenv("CI_SERVER_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "tok")


@pytest.fixture
def captured_request(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["headers"] = dict(req.header_items())
        captured["body"] = json.loads(req.data.decode("utf-8"))

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b""

        return _Resp()

    monkeypatch.setattr(ci.urllib.request, "urlopen", fake_urlopen)
    return captured


def test_set_label_adds_when_drift(gitlab_env, captured_request):
    results = [ComparisonResult(equal=False, report="x", node_id="t::a")]
    ci.set_gitlab_mr_label(results, [])

    assert captured_request["method"] == "PUT"
    assert captured_request["url"].endswith("/projects/42/merge_requests/7")
    assert captured_request["body"] == {"add_labels": "drift"}


def test_set_label_removes_when_stable(gitlab_env, captured_request):
    results = [ComparisonResult(equal=True, report=None, node_id="t::a")]
    ci.set_gitlab_mr_label(results, [])

    assert captured_request["body"] == {"remove_labels": "drift"}


def test_set_label_noop_outside_mr_pipeline(monkeypatch, captured_request):
    monkeypatch.setenv("GITLAB_CI", "true")
    monkeypatch.delenv("CI_MERGE_REQUEST_IID", raising=False)
    results = [ComparisonResult(equal=False, report="x", node_id="t::a")]

    ci.set_gitlab_mr_label(results, [])

    assert captured_request == {}

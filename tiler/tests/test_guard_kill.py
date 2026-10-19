"""The cost guard's kill switch (terraform/tiler/guard/kill.py), with boto3 stubbed."""

import importlib.util
import json
from pathlib import Path

import pytest

KILL = Path(__file__).resolve().parents[2] / "terraform/tiler/guard/kill.py"


class Fake:
    def __init__(self, calls, fail=()):
        self.calls, self.fail = calls, fail

    def client(self, service, region_name=None):
        calls, fail = self.calls, self.fail

        class Client:
            def __getattr__(self, op):
                def call(**kw):
                    calls.append((service, region_name, op, kw))
                    if op in fail:
                        raise RuntimeError(f"{op} denied")
                    if op == "get_distribution_config":
                        return {"ETag": "E1", "DistributionConfig": {"Enabled": True, "Comment": kw["Id"]}}
                    if op == "get_function_concurrency":
                        return {"ReservedConcurrentExecutions": 60}
                    return {}

                return call

        return Client()


def load(monkeypatch, calls, fail=()):
    monkeypatch.setenv(
        "FUNCTIONS", json.dumps([{"name": "t-nasa", "region": "us-west-2"}, {"name": "t-noaa", "region": "us-east-1"}])
    )
    monkeypatch.setenv("DISTRIBUTIONS", json.dumps(["TILER", "SITE"]))
    monkeypatch.setenv("ALERT_TOPIC", "arn:aws:sns:us-east-1:1:alerts")
    spec = importlib.util.spec_from_file_location("kill", KILL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "boto3", Fake(calls, fail))
    return mod


def ops(calls):
    return [(c[0], c[1], c[2]) for c in calls]


def test_kill_stops_functions_and_disables_distributions(monkeypatch):
    calls = []
    kill = load(monkeypatch, calls)
    report = kill.handler({"alarmData": {"alarmName": "x-kill"}}, None)
    assert report["reason"] == "alarm x-kill" and not report["errors"]
    assert ("lambda", "us-west-2", "put_function_concurrency") in ops(calls)
    assert ("lambda", "us-east-1", "put_function_concurrency") in ops(calls)
    updates = [c[3] for c in calls if c[2] == "update_distribution"]
    assert [u["Id"] for u in updates] == ["TILER", "SITE"]
    assert all(u["IfMatch"] == "E1" and u["DistributionConfig"]["Enabled"] is False for u in updates)
    assert any(c[2] == "publish" for c in calls)


def test_dry_run_changes_nothing(monkeypatch):
    calls = []
    kill = load(monkeypatch, calls)
    report = kill.handler({"dry_run": True}, None)
    assert report["dry_run"] and len(report["done"]) == 4
    assert not any(c[2] in ("put_function_concurrency", "update_distribution", "publish") for c in calls)


def test_one_failure_doesnt_stop_the_rest(monkeypatch):
    calls = []
    kill = load(monkeypatch, calls, fail=("put_function_concurrency",))
    with pytest.raises(RuntimeError, match="incomplete"):
        kill.handler({"Records": [{"Sns": {"Subject": "AWS Budgets: over"}}]}, None)
    assert len([c for c in calls if c[2] == "update_distribution"]) == 2  # distributions still disabled

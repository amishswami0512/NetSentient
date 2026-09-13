"""Unit tests mock subprocess.run so they pass in any CI environment,
regardless of whether it has root/NET_ADMIN -- the real tc/iptables
commands were verified manually against a live interface during
development, not as part of this portable suite.
"""
from unittest.mock import patch

import pytest

from config import Config
from services import enforcement_service


@pytest.fixture(autouse=True)
def _default_disabled(monkeypatch):
    monkeypatch.setattr(Config, "ENFORCEMENT_ENABLED", False)
    monkeypatch.setattr(Config, "ENFORCEMENT_INTERFACE", "lo")
    monkeypatch.setattr(Config, "ENFORCEMENT_BANDWIDTH_MBPS", 10.0)
    monkeypatch.setattr(enforcement_service, "_base_applied", False)


@pytest.mark.parametrize(
    "priority,expected_tier",
    [(10.0, "critical"), (7.5, "critical"), (7.4, "high"), (5.0, "high"),
     (4.9, "normal"), (2.0, "normal"), (1.9, "low"), (0.0, "low")],
)
def test_tier_boundaries(priority, expected_tier):
    tier = enforcement_service._tier_for_priority(priority)
    assert tier["name"] == expected_tier


def test_dry_run_never_calls_subprocess():
    with patch("services.enforcement_service.subprocess.run") as mock_run:
        result = enforcement_service.apply_flow_priority("tcp", 443, 9.0)

    mock_run.assert_not_called()
    assert result["dry_run"] is True
    assert result["applied"] is False
    assert result["tier"] == "critical"
    assert any("tc qdisc replace" in c for c in result["commands"])
    assert any("iptables -t mangle -A NETSENTIENT_MARK -p tcp --dport 443" in c for c in result["commands"])


def test_dst_cidr_appears_in_plan_when_enabled_or_not():
    result = enforcement_service.apply_flow_priority("udp", 5004, 6.0, dst_cidr="10.0.0.0/24")
    mark_cmd = next(c for c in result["commands"] if "--dport 5004" in c)
    assert "-d 10.0.0.0/24" in mark_cmd


def test_validate_dst_cidr_rejects_garbage():
    with pytest.raises(ValueError):
        enforcement_service.validate_dst_cidr("not-a-cidr; rm -rf /")


def test_validate_dst_cidr_accepts_real_cidr():
    assert enforcement_service.validate_dst_cidr("192.168.1.0/24") == "192.168.1.0/24"


def _fake_run(success_cmds=(), fail_cmds=()):
    """Builds a subprocess.run stand-in keyed off the joined argv, so
    tests can script exactly which commands succeed vs. fail without
    needing a real tc/iptables underneath.
    """
    from types import SimpleNamespace

    def _run(cmd, capture_output, text, timeout):
        joined = " ".join(cmd)
        if any(pat in joined for pat in fail_cmds):
            return SimpleNamespace(returncode=1, stdout="", stderr="simulated failure")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return _run


def test_enabled_mode_executes_and_reports_success(monkeypatch):
    monkeypatch.setattr(Config, "ENFORCEMENT_ENABLED", True)
    with patch("services.enforcement_service.subprocess.run", side_effect=_fake_run()) as mock_run:
        result = enforcement_service.apply_flow_priority("tcp", 443, 9.0)

    assert result["dry_run"] is False
    assert result["applied"] is True
    assert result["errors"] == []
    assert mock_run.called


def test_enabled_mode_reports_real_failures(monkeypatch):
    monkeypatch.setattr(Config, "ENFORCEMENT_ENABLED", True)
    fake = _fake_run(fail_cmds=("tc qdisc replace",))
    with patch("services.enforcement_service.subprocess.run", side_effect=fake):
        result = enforcement_service.apply_flow_priority("tcp", 443, 9.0)

    assert result["applied"] is False
    assert any("tc qdisc replace" in e["command"] for e in result["errors"])


def test_benign_errors_are_tolerated_not_reported(monkeypatch):
    monkeypatch.setattr(Config, "ENFORCEMENT_ENABLED", True)
    from types import SimpleNamespace

    def _run(cmd, capture_output, text, timeout):
        if "-N" in cmd and "NETSENTIENT_MARK" in cmd:
            return SimpleNamespace(returncode=1, stdout="", stderr="Chain already exists")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with patch("services.enforcement_service.subprocess.run", side_effect=_run):
        result = enforcement_service.apply_flow_priority("tcp", 443, 9.0)

    assert result["applied"] is True
    assert result["errors"] == []


def test_idempotent_jump_rule_skips_append_when_already_present(monkeypatch):
    monkeypatch.setattr(Config, "ENFORCEMENT_ENABLED", True)
    calls = []
    from types import SimpleNamespace

    def _run(cmd, capture_output, text, timeout):
        calls.append(cmd)
        if cmd[3] == "-C" and cmd[4:] == ["OUTPUT", "-j", "NETSENTIENT_MARK"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")  # already present
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with patch("services.enforcement_service.subprocess.run", side_effect=_run):
        enforcement_service.apply_flow_priority("tcp", 443, 9.0)

    jump_appends = [c for c in calls if c[3:6] == ["-A", "OUTPUT", "-j"]]
    assert jump_appends == []  # probe succeeded, so -A OUTPUT was never issued


def test_reset_dry_run_never_calls_subprocess():
    with patch("services.enforcement_service.subprocess.run") as mock_run:
        result = enforcement_service.reset_enforcement()
    mock_run.assert_not_called()
    assert result["dry_run"] is True


def test_get_status_never_raises_when_binaries_missing(monkeypatch):
    def _raise(*args, **kwargs):
        raise FileNotFoundError("tc not found")

    monkeypatch.setattr(enforcement_service.subprocess, "run", _raise)
    status = enforcement_service.get_status()
    assert status["qdisc"] is None
    assert status["classes"] is None
    assert status["mangle_rules"] is None

"""Deterministic phone alert timing, without a camera, Qt or audio device."""
import pytest

from phone_alerts import CameraAlerts, PhoneAlerts


def observe(alerts, start, end, mode="strict"):
    return [(time, event) for time in range(start, end + 1)
            if (event := alerts.update(float(time), True, mode))]


@pytest.mark.parametrize("alert_type", [CameraAlerts, PhoneAlerts])
@pytest.mark.parametrize("mode,expected", [
    ("light", [(3, "checkin"), (30, "alarm"), (40, "alarm")]),
    ("strict", [(3, "checkin"), (15, "alarm"), (18, "alarm"), (21, "alarm")]),
    ("asian_parent", [(3, "checkin"), (10, "alarm"), (11, "alarm"), (12, "alarm")]),
])
def test_each_mode_chimes_once_and_escalates_at_its_cadence(alert_type, mode, expected):
    assert observe(alert_type(), 0, expected[-1][0], mode) == expected


def test_phone_leaving_view_resets_cadence_for_next_pickup():
    alerts = PhoneAlerts()
    observe(alerts, 0, 16)
    assert alerts.update(16.5, False) is None
    assert observe(alerts, 17, 20) == [(20, "checkin")]


@pytest.mark.parametrize("next_time", [2.01, -1])
def test_observation_gap_or_clock_reversal_cannot_accumulate_phone_time(next_time):
    alerts = PhoneAlerts()
    observe(alerts, 0, 1)
    assert alerts.update(next_time, True) is None
    assert alerts.since == next_time
    assert alerts.last_alarm is None


def test_strictness_change_applies_to_current_episode():
    alerts = PhoneAlerts()
    assert observe(alerts, 0, 15, "light") == [(3, "checkin")]
    assert alerts.update(15.1, True, "strict") == "alarm"
    assert alerts.update(16.1, True, "asian_parent") == "alarm"


def test_refreshes_between_due_times_never_stack_alarms():
    alerts = PhoneAlerts()
    observe(alerts, 0, 15)
    for i in range(1, 30):
        assert alerts.update(15 + i / 10, True) is None
    assert alerts.update(18.0, True) == "alarm"

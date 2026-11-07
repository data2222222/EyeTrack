"""Deterministic phone alert timing, without a camera, Qt or audio device."""
import pytest

from phone_alerts import CameraAlerts, LookingAwayAlerts, PhoneAlerts


def observe(alerts, start, end, mode="strict"):
    return [(time, event) for time in range(start, end + 1)
            if (event := alerts.update(float(time), True, mode))]


@pytest.mark.parametrize("alert_type", [CameraAlerts, PhoneAlerts, LookingAwayAlerts])
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


def test_looking_away_alarm_requires_two_continuous_seconds_back_on_task():
    alerts = LookingAwayAlerts()
    assert observe(alerts, 0, 15) == [(3, "checkin"), (15, "alarm")]
    assert alerts.update(15.5, False) is None
    assert alerts.update(16.0, False) is None
    assert alerts.update(16.5, True) is None  # A glance back doesn't clear the episode.
    assert alerts.update(17.0, False) is None
    assert alerts.update(18.0, False) == "alarm"  # Original repeat cadence continues.
    assert alerts.update(18.9, False) is None
    assert alerts.since == 0
    assert alerts.update(19.0, False) is None
    assert alerts.since is None
    assert observe(alerts, 20, 23) == [(23, "checkin")]


def test_looking_away_checkin_can_clear_immediately_before_alarm_escalates():
    alerts = LookingAwayAlerts()
    observe(alerts, 0, 3)
    assert alerts.update(3.5, False) is None
    assert alerts.since is None


@pytest.mark.parametrize("next_time", [18.01, 15.0])
def test_interrupted_observations_reset_looking_away_recovery(next_time):
    alerts = LookingAwayAlerts()
    observe(alerts, 0, 15)
    alerts.update(16.0, False)
    alerts.update(17.0, False)
    assert alerts.update(next_time, False) is None
    assert alerts.since is None


def test_return_progress_tracks_the_same_clock_and_resets_with_attention():
    alerts = LookingAwayAlerts()
    assert alerts.recovery_progress(0) is None
    observe(alerts, 0, 15)
    assert alerts.recovery_progress(15) is None
    alerts.update(15.5, False)
    assert alerts.recovery_progress(15.5) == 0
    assert alerts.recovery_progress(16) == .25
    alerts.update(16.5, False)
    assert alerts.recovery_progress(16.5) == .5
    alerts.update(17, True)
    assert alerts.recovery_progress(17) is None
    alerts.update(17.5, False)
    assert alerts.recovery_progress(17.5) == 0
    alerts.reset()
    assert alerts.recovery_progress(18) is None


def test_return_progress_does_not_fill_through_a_stalled_ui_or_clock_reversal():
    alerts = LookingAwayAlerts()
    observe(alerts, 0, 15)
    alerts.update(15.5, False)
    assert alerts.recovery_progress(17) is None
    assert alerts.recovery_progress(15) is None

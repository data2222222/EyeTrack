"""Camera-alert cadence, driven by fresh observations and monotonic timestamps.

No GUI, camera or sound dependencies. Missing observations and inactive work reset
the episode; a slow/stalled UI must not count unobserved time as distraction.
"""

MODES = {
    "light": ("Light", 30, 10),
    "strict": ("Strict", 15, 3),
    "asian_parent": ("Asian parent", 10, 1),
}
CHIME_AFTER = 3
MAX_GAP = 1.0
RETURN_AFTER = 2


class CameraAlerts:
    def __init__(self):
        self.reset()

    def reset(self):
        self.since = None
        self.last_seen = None
        self.chimed = False
        self.last_alarm = None

    def update(self, now, visible, mode="strict"):
        """Return checkin/alarm when due, or None, for a sustained observed state."""
        if not visible:
            self.reset()
            return None
        if self.last_seen is not None and not 0 <= now - self.last_seen <= MAX_GAP + 1e-6:
            self.reset()
        if self.since is None:
            self.since = now
        self.last_seen = now
        elapsed = now - self.since
        _, escalate, repeat = MODES.get(mode, MODES["strict"])
        if elapsed >= escalate and (self.last_alarm is None or now - self.last_alarm >= repeat):
            self.chimed = True
            self.last_alarm = now
            return "alarm"
        if elapsed >= CHIME_AFTER and not self.chimed:
            self.chimed = True
            return "checkin"
        return None


class PhoneAlerts(CameraAlerts):
    """Cadence for confirmed phones; also shared by looking-away alerts."""


class LookingAwayAlerts(CameraAlerts):
    """After escalation, require sustained on-task observations to clear the alarm."""

    def reset(self):
        super().reset()
        self.return_since = None

    def update(self, now, visible, mode="strict"):
        if visible:
            self.return_since = None
        elif (self.last_alarm is not None and self.last_seen is not None
              and 0 <= now - self.last_seen <= MAX_GAP + 1e-6):
            if self.return_since is None:
                self.return_since = now
            # Keep the existing alarm cadence during a brief return to the task.
            visible = now - self.return_since < RETURN_AFTER
        return super().update(now, visible, mode)

    def recovery_progress(self, now):
        """Fraction of the continuous return completed, or None when not recovering."""
        if (self.return_since is None or self.last_seen is None
                or not 0 <= now - self.last_seen <= MAX_GAP + 1e-6):
            return None
        return max(0.0, min(1.0, (now - self.return_since) / RETURN_AFTER))

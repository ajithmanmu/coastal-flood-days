"""Backfill every station-year of hourly water levels.

Designed to run unattended on Fargate for several hours against an API that publishes
no rate limit and asks callers to be reasonable. Every control below exists so that
this can be stopped, capped, or slowed without a redeploy.

Local dry run:
    .venv/bin/python src/backfill.py --stations 2 --start 2020 --max-requests 10

Stopping a running task:
    aws ssm put-parameter --name /coastal-flood-days/backfill/enabled \\
        --value false --type String --overwrite

It stops at the next station boundary, having written everything it already fetched.
Nothing is lost -- rerunning skips whatever is already cached.
"""

import argparse
import json
import logging
import os
import signal
import sys
import time
import urllib.request
from dataclasses import dataclass, field

from flood_days import fetch_threshold
from storage import is_cached, load_year

STATIONS_URL = (
    "https://api.tidesandcurrents.noaa.gov/dpapi/prod/webapi/htf/htf_annual.json"
)
KILL_SWITCH_PARAM = "/coastal-flood-days/backfill/enabled"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,  # CloudWatch reads stdout
)
log = logging.getLogger("backfill")


class Stop(Exception):
    """Raised by any brake. Always results in a clean exit, never a half-written file."""


@dataclass
class Brakes:
    """Every limit that can halt the run, in one place so none of them are implicit."""

    max_requests: int = 20_000
    max_hours: float = 8.0
    max_consecutive_failures: int = 10
    seconds_between_requests: float = 0.5
    check_kill_switch: bool = True

    requests_made: int = 0
    consecutive_failures: int = 0
    started_at: float = field(default_factory=time.monotonic)
    _sigterm: bool = False

    def install_signal_handler(self) -> None:
        """ECS StopTask sends SIGTERM, then SIGKILL after a grace period. Catching it
        means we finish the current write instead of leaving a truncated file."""

        def handle(signum, _frame):
            log.warning("received signal %s -- stopping at next boundary", signum)
            self._sigterm = True

        signal.signal(signal.SIGTERM, handle)
        signal.signal(signal.SIGINT, handle)

    def elapsed_hours(self) -> float:
        return (time.monotonic() - self.started_at) / 3600

    def check(self) -> None:
        """Raise Stop if any brake is engaged. Called between stations."""
        if self._sigterm:
            raise Stop("SIGTERM received")
        if self.requests_made >= self.max_requests:
            raise Stop(f"request cap reached ({self.max_requests})")
        if self.elapsed_hours() >= self.max_hours:
            raise Stop(f"time limit reached ({self.max_hours}h)")
        if self.consecutive_failures >= self.max_consecutive_failures:
            raise Stop(f"{self.consecutive_failures} consecutive failures")
        if self.check_kill_switch and not kill_switch_enabled():
            raise Stop("kill switch flipped off")

    def record_request(self, ok: bool) -> None:
        self.requests_made += 1
        self.consecutive_failures = 0 if ok else self.consecutive_failures + 1
        time.sleep(self.seconds_between_requests)


def kill_switch_enabled(default: bool = True) -> bool:
    """Read the SSM kill switch. Fails OPEN deliberately.

    If SSM is unreachable we keep running rather than aborting a six-hour job over a
    transient API blip -- the other brakes (time, request cap, circuit breaker) still
    bound the damage. A missing parameter also means 'enabled', so the task runs
    without requiring setup.
    """
    try:
        import boto3

        value = boto3.client("ssm").get_parameter(Name=KILL_SWITCH_PARAM)
        return value["Parameter"]["Value"].strip().lower() not in {"false", "0", "off"}
    except Exception as exc:
        if "ParameterNotFound" in str(exc):
            return True
        log.warning("kill switch unreadable (%s) -- continuing", type(exc).__name__)
        return default


def all_station_ids() -> list[str]:
    """Every station NOAA publishes flood-day counts for -- the 137 that matter."""
    with urllib.request.urlopen(STATIONS_URL, timeout=60) as response:
        payload = json.load(response)
    return sorted({row["stnId"] for row in payload["AnnualFloodCount"]})


def backfill_station(station_id: str, start: int, end: int, brakes: Brakes) -> dict:
    """Fetch and cache every year for one station. Returns a small progress record."""
    stats = {"station": station_id, "fetched": 0, "cached": 0, "empty": 0, "failed": 0}

    try:
        fetch_threshold(station_id)  # no threshold means the station is not usable
    except Exception:
        log.warning("%s has no flood threshold -- skipping", station_id)
        stats["failed"] = 1
        return stats

    for year in range(start, end + 1):
        # Checked per YEAR, not per station. Checking only at station boundaries lets a
        # 106-year station overshoot the request cap by 105 -- measured, not theoretical.
        # Stopping mid-station is safe: every completed year is already on disk.
        brakes.check()

        if is_cached(station_id, year):
            stats["cached"] += 1
            continue
        try:
            frame = load_year(station_id, year)
            stats["fetched"] += 1
            if frame.empty:
                stats["empty"] += 1
            brakes.record_request(ok=True)
        except Exception as exc:
            stats["failed"] += 1
            log.warning("%s %s failed: %s", station_id, year, str(exc)[:80])
            brakes.record_request(ok=False)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=1920)
    parser.add_argument("--end", type=int, default=2025)
    parser.add_argument("--stations", type=int, default=0, help="limit, 0 = all")
    parser.add_argument("--max-requests", type=int, default=20_000)
    parser.add_argument("--max-hours", type=float, default=8.0)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--no-kill-switch", action="store_true")
    args = parser.parse_args()

    brakes = Brakes(
        max_requests=args.max_requests,
        max_hours=args.max_hours,
        seconds_between_requests=args.delay,
        check_kill_switch=not args.no_kill_switch,
    )
    brakes.install_signal_handler()

    stations = all_station_ids()
    if args.stations:
        stations = stations[: args.stations]

    log.info(
        "backfill start · %s stations · %s-%s · cap %s requests · limit %sh · delay %ss",
        len(stations), args.start, args.end, args.max_requests, args.max_hours, args.delay,
    )

    totals = {"fetched": 0, "cached": 0, "empty": 0, "failed": 0}
    stopped = None

    for index, station_id in enumerate(stations, start=1):
        try:
            brakes.check()
            stats = backfill_station(station_id, args.start, args.end, brakes)
        except Stop as stop:
            stopped = str(stop)
            break

        for key in totals:
            totals[key] += stats[key]

        log.info(
            "[%s/%s] %s · fetched %s (empty %s) · cached %s · failed %s "
            "· %s requests · %.2fh",
            index, len(stations), station_id, stats["fetched"], stats["empty"],
            stats["cached"], stats["failed"], brakes.requests_made, brakes.elapsed_hours(),
        )

    if stopped:
        log.warning("STOPPED: %s", stopped)
    log.info(
        "done · fetched %s · cached %s · empty %s · failed %s · %s requests · %.2fh",
        totals["fetched"], totals["cached"], totals["empty"], totals["failed"],
        brakes.requests_made, brakes.elapsed_hours(),
    )

    # A halt requested by an operator is a success; a circuit-breaker trip is not.
    if stopped and "consecutive failures" in stopped:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""The date and the four times of day shown in the ERA5-Land figures.

DATE was chosen with select_day.py (clearest summer 2026 day in ERA5 total
cloud cover over New Haven). Times are the ERA5-Land hours nearest to the
actual sunrise, solar noon and sunset in New Haven on DATE, and to the middle
of the preceding night (midpoint between the previous sunset and sunrise), so
all four are on the same local calendar day. Local time is EDT = UTC-4.

Needs the "astral" package.
"""

import datetime as dt

from astral import Observer
from astral.sun import sun

DATE = dt.date(2026, 7, 20)  # mean ERA5 cloud cover 3.5% (06-19 EDT), 3.9% (00-05 EDT)
EDT = dt.timezone(dt.timedelta(hours=-4), "EDT")
NEW_HAVEN = Observer(latitude=41.3083, longitude=-72.9279)  # New Haven Green


# region sun-event-times
def _round_hour(t: dt.datetime) -> dt.datetime:
    return (t + dt.timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0)


def sun_events(date: dt.date = DATE) -> dict[str, dt.datetime]:
    """Sunrise, solar noon, sunset, and the middle of the preceding night (EDT)."""
    today = sun(NEW_HAVEN, date=date, tzinfo=EDT)
    prev_sunset = sun(NEW_HAVEN, date=date - dt.timedelta(days=1), tzinfo=EDT)["sunset"]
    return {
        "night": prev_sunset + (today["sunrise"] - prev_sunset) / 2,
        "sunrise": today["sunrise"],
        "midday": today["noon"],
        "sunset": today["sunset"],
    }


def product_times(date: dt.date = DATE) -> dict[str, tuple[dt.datetime, dt.datetime]]:
    """{product: (event time, nearest whole hour)} in EDT, product = t2m_<event>."""
    return {f"t2m_{k}": (t, _round_hour(t)) for k, t in sun_events(date).items()}
# endregion sun-event-times


if __name__ == "__main__":
    for product, (event, hour) in product_times().items():
        print(f"{product:12s} event {event:%H:%M} EDT -> {hour:%Y-%m-%d %H:%M} EDT = {hour.astimezone(dt.UTC):%Y-%m-%d %H:%M} UTC")

"""Чистые хелперы интерфейса мастера: роли, кнопки времени, разбор цены."""

from datetime import time

import pytest

from barber_bot.domain.rules import DEFAULT_RULES
from barber_bot.presentation.master.common import parse_hhmm, time_options
from barber_bot.presentation.master.services import _price
from barber_bot.presentation.roles import Roles

MASTER_TG = 1
CLIENT_TG = 111


def test_master_acts_as_master_until_switching_to_client_mode() -> None:
    roles = Roles(MASTER_TG)
    assert roles.acts_as_master(MASTER_TG)
    assert not roles.acts_as_master(CLIENT_TG)

    roles.set_client_mode(True)
    assert not roles.acts_as_master(MASTER_TG)
    assert roles.is_master(MASTER_TG)  # кнопка «Режим мастера» остаётся

    roles.set_client_mode(False)
    assert roles.acts_as_master(MASTER_TG)


def test_time_options_follow_grid_and_skip_earlier_times() -> None:
    all_times = time_options(DEFAULT_RULES)
    assert all_times[0] == ("0600", "06:00")
    assert all_times[-1] == ("2330", "23:30")
    assert all(parse_hhmm(hhmm).minute % 30 == 0 for hhmm, _ in all_times)

    later = time_options(DEFAULT_RULES, after=time(20, 0))
    assert [label for _, label in later] == [
        "20:30",
        "21:00",
        "21:30",
        "22:00",
        "22:30",
        "23:00",
        "23:30",
    ]


@pytest.mark.parametrize(("raw", "price"), [("5000", 5000), ("5 000", 5000), (" 0 ", 0)])
def test_price_accepts_digits_with_spaces(raw: str, price: int) -> None:
    assert _price(raw) == price


@pytest.mark.parametrize("raw", ["", "abc", "-100", "5000₸", "1.5"])
def test_price_rejects_non_numbers(raw: str) -> None:
    with pytest.raises(ValueError):
        _price(raw)

import math
from shuttle_system.core.optimization import (
    C, benefit_per_person, breakeven_N, net_benefit,
)


def test_cost_constant():
    assert C == 35_000


def test_benefit_per_person_matches_pdf_table():
    # PDF 6절 결과표: 요금 0/1000/2000/3000 -> b 6983/5983/4983/3983
    assert round(benefit_per_person(0)) == 6983
    assert round(benefit_per_person(1000)) == 5983
    assert round(benefit_per_person(2000)) == 4983
    assert round(benefit_per_person(3000)) == 3983


def test_breakeven_matches_pdf_table():
    # N* = ceil(C/b): 6/6/8/9
    assert breakeven_N(0) == 6
    assert breakeven_N(1000) == 6
    assert breakeven_N(2000) == 8
    assert breakeven_N(3000) == 9


def test_net_benefit_sign():
    # F=2000 -> b=4983, N*=8. 8명이면 양수, 7명이면 음수
    assert net_benefit(8, 2000) > 0
    assert net_benefit(7, 2000) < 0
    # b(2000)=4983.33 -> 4983.33*8 - 35000 ≈ 4867
    assert round(net_benefit(8, 2000)) == 4867

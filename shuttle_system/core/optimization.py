"""PDF '셔틀 운영 모델'의 코드 구현 — 순수 함수, 외부 의존 없음.

값의 성격:
  - N* (손익분기): 상수. 요금/비용이 정해지면 1회 산출.
  - net_benefit: Report가 매 기간 실제 수송 인원으로 계산.
"""
import math

# ── 파라미터 (PDF 3·5절) ────────────────────────────────
C = 35_000              # 회당 변동 운영비(원)
P_TAXI = 0.3            # 셔틀 이용자 중 원래 택시 비율
P_BUS = 0.7             # 〃 버스 비율
TAXI_FARE = 12_000      # 캠퍼스↔울산역 택시요금
BUS_FARE = 1_500        # 513 요금
T_SAVED_MIN = 20        # 513 대비 셔틀 시간절약(분)
VOT_PER_HOUR = 10_000   # 학생 시간가치(원/h)

# 정책 요금 (확정: 2,000원 → N*=8)
POLICY_FARE = 2_000


def benefit_per_person(fare: int) -> float:
    """1인당 편익 b (PDF 3절). fare는 셔틀 요금(0~3000)."""
    taxi = P_TAXI * (TAXI_FARE - fare)
    bus = P_BUS * ((T_SAVED_MIN / 60) * VOT_PER_HOUR + BUS_FARE - fare)
    return taxi + bus


def breakeven_N(fare: int = POLICY_FARE) -> int:
    """손익분기 인원 N* = ceil(C / b). 상수."""
    return math.ceil(C / benefit_per_person(fare))


def net_benefit(passengers: int, fare: int = POLICY_FARE) -> float:
    """실현 사회 순편익 b·N − C."""
    return benefit_per_person(fare) * passengers - C

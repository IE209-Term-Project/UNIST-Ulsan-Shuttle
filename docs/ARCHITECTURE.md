# 시스템 아키텍처

## 데이터 흐름
```
KTX 시간표 + 513 시간표 + 설문
        ↓ (OR 모델: Z=Σxₜ(b·Nₜ−C), N*=⌈C/b⌉)
고정 8 + 조건부 5 슬롯 (F=2,000원 → N*=8)
        ↓
[학생 앱] 예약 → Google Sheets ← [관리자 앱] 집계
        ↓                              ↓
Notify Agent (셔틀/513/택시 + 택시셰어)   Report Agent (순편익·대기절감 + 차트 + LLM)
```

## 4개 에이전트
| 에이전트 | 책임 | LLM |
|---|---|---|
| Data Agent | 실시간 513 도착(BIS API) | X |
| (Demand) | 설문 수요 N → core가 사용 | X |
| Notify Agent | 개인화 추천 메시지 | O |
| Report Agent | 운영 리포트 서술 | O |

핵심: LLM은 계산하지 않는다. Python(core)이 OR 모델로 계산하고, 에이전트는 해석·전달한다.

## 모듈 구조
```
shuttle_system/
├── core/optimization.py   # b, C, N*=⌈C/b⌉, net_benefit
├── core/schedule.py       # 고정8/조건부5 슬롯 + 요일·KTX 매칭
├── core/connection.py     # KTX↔513 연계 판정 + 택시
├── agents/data_agent.py   # 실시간 BIS API
├── agents/notify_agent.py # 추천 LLM + 택시셰어
├── agents/report_agent.py # 집계 + 차트 + LLM 요약
├── storage.py             # 예약(메모리/Sheets)
├── app_student.py / app_admin.py
└── demo.ipynb
```

## 핵심 설계 포인트
- **모델↔에이전트 연결:** 조건부 배차 임계값은 하드코딩이 아니라 `breakeven_N(2000)=8`에서 산출 → 시스템이 OR 모델 위에서 동작함을 코드로 증명.
- **실시간 값은 하나:** 슬롯별 "현재 예약 인원". N*와 슬롯 수요 N은 상수. 매 기간 예약을 N*와 대조해 운행/미운행 결정.
- **택시 셰어:** N<N*로 미운행 시 같은 슬롯 예약자를 묶어 1인 요금 안내(모델의 "대체교통" 구체화).
- **역할 분리:** 학생 앱(입력)과 관리자 앱(집계)이 같은 저장소를 공유.

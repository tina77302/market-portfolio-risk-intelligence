# Stress 검증: 새 기간 기록 파이프라인

첫 수정의 주식+금리 일간 회귀와 과거 오차 범위 규칙을 고정하고, 앞으로 관측할 구간을 조건부 재현 방식으로 평가합니다.
실제 시장 충격은 구간 종료 후에만 알려지므로 시작 전에 미래 손실 숫자를 발행하는 모델이 아닙니다. 시작 전에는 베타와 오차 분포를 저장하고, 종료 후 그 베타에 실제 충격을 입력합니다.

## 실행

```bash
# 기존 로컬 스냅샷으로 상태 확인·갱신. 원본 파일은 바꾸지 않습니다.
python -m src.portfolio.forward_validation run

# Yahoo Finance 수정종가/VIX와 FRED DGS10을 새로 읽어 별도 보관
python -m src.portfolio.forward_validation run --refresh

# 봉인 파일 무결성을 확인한 뒤 현재 상태 표시
python -m src.portfolio.forward_validation status

# 별도 입력 CSV 사용
python -m src.portfolio.forward_validation run --prices /path/prices.csv --factors /path/factors.csv
```

두 CSV는 기존 `data/portfolio/prices.csv`, `factors.csv`와 같은 날짜 인덱스와 열 규약을 사용합니다.
기본 보관소는 `data/portfolio_forward_validation/`이며 `--store`로 별도 실험 경로를 지정할 수 있습니다.
실제 실행 기록·가격·오차 분포는 Git에서 제외되며, 예약 실행은 전체 보관소를 Actions artifact로 보관합니다.

## 단계와 고정 규칙

1. **정책 봉인:** 모델 방식, 756일 학습창, 10거래일 구간, 최소 30/최대 60개 오차, 목표 포함률 90%, 비대칭·대칭 방식, 자산·포트폴리오 비중을 기록합니다. Python/numpy/pandas 버전, 코드와 연구용 초기 오차의 해시 및 패키지 잠금 파일도 저장합니다.
2. **입력 보관:** 완료된 날짜의 SPY 기반 거래 관측과 가격·금리·VIX를 별도 버전으로 저장합니다. 뉴욕 당일의 막대는 장 종료 여부를 추측하지 않고 항상 제외합니다. 가격·금리 입력이 4일 넘게 오래됐거나 누락이면 새 베타를 발행하지 않습니다.
3. **시작 전 봉인:** 당시 자료로 계산한 28개 자산의 베타, 실제 입력 해시, 과거 오차 행과 순위 기반 범위 오프셋을 저장합니다. 절편은 기존 첫 수정처럼 손실 계산에서 제외합니다. 28개 단일 자산과 두 예시 포트폴리오를 추적합니다.
4. **시작 관측:** 발행한 뉴욕 날짜보다 뒤에 실제로 나타난 첫 SPY 거래 관측을 시작으로 고정합니다. 휴일을 임의의 평일로 채우지 않습니다. 시작일이 관측될 때 별도 anchor를 추가하며 이전 발행 파일은 바꾸지 않습니다.
5. **평가 대기:** 시작 관측 이후 10개의 추가 SPY 거래 관측이 생길 때까지 평가하지 않습니다. 금리 양끝 수준이 없거나 과거 이월 수준이 4일 넘으면 금리 대기 상태를 유지합니다.
6. **평가 봉인:** 저장한 베타와 오차 오프셋만 사용합니다. 실제 충격, 실제 buy-and-hold 손실, 추정 손실, 범위, 포함 여부·폭·상한 초과·구간 점수를 새 결과 파일로 추가합니다. 평가 후 다음 구간의 발행 파일을 만들 수 있습니다. 완료한 결과는 재실행해도 재평가·교체하지 않습니다.

‘거래일’은 수집된 SPY 일별 관측의 순서입니다. 별도 거래소 달력과 공급자의 누락 일자를 대조한 것으로 주장하지 않습니다.
새 구간마다 같은 고정 방식으로 베타를 다시 추정할 수 있지만, 한 번 발행한 구간의 베타·범위는 고정합니다.

## 상태와 저장물

| 상태 | 의미 |
| --- | --- |
| `WAITING_FOR_INPUT` | 수집 실패, 결측 또는 자산 규약 불일치. 오류 종류를 기록하며 새 성과를 생성하지 않음 |
| `WAITING_FOR_FRESH_INPUT` | 입력 날짜가 오래됨 |
| `WAITING_FOR_START_SESSION` | 시작 전에 베타·오차 분포를 저장했으나 후속 시작 관측이 없음 |
| `WAITING_FOR_OUTCOME` | 시작했으나 10개 추가 거래 관측이 아직 없음 |
| `WAITING_FOR_ENDPOINT_RATE` | 평가 구간은 생겼지만 금리 양끝 수준이 불충분 |
| `EVALUATED` | 실제 결과 파일이 봉인됨. 다음 구간은 별도 발행 파일로 추적 |

- `policy.json`, `requirements.freeze.txt`: 실험의 고정 정의·코드·환경.
- `inputs/<해시>/`: 수집 입력과 SHA-256 receipt. 동일 입력은 재사용하며 원본 연구 스냅샷을 덮어쓰지 않습니다.
- `entries/<발행 시각>/issue.json`: 시작 전 베타·학습 기준일·보정 오차와 범위 오프셋.
- `anchor.json`, `result.json`: 시작 관측과 완료 평가를 추가 생성.
- `status.json`, `evaluations.csv`, `summary.csv`: 재생성 가능한 상태·누적 집계. 성과 집계에는 완료한 새 기간 결과만 넣습니다.

기존 145개 구간의 오차는 `retrospective_seed`라고 표시한 준비 자료입니다. 새 기간의 관측 성과로 합산하지 않습니다.
새 결과를 이후 범위 계산에 사용할 때도 완료된 날짜와 기록 시각을 확인하고 `forward:<발행 해시>`로 출처를 남깁니다.
범위 자료가 부족하면 범위를 0이나 확률로 대체하지 않습니다. 기본 연구용 준비 자료로는 첫 발행에 최대 60개 오차가 사용될 수 있습니다.

## 수정종가 개정과 무결성

배당·분할 때문에 이후 수집의 과거 수정종가가 바뀔 수 있습니다. 실제 구간 수익률은 **같은 평가 입력 버전의 시작·종료 수정종가**로 계산해 서로 다른 수정 기준을 섞지 않습니다.
처음 보았던 시작 가격도 보존하고 평가 시 개정 차이를 기록합니다. 이것은 당시 공급자 공표본을 완벽하게 재현한 검증이나 실제 체결 계좌가 아닙니다.

정책·입력·발행·anchor·결과는 원자적 신규 생성과 해시 검사를 사용합니다. 같은 경로에 다른 내용을 쓰지 않으며 실행을 잠가 중복을 막습니다.
코드·핵심 환경·준비 자료가 바뀌거나 해시가 맞지 않으면 중단합니다. 새 정책은 별도의 실험 경로로 관리해야 합니다.
로컬 해시는 실수로 인한 수정 탐지와 재현을 위한 것으로, 외부 타임스탬프 공증이나 악의적인 관리자의 변경 방지를 보장하지 않습니다. 실행 환경의 시계를 신뢰한다는 가정도 남습니다.

## 예약 실행과 보관

[워크플로](../.github/workflows/portfolio-forward-validation.yml)는 UTC 평일 23:37, 한국 시간 다음 날 08:37에 실행하도록 구성했습니다. 수동 실행도 지원합니다.
원격 기본 브랜치에 워크플로가 반영되고 Actions가 활성화돼야 예약이 동작합니다. 로컬 커밋만으로 원격 예약을 실행한 것으로 표시하지 않습니다.
GitHub 예약 실행은 지연·누락될 수 있어 시각을 보장하지 않습니다. [GitHub 예약 실행 문서](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

이전의 신뢰한 동일 워크플로·기본 브랜치 artifact에서 전체 보관소를 복원하고, 원래 Python 버전·패키지 잠금을 재사용합니다.
실행 후 상태가 대기이거나 수집이 실패해도 보관소를 업로드합니다. 정책·기록이 있던 실행의 보관소를 복원할 수 없으면 조용히 새 연구로 초기화하지 않습니다.
artifact 보관 기간은 90일로 설정했고 매 실행의 보관소에는 기존 기록을 누적합니다. 장기 중단·삭제에 대비한 외부 보관은 별도로 필요합니다. [Actions artifact 문서](https://github.com/actions/upload-artifact)

처음 실행할 때도 이미 이전 실행이 있었는데 artifact가 없으면 복구를 요구합니다. 이 경우 새 성과로 이어 붙이지 말고 보관본을 복원하거나 별도의 실험 이름으로 시작해야 합니다.

## 수집 실패와 예약 누락 알림

수집 워크플로는 상태를 보관한 뒤에도 입력 문제를 성공으로 숨기지 않습니다. 수집 단계 다음의 상태 점검에서 `WAITING_FOR_INPUT`, `WAITING_FOR_FRESH_INPUT`, `WAITING_FOR_ENDPOINT_RATE`를 발견하면 Actions 오류와 실패 종료를 기록합니다. 정상적인 시작·결과 대기와 완료 상태는 알림 대상이 아닙니다. 상태 기록이 30분 넘게 오래됐거나 입력 가격이 뉴욕 당일 자료 또는 4일 넘게 오래된 자료인 경우에도 실패합니다. 상태 파일이 없거나 손상된 경우는 감시 실패로 표시합니다.

이 점검은 모델·계수·정책·발행 기록을 변경하지 않습니다. 점검이 실패해도 기존 상태 보관 단계는 실행되며, `health.json`을 같은 `portfolio-forward-state` artifact에 포함합니다. 설치·복원·수집 명령 자체의 오류는 기존 Actions 실패로 표시됩니다.

별도 [감시 워크플로](../.github/workflows/portfolio-forward-watchdog.yml)는 매일 UTC 02:17, 한국 시간 11:17에 실행합니다. 가장 최근 UTC 평일 23:37의 수집 예약을 대상으로 90분의 지연 허용 시간을 둡니다. 해당 기본 브랜치의 **schedule 이벤트**가 없거나 아직 완료되지 않았거나 실패·취소·건너뜀으로 끝나면 감시 워크플로를 실패시킵니다. push·수동 실행 성공은 누락된 예약을 대신하지 않습니다. 주말에는 금요일의 마지막 예약을 확인하고, 워크플로가 처음 만들어진 시각보다 앞선 예약은 요구하지 않습니다. 수집 워크플로가 비활성화됐거나 API 조회가 실패해도 정상으로 판단하지 않습니다.

감시 결과는 실행 요약과 `portfolio-forward-health` artifact에 30일간 보관합니다. 수집·감시 워크플로 모두 Actions 화면에서 수동 실행할 수 있습니다. 로컬 상태 파일 점검은 다음과 같습니다.

```bash
python scripts/check_portfolio_forward_health.py status
```

알림 전달은 **GitHub Actions 기본 실패 알림**을 사용합니다. GitHub 계정의 [알림 설정](https://github.com/settings/notifications)에서 Actions의 메일 또는 GitHub 웹 알림을 켜고 필요하면 실패 실행만 받도록 설정해야 합니다. 계정의 수신 설정이나 실제 메일 수신 여부는 이 코드에서 변경·검증하지 않습니다. 예약 알림 수신자는 GitHub의 예약 워크플로 actor 규칙을 따릅니다. [Actions 알림 설정 문서](https://docs.github.com/en/subscriptions-and-notifications/how-tos/managing-github-actions-notifications), [예약 이벤트와 알림 수신자 문서](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

감시도 GitHub Actions에서 실행하므로 GitHub 전체 장애나 두 예약의 동시 누락을 독립적으로 탐지하지는 못합니다. 이런 경우까지 보장하려면 별도 서비스의 외부 감시가 필요합니다. 실제 장애를 만들어 알림을 보내는 대신, 누락·취소·수집 실패·정상 대기·주말·첫 배포 조건은 임시 테스트 자료로 검증합니다.

AWS 외부 예약의 구성·인증 등록·실제 예약 검증은 [AWS 예약 운영 문서](PORTFOLIO_AWS_SCHEDULER_KO.md)를 따릅니다. 예약 공급자는 `infra/aws/portfolio_schedule_policy.json`으로 구분합니다. `github` 모드에서는 위의 `schedule` 이벤트를 확인하고, `aws-eventbridge` 모드에서는 정확한 예정 시각의 AWS 표시가 있는 `workflow_dispatch` 실행을 확인합니다. 일반 수동·push 실행과 AWS 시험 실행은 정기 예약 성공으로 합산하지 않습니다. AWS 활성화 전까지 기존 모드를 유지하며, 활성화 시 GitHub 자체 cron을 제거해 이중 예약을 막습니다.

## 현재 점검 결과

실제 연결·등록 상태는 [실행 점검 보고서](../reports/portfolio/forward_stress/stress_validation_report.md)에 기록합니다.
검증 테스트의 가상 시장 자료는 임시 디렉터리에서만 사용하며 실제 새 기간 성과에 포함하지 않습니다.

```bash
python -m pytest tests/test_portfolio_forward_validation.py tests/test_portfolio_forward_health.py tests/test_portfolio_data.py
```

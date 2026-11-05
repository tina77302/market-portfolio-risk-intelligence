# Stress 검증 AWS 예약 실행

AWS EventBridge Scheduler가 Lambda를 호출하고, Lambda가 기존 GitHub Actions를 `workflow_dispatch`로 시작합니다. 수집·모델 계산·봉인 기록과 artifact 복원은 기존 GitHub 워크플로가 담당합니다. PC나 관리용 AWS 로그인 세션을 계속 켜두지 않아도 배포된 예약은 전용 IAM 역할로 실행됩니다.

## 구성과 비용

- 수집: UTC 월~금 23:37, 한국 시간 화~토 08:37.
- 감시: UTC 매일 02:17, 한국 시간 매일 11:17.
- Lambda: GitHub 실행 요청만 전송합니다. 포트폴리오 자료를 AWS에 복제하지 않습니다.
- Secrets Manager: 해당 저장소의 Actions 실행용 인증 하나를 보관합니다. 새 저장소는 `{"token":""}` 상태이며, 인증 성공으로 표시하지 않습니다.
- DynamoDB: 같은 종류·예약 시각의 중복 호출을 억제하고 기록을 7일 후 만료시킵니다. 응답이 끊겨 성공 여부가 불분명한 요청은 실행 이력을 대조하며, 확인 없이 재전송하지 않습니다.
- SQS: Scheduler 호출 실패와 Lambda 비동기 처리 실패를 최대 14일 보관합니다. CloudWatch 실행 로그도 14일 보관합니다. 이 보관함은 메일 알림을 발송하지 않습니다.

정상적인 하루 수집 1회·감시 1회 이내의 사용량에서는 월 US$1 미만으로 추정합니다. 주된 고정비는 Secrets Manager의 secret 하나당 월 US$0.40입니다. 이는 사용량·지역·세금·무료 혜택을 확정한 청구액이 아닙니다. [Secrets Manager 요금](https://aws.amazon.com/secrets-manager/pricing/), [Scheduler 요금](https://aws.amazon.com/eventbridge/pricing/), [Lambda 요금](https://aws.amazon.com/lambda/pricing/)

## 배포

```bash
python3 infra/aws/build_portfolio_scheduler.py > /tmp/portfolio-scheduler-template.json
aws cloudformation deploy \
  --stack-name market-stress-portfolio-scheduler \
  --template-file /tmp/portfolio-scheduler-template.json \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides EnableSchedules=false \
  --profile market-stress-scheduler --region ap-northeast-2
```

기본값은 **예약 비활성**입니다. 이 템플릿에는 실제 GitHub 토큰이나 특정 AWS 계정 ID를 넣지 않습니다. Lambda 역할은 생성한 secret·테이블·로그·실패 보관함만 접근하고, Scheduler 역할은 해당 Lambda와 실패 보관함만 접근합니다. Scheduler의 신뢰 범위도 같은 AWS 계정·일정 그룹으로 제한합니다.

## GitHub 인증을 비공개로 등록

1. 저장소 소유자 계정에서 fine-grained personal access token을 만듭니다. Resource owner는 `tina77302`, Repository access는 **Only select repositories**에서 `market-portfolio-risk-intelligence` 하나만 선택합니다. Repository permissions의 **Actions: Read and write**만 부여합니다. Metadata 읽기는 GitHub가 기본으로 포함합니다. 토큰 만료 전에 교체해야 합니다.
2. AWS 서울 리전의 Secrets Manager에서 `market-stress/portfolio/github-actions`를 엽니다.
3. Retrieve secret value → Edit에서 `token`의 빈 값에 발급한 토큰을 저장합니다. **채팅·소스·명령행 인자·로그에 토큰을 넣지 않습니다.**

연결된 GitHub 앱의 인증을 추출하거나 AWS로 복사하지 않습니다. 소유자 이외의 협업 계정은 fine-grained token의 대상 저장소 제한 때문에 같은 방식이 지원되지 않을 수 있습니다. 이때 광범위한 토큰을 대신 요구하지 않고 저장소 전용 GitHub App 등 권한 범위를 확인합니다. [토큰 생성과 대상 제한](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens), [워크플로 실행 권한](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event)

`preflight` 호출은 인증으로 워크플로를 읽을 수 있는지만 확인합니다. Actions 쓰기 권한이나 실제 예약 성공을 증명하지 않습니다.

## 실제 예약 검증과 활성화

1. GitHub에 이 변경의 `scheduler_source`, `scheduled_for` 입력과 실행 이름을 반영합니다.
2. Lambda의 `preflight`가 `CREDENTIAL_READ_OK`인지 확인합니다. 실제 토큰 값은 조회·출력하지 않습니다.
3. 같은 일정 그룹에 **몇 분 뒤 한 번만** 실행되는 검증 예약을 만듭니다. 입력은 `{"kind":"verify","scheduled_for":"<aws.scheduler.scheduled-time>"}`입니다. 완료 후 예약은 삭제하도록 설정합니다.
4. AWS에서 실제 예약 실행이 발생했는지 확인하고, GitHub의 `aws-verification` 실행이 수집·상태 점검·artifact 보관까지 성공했는지 확인합니다. 기존 정책 해시와 발행 ID도 대조합니다. 직접 Lambda를 호출한 결과만으로 예약 성공을 주장하지 않습니다.
5. `infra/aws/portfolio_schedule_policy.json`의 mode를 `aws-eventbridge`, activated_at을 실제 활성화 UTC 시각으로 바꿉니다. 두 GitHub 워크플로의 `on.schedule`은 제거합니다. 이 변경을 반영한 뒤 AWS `EnableSchedules=true`를 적용합니다.
6. 이후 감시는 정확한 수집 예정 시각의 **aws-eventbridge 표시가 있는 workflow_dispatch 실행**만 정상 예약으로 인정합니다. 일반 수동·push 실행, 다른 날짜의 실행, `aws-verification`은 누락된 정기 실행을 대신하지 않습니다. 활성화 전의 예약은 요구하지 않습니다.

Lambda가 GitHub에 보낸 요청의 성공과 실제 수집의 성공을 구분합니다. GitHub가 요청을 수락해도 뒤의 작업이 실패할 수 있으므로 GitHub Actions 결과를 확인해야 합니다. 기본 실패 알림은 계정 설정을 따릅니다. AWS나 GitHub 전체 장애를 모두 독립적으로 보장하는 구성은 아닙니다.

## 실패 대응과 제거

- GitHub 토큰 만료·권한 오류: Secrets Manager에서 비공개로 교체한 뒤 preflight와 검증 예약을 다시 확인합니다.
- `DispatchUncertain`: 먼저 동일한 실행 이름의 GitHub 이력을 확인합니다. 실제 실행이 있는데 DynamoDB 기록을 지우고 재전송하지 않습니다. 확인이 어려운 상태는 SQS 실패 보관함에 남겨 수동으로 조사합니다.
- 예약 비활성화: CloudFormation의 `EnableSchedules=false`를 적용합니다. 수동 비활성화된 GitHub 워크플로는 Lambda가 자동으로 다시 켜지 않습니다.
- 스택 삭제 시 secret은 보존합니다. 완전히 제거할 때는 GitHub 토큰을 폐기하고, 보존된 secret도 AWS 콘솔에서 별도로 삭제해야 합니다. 보존된 secret에는 비용이 계속 발생할 수 있습니다.

관련 테스트:

```bash
python -m pytest tests/test_portfolio_aws_scheduler.py tests/test_portfolio_forward_health.py tests/test_portfolio_forward_validation.py tests/test_portfolio_data.py
```

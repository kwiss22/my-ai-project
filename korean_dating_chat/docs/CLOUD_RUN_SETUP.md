# Cloud Run 첫 배포 가이드

`*.run.app` 무료 서브도메인 + GCS Fuse 로 SQLite·이벤트 로그 영구화.
한 번 셋업 후에는 main 브랜치에 푸시만 하면 자동 배포.

## 0. 사전 준비

- GCP 프로젝트 1개 (기존 Gemini API 키 발급한 프로젝트 재사용 권장)
- 로컬 `gcloud` CLI 설치 + 로그인
  ```bash
  gcloud auth login
  gcloud config set project YOUR-PROJECT-ID
  ```
- GitHub 리포 admin 권한 (Actions secret/variable 등록용)

이하 모든 명령에서 `YOUR-PROJECT-ID` → 본인 프로젝트 ID 로 치환.

## 1. API 활성화

```bash
gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    storage.googleapis.com \
    secretmanager.googleapis.com
```

(1~2분 소요)

## 2. GCS 버킷 생성 (영구 저장소)

```bash
# 버킷명은 글로벌 unique. 본인 도메인 prefix 권장.
export BUCKET=kdate-data

# 서울 리전 (Cloud Run 과 같은 리전 권장)
gcloud storage buckets create gs://$BUCKET \
    --location=asia-northeast3 \
    --uniform-bucket-level-access

# 버전 관리 ON — SQLite 파일 사고로 깨졌을 때 이전 버전 복구 가능
gcloud storage buckets update gs://$BUCKET --versioning
```

⚠️ `deploy.yml` 의 `BUCKET` env 가 `kdate-data` 로 박혀 있음. 다른 이름 쓰면 거기도 같이 수정.

## 3. 서비스 계정 + 권한

GitHub Actions 가 이 SA 로 빌드·배포.

```bash
# 서비스 계정 생성
gcloud iam service-accounts create kdate-deploy \
    --display-name="K-Dating Chat Deploy Bot"

export SA=kdate-deploy@YOUR-PROJECT-ID.iam.gserviceaccount.com

# 필요한 권한 부여
for role in \
    roles/run.admin \
    roles/cloudbuild.builds.builder \
    roles/storage.objectAdmin \
    roles/secretmanager.secretAccessor \
    roles/iam.serviceAccountUser \
    roles/artifactregistry.writer
do
    gcloud projects add-iam-policy-binding YOUR-PROJECT-ID \
        --member="serviceAccount:$SA" \
        --role="$role"
done

# JSON 키 발급 (한 번만)
gcloud iam service-accounts keys create kdate-deploy-key.json \
    --iam-account=$SA
```

생성된 `kdate-deploy-key.json` 내용 전체를 복사 → **GitHub repo → Settings → Secrets and variables → Actions → New repository secret** → 이름 `GCP_SA_KEY` 로 등록.

키 파일은 등록 후 로컬에서 삭제:
```bash
rm kdate-deploy-key.json
```

추가로 **Cloud Run 의 runtime 서비스 계정**(`PROJECT_NUMBER-compute@developer.gserviceaccount.com`)에도 버킷 접근 권한 필요:

```bash
export PROJECT_NUMBER=$(gcloud projects describe YOUR-PROJECT-ID --format='value(projectNumber)')
gcloud storage buckets add-iam-policy-binding gs://$BUCKET \
    --member="serviceAccount:$PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
    --role="roles/storage.objectUser"
```

## 4. Secret Manager — 빈 placeholder 먼저 만들기

`deploy.yml` 이 참조하는 모든 secret 이 존재해야 배포 성공. 빈 값이라도 만들어 두면 우리 코드는 기능별로 503 / no-op 로 자동 대응.

```bash
for s in \
    GEMINI_API_KEY \
    SESSION_SECRET \
    GOOGLE_OAUTH_CLIENT_ID \
    GOOGLE_OAUTH_CLIENT_SECRET \
    STRIPE_SECRET_KEY \
    STRIPE_PRICE_ID \
    STRIPE_WEBHOOK_SECRET \
    AZURE_SPEECH_KEY \
    ALERT_SLACK_WEBHOOK_URL \
    ALERT_SMTP_PASSWORD
do
    echo -n "placeholder" | gcloud secrets create $s --data-file=- 2>/dev/null || \
        echo "$s 이미 존재 — skip"
done

# 즉시 채울 수 있는 것 먼저
echo -n "$(openssl rand -hex 32)" | gcloud secrets versions add SESSION_SECRET --data-file=-
echo -n "AIzaSy..." | gcloud secrets versions add GEMINI_API_KEY --data-file=-   # 실 키
```

각 secret 의 실제 값은 가입 진행에 따라 천천히 채우면 됨:
```bash
echo -n "sk_live_..." | gcloud secrets versions add STRIPE_SECRET_KEY --data-file=-
echo -n "whsec_..."   | gcloud secrets versions add STRIPE_WEBHOOK_SECRET --data-file=-
# ...
```

## 5. GitHub 리포 variable 등록

`deploy.yml` 의 `vars.ADMIN_EMAILS` / `vars.APP_BASE_URL` 참조용.

**Settings → Secrets and variables → Actions → Variables 탭** 에서:

| Name | Value (예시) |
|---|---|
| `ADMIN_EMAILS` | `you@your-domain.com` |
| `APP_BASE_URL` | (첫 배포 후 받는 `*.run.app` URL 로 채움) |

`APP_BASE_URL` 은 첫 배포 시점에 비워둬도 됨. 두 번째 배포부터 적용.

## 6. 첫 배포

```bash
git checkout main
git pull
git push origin main
```

또는 GitHub UI 에서 **Actions → Deploy to Cloud Run → Run workflow** 수동 실행.

5~10분 후 GitHub Actions 의 **Show service URL** 단계 출력에서 URL 확인:
```
https://kdating-chat-xxxxxxxx-an.a.run.app
```

## 7. 후속 — URL 받은 다음 한 번만

1. **GitHub repo variable** `APP_BASE_URL` 을 위 URL 로 설정
2. **main 푸시** (또는 workflow_dispatch) → 환경변수 적용 위해 재배포
3. **Google OAuth Console** → 자격 증명 → OAuth 2.0 클라이언트 → Authorized redirect URIs:
   ```
   https://kdating-chat-xxxxxxxx-an.a.run.app/auth/google/callback
   ```
4. **Stripe Dashboard** → Webhooks → Add endpoint:
   ```
   https://kdating-chat-xxxxxxxx-an.a.run.app/billing/webhook
   ```
   이벤트: `checkout.session.completed`, `customer.subscription.created`,
   `customer.subscription.updated`, `customer.subscription.deleted`,
   `customer.subscription.trial_will_end`, `invoice.payment_succeeded`,
   `invoice.payment_failed`
   생성된 webhook secret (whsec_...) 을 Secret Manager 에 업데이트:
   ```bash
   echo -n "whsec_..." | gcloud secrets versions add STRIPE_WEBHOOK_SECRET --data-file=-
   gcloud run services update kdating-chat --region=asia-northeast3 --update-secrets=STRIPE_WEBHOOK_SECRET=STRIPE_WEBHOOK_SECRET:latest
   ```

## 8. OAuth 동의 화면 게시

GCP 콘솔 → APIs & Services → OAuth consent screen:

- **앱 도메인**:
  - 홈페이지: `https://kdating-chat-xxxxxxxx-an.a.run.app`
  - 개인정보처리방침: `https://kdating-chat-xxxxxxxx-an.a.run.app/privacy`
  - 이용약관: `https://kdating-chat-xxxxxxxx-an.a.run.app/terms`
- **승인된 도메인**: `run.app` (이미 Google 등록된 public domain — 추가 verification 없이 사용 가능)
- **앱 로고**: 120×120 PNG 업로드 (선택)
- 페이지 하단 **"앱 게시"** 클릭 → "프로덕션 푸시" 확인

⚠️ Non-sensitive scope (`openid`, `email`, `profile`) 만 사용해서 **브랜드 검증만** 필요. 보안 평가·연간 평가 없음. 신청 후 3~5 영업일이면 통과. 그 사이에도 동작은 함 — 첫 ~100 사용자한테 "확인되지 않은 앱" 경고 페이지만 표시.

## 9. 검증

```bash
URL=https://kdating-chat-xxxxxxxx-an.a.run.app
curl -s $URL/me | jq            # billing_enabled: true 인지
curl -s $URL/privacy | head     # 약관 페이지 라이브
curl -s $URL/terms   | head
```

## 운영 — 자주 쓸 명령

```bash
# 로그 실시간
gcloud run services logs tail kdating-chat --region=asia-northeast3

# events.jsonl 확인 (critical 이벤트 감시)
gcloud storage cp gs://kdate-data/events.jsonl - | grep critical

# SQLite 백업 (수동)
gcloud storage cp gs://kdate-data/kdate_users.db ./backup-$(date +%F).db

# secret 값 교체
echo -n "새값" | gcloud secrets versions add SECRET_NAME --data-file=-
gcloud run services update kdating-chat --region=asia-northeast3 --update-secrets=SECRET_NAME=SECRET_NAME:latest
```

## 비용 예상 (월)

| 항목 | 비용 |
|---|---|
| Cloud Run (1 인스턴스 always-on, 1GB RAM) | ~$0 (무료 tier) |
| Cloud Build (배포 빌드) | ~$0 (120분 무료) |
| GCS (수 MB SQLite + JSONL) | ~$0 (5GB 무료) |
| Artifact Registry (Docker 이미지) | ~$0 (0.5GB 무료) |
| Secret Manager (10개 secret) | ~$0 (6개 무료 + 추가 4개 = $0.24) |
| **합계** | **$0 ~ $1** |

사용자 늘면 Cloud Run 요청 + outgoing bandwidth 가 가장 먼저 비용. 그래도 월 200만 요청까지 무료. 본격 매출 발생할 무렵 정확한 추정 다시.

## 한계

- **max-instances=1** — SQLite 단일 작성자 제약. 수백 동시 사용자까진 OK. 그 이상은 Firestore/Postgres 마이그레이션 필요.
- **GCS Fuse latency** — SQLite 쓰기 ~50ms (로컬 SSD 의 50배). 채팅 응답 자체엔 영향 X (Gemini API 가 압도적 지연).
- **첫 cold start** — min-instances=1 이라 사실상 없음. 단, 재배포 직후 ~5초 startup.

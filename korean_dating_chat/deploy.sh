#!/usr/bin/env bash
# Deploy to Cloud Run.
#
# Prereqs:
#   - gcloud CLI installed and authenticated (gcloud auth login)
#   - Application Default project set (gcloud config set project <PROJECT_ID>)
#   - Env vars (GEMINI_API_KEY, AZURE_SPEECH_KEY, etc.) already configured
#     on the kdating-chat service (Cloud Run console). They persist across
#     source deploys.
#
# Run from this directory: ./deploy.sh

set -euo pipefail

SERVICE="${SERVICE:-kdating-chat}"
REGION="${REGION:-asia-northeast3}"

echo "Deploying ${SERVICE} to ${REGION}..."

# --min/max-instances 를 반드시 함께 넘긴다.
# 이 플래그 없이 source deploy 하면 Cloud Run 이 해당 설정을 기본값으로 되돌린다.
# 실제로 그렇게 min-instances 가 0 으로 풀려서, 유휴 후 첫 요청이 수 초(최대 9초)
# 걸리는 콜드 스타트가 하루 30회 가까이 발생했다. deploy.yml 은 이미 둘 다 넘긴다.
#   max-instances=1 : SQLite 단일 작성자 제약
#   min-instances=1 : 콜드 스타트 제거
gcloud run deploy "${SERVICE}" \
  --source . \
  --region "${REGION}" \
  --allow-unauthenticated \
  --min-instances=1 \
  --max-instances=1

echo
echo "Done. URL:"
gcloud run services describe "${SERVICE}" \
  --region "${REGION}" \
  --format='value(status.url)'

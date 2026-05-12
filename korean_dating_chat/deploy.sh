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

gcloud run deploy "${SERVICE}" \
  --source . \
  --region "${REGION}" \
  --allow-unauthenticated

echo
echo "Done. URL:"
gcloud run services describe "${SERVICE}" \
  --region "${REGION}" \
  --format='value(status.url)'

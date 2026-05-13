# CI/CD

## `deploy.yml` — Cloud Run auto-deploy

Triggers on push to `main` touching `korean_dating_chat/**`, or on manual
`workflow_dispatch`. Builds from `korean_dating_chat/Dockerfile` and rolls a
new revision on the `kdating-chat` Cloud Run service in `asia-northeast3`.

### One-time setup

1. **Create a GCP service account** (in the same project that owns the existing
   Cloud Run service)

   ```bash
   gcloud iam service-accounts create github-actions-deployer \
     --display-name="GitHub Actions Deployer"
   ```

2. **Grant deploy roles** (replace `<PROJECT_ID>`):

   ```bash
   PROJECT_ID=<PROJECT_ID>
   SA="github-actions-deployer@${PROJECT_ID}.iam.gserviceaccount.com"

   for role in \
     roles/run.admin \
     roles/iam.serviceAccountUser \
     roles/cloudbuild.builds.editor \
     roles/artifactregistry.writer \
     roles/storage.admin \
     roles/logging.viewer; do
     gcloud projects add-iam-policy-binding "$PROJECT_ID" \
       --member="serviceAccount:$SA" --role="$role"
   done
   ```

3. **Create a JSON key**:

   ```bash
   gcloud iam service-accounts keys create key.json \
     --iam-account="$SA"
   ```

4. **Add the key to GitHub Secrets**:
   GitHub repo → Settings → Secrets and variables → Actions →
   New repository secret →
   - Name: `GCP_SA_KEY`
   - Value: paste the full contents of `key.json`

   Then delete `key.json` locally.

### Deploying

- **Auto**: merge to `main` (any change under `korean_dating_chat/`).
- **Manual**: GitHub → Actions → "Deploy to Cloud Run" → Run workflow → pick branch.

### Runtime env vars

`GEMINI_API_KEY`, `AZURE_SPEECH_KEY`, etc. live on the Cloud Run service
configuration, not in this workflow. Source-deploy preserves them.

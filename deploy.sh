#!/usr/bin/env bash
# Automated Google Cloud Run deployment script for Process at a Glance (PAAG).
# Usage:
#   PROJECT_ID="my-gcp-project" GCS_BUCKET="my-paag-persistence-bucket" ./deploy.sh

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || true)}"
REGION="${REGION:-us-central1}"
AR_REPO="${AR_REPO:-paag-repo}"
SERVICE_NAME="${SERVICE_NAME:-paag-app}"
GCS_BUCKET="${GCS_BUCKET:-${PROJECT_ID}-paag-state}"
GCS_PREFIX="${GCS_PREFIX:-paag-state}"
MEMORY="${MEMORY:-2Gi}"
CPU="${CPU:-2}"
CONCURRENCY="${CONCURRENCY:-80}"
CACHE_MAX_MB="${CACHE_MAX_MB:-256}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "ERROR: PROJECT_ID is not set. Export PROJECT_ID or run 'gcloud config set project <PROJECT_ID>'." >&2
  exit 1
fi

echo "==> Configuring GCP project: ${PROJECT_ID} (${REGION})"
gcloud config set project "${PROJECT_ID}"

echo "==> Enabling required GCP APIs..."
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  storage.googleapis.com \
  iap.googleapis.com

echo "==> Ensuring Artifact Registry repository '${AR_REPO}' exists..."
if ! gcloud artifacts repositories describe "${AR_REPO}" --location="${REGION}" >/dev/null 2>&1; then
  gcloud artifacts repositories create "${AR_REPO}" \
    --repository-format=docker \
    --location="${REGION}" \
    --description="PAAG container images"
fi

echo "==> Ensuring GCS persistence bucket 'gs://${GCS_BUCKET}' exists..."
if ! gcloud storage buckets describe "gs://${GCS_BUCKET}" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${GCS_BUCKET}" \
    --location="${REGION}" \
    --uniform-bucket-level-access
  gcloud storage buckets update "gs://${GCS_BUCKET}" --versioning
fi

IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${SERVICE_NAME}:latest"

echo "==> Building and pushing container image via Cloud Build: ${IMAGE_URI}"
gcloud builds submit --tag "${IMAGE_URI}" .

echo "==> Deploying '${SERVICE_NAME}' to Cloud Run (max-instances=1, session-affinity, GCS sync)..."
gcloud run deploy "${SERVICE_NAME}" \
  --image="${IMAGE_URI}" \
  --region="${REGION}" \
  --platform=managed \
  --execution-environment=gen2 \
  --max-instances=1 \
  --concurrency="${CONCURRENCY}" \
  --cpu="${CPU}" \
  --memory="${MEMORY}" \
  --timeout=3600 \
  --session-affinity \
  --set-env-vars="PAAG_GCS_BUCKET=${GCS_BUCKET},PAAG_GCS_PREFIX=${GCS_PREFIX},PAAG_CACHE_MAX_MB=${CACHE_MAX_MB}"

echo "==> Deployment complete."
gcloud run services describe "${SERVICE_NAME}" --region="${REGION}" --format="value(status.url)"

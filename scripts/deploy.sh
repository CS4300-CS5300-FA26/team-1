#!/usr/bin/env bash
# Deploy an existing FitPro image (already pushed to Artifact Registry) to GKE.
# Builds and pushes nothing. Used manually (Git Bash on Windows) and by GitHub Actions.
#
# Usage:
#   IMAGE_TAG=<full git sha> scripts/deploy.sh [--dry-run] [--skip-smoke]
#   scripts/deploy.sh -h | --help
#
# Flags:
#   --dry-run     Run preflight, render, and `kubectl apply --dry-run=server`, then exit.
#                 Changes nothing on the cluster.
#   --skip-smoke  Skip the HTTPS smoke test. Useful on the very first deploy, when the
#                 load balancer and certificate can take 10+ minutes to provision.
#   -h, --help    Show this header.
#
# Environment:
#   IMAGE_TAG        (required) full 40-character git SHA of the image to deploy
#   PROJECT_ID       default: project_id in terraform_scripts/terraform.tfvars
#   REGION           default: us-central1
#   CLUSTER          default: fitpro
#   NAMESPACE        default: app
#   DEPLOYMENT       default: django-app
#   OVERLAY          default: k8s/app/overlays/prod   (relative to the repo root, under k8s/)
#   MIGRATE_JOB      default: k8s/app/jobs/migrate-job.yaml
#   ROLLOUT_TIMEOUT  default: 600s
#   MIGRATE_TIMEOUT  default: 600s
# The image repository is read from the overlay's `images` entry (newName).
#
# Prerequisites: kubectl, gcloud (and curl unless --skip-smoke). The current kubectl
# context must be gke_<project>_<region>_<cluster>; get it with
#   gcloud container clusters get-credentials fitpro --region us-central1 --dns-endpoint
# (google-github-actions/get-gke-credentials uses the same context name by default).
#
# Steps: preflight -> render (temp dir) -> migrate Job -> apply overlay + rollout ->
# smoke test -> summary. A failed rollout or smoke test rolls the Deployment back to
# the revision that was live before this run. Migrations are never rolled back, and
# other applied resources (ConfigMap, routes, ...) stay at the new version.
#
# Exit codes:
#   0  success (or dry run passed)
#   1  usage error or unexpected failure
#   2  preflight failed (wrong cluster, missing namespace/image/tool, bad render)
#   3  migration Job failed or timed out (Deployment not touched)
#   4  rollout failed (Deployment rolled back)
#   5  smoke test failed (Deployment rolled back)
set -euo pipefail

readonly EXIT_USAGE=1 EXIT_PREFLIGHT=2 EXIT_MIGRATE=3 EXIT_ROLLOUT=4 EXIT_SMOKE=5
readonly SMOKE_TIMEOUT_SECONDS=300 SMOKE_INTERVAL_SECONDS=10

usage() { sed -n '2,/^set -euo pipefail/{/^set /d;s/^# \{0,1\}//;p}' "$0"; }
log() { printf '\n==> %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die() { local code=$1; shift; printf 'ERROR: %s\n' "$*" >&2; exit "$code"; }

DRY_RUN=false
SKIP_SMOKE=false
while (($#)); do
  case "$1" in
    --dry-run) DRY_RUN=true ;;
    --skip-smoke) SKIP_SMOKE=true ;;
    -h | --help) usage; exit 0 ;;
    *) usage >&2; die "$EXIT_USAGE" "unknown argument: $1" ;;
  esac
  shift
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

IMAGE_TAG="${IMAGE_TAG:-}"
REGION="${REGION:-us-central1}"
CLUSTER="${CLUSTER:-fitpro}"
NAMESPACE="${NAMESPACE:-app}"
DEPLOYMENT="${DEPLOYMENT:-django-app}"
OVERLAY="${OVERLAY:-k8s/app/overlays/prod}"
MIGRATE_JOB="${MIGRATE_JOB:-k8s/app/jobs/migrate-job.yaml}"
ROLLOUT_TIMEOUT="${ROLLOUT_TIMEOUT:-600s}"
MIGRATE_TIMEOUT="${MIGRATE_TIMEOUT:-600s}"

TFVARS="terraform_scripts/terraform.tfvars"
if [[ -z "${PROJECT_ID:-}" && -f "$TFVARS" ]]; then
  PROJECT_ID="$(sed -n 's/^[[:space:]]*project_id[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' "$TFVARS" | tr -d '\r' | head -n1)"
fi
PROJECT_ID="${PROJECT_ID:-}"

# Convert "600", "600s", or "10m" to seconds.
to_seconds() {
  case "$1" in
    *m) echo $((${1%m} * 60)) ;;
    *s) echo "${1%s}" ;;
    *) echo "$1" ;;
  esac
}

# Results for the summary.
JOB_RESULT="not run"
ROLLOUT_RESULT="not run"
SMOKE_RESULT="not run"
PREV_REVISION=""

summary() {
  log "Summary"
  printf '  Image tag : %s\n' "$IMAGE_TAG"
  printf '  Migration : %s\n' "$JOB_RESULT"
  printf '  Rollout   : %s\n' "$ROLLOUT_RESULT"
  printf '  Smoke test: %s\n' "$SMOKE_RESULT"
}

# ---------------------------------------------------------------- 1. preflight
log "Preflight"

[[ "$IMAGE_TAG" =~ ^[0-9a-f]{40}$ ]] || die "$EXIT_USAGE" "IMAGE_TAG must be a full 40-character git SHA (got: '${IMAGE_TAG}')"
[[ -n "$PROJECT_ID" ]] || die "$EXIT_PREFLIGHT" "PROJECT_ID is not set and could not be read from $TFVARS"
[[ "$ROLLOUT_TIMEOUT" =~ ^[0-9]+[sm]?$ ]] || die "$EXIT_USAGE" "ROLLOUT_TIMEOUT must look like 600s or 10m"
[[ "$MIGRATE_TIMEOUT" =~ ^[0-9]+[sm]?$ ]] || die "$EXIT_USAGE" "MIGRATE_TIMEOUT must look like 600s or 10m"

required_tools=(kubectl gcloud)
$SKIP_SMOKE || $DRY_RUN || required_tools+=(curl)
for tool in "${required_tools[@]}"; do
  command -v "$tool" >/dev/null 2>&1 || die "$EXIT_PREFLIGHT" "required tool not found on PATH: $tool"
done

[[ "$OVERLAY" == k8s/* && -f "$OVERLAY/kustomization.yaml" ]] || die "$EXIT_PREFLIGHT" "OVERLAY must be a kustomization directory under k8s/: $OVERLAY"
[[ -f "$MIGRATE_JOB" ]] || die "$EXIT_PREFLIGHT" "MIGRATE_JOB not found: $MIGRATE_JOB"

expected_context="gke_${PROJECT_ID}_${REGION}_${CLUSTER}"
current_context="$(kubectl config current-context 2>/dev/null | tr -d '\r' || true)"
if [[ "$current_context" != "$expected_context" ]]; then
  die "$EXIT_PREFLIGHT" "kubectl context is '${current_context:-<none>}', expected '$expected_context'.
       Run: gcloud container clusters get-credentials $CLUSTER --region $REGION --project $PROJECT_ID --dns-endpoint"
fi
echo "kubectl context: $current_context"

kubectl get namespace "$NAMESPACE" >/dev/null 2>&1 \
  || die "$EXIT_PREFLIGHT" "namespace '$NAMESPACE' not found (apply k8s/platform first) or the cluster is unreachable"
echo "namespace: $NAMESPACE"

mapfile -t image_names < <(sed -n 's/^[[:space:]]*newName:[[:space:]]*//p' "$OVERLAY/kustomization.yaml" | tr -d '\r"' | sed 's/[[:space:]]*$//')
((${#image_names[@]} == 1)) || die "$EXIT_PREFLIGHT" "expected exactly one images[].newName in $OVERLAY/kustomization.yaml, found ${#image_names[@]}"
IMAGE_REPO="${image_names[0]}"
IMAGE="${IMAGE_REPO}:${IMAGE_TAG}"

gcloud artifacts docker images describe "$IMAGE" --project "$PROJECT_ID" --format='value(image_summary.digest)' >/dev/null 2>&1 \
  || die "$EXIT_PREFLIGHT" "image not found in Artifact Registry (or no access): $IMAGE"
echo "image: $IMAGE"

# ---------------------------------------------------------------- 2. render
log "Render"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Copy k8s/ so the overlay's relative paths (../../base) still resolve, and strip CRs
# (Windows checkouts) so the edits below match. Nothing in the repo is modified.
cp -R k8s "$WORK/k8s"
find "$WORK/k8s" -type f \( -name '*.yaml' -o -name '*.yml' \) -exec sed -i 's/\r$//' {} +

work_overlay="$WORK/$OVERLAY"
work_kustomization="$work_overlay/kustomization.yaml"
JOB_NAME="django-migrate-${IMAGE_TAG}"
((${#JOB_NAME} <= 63)) || die "$EXIT_PREFLIGHT" "Job name exceeds 63 characters: $JOB_NAME"

# kustomize refuses to load files outside the kustomization directory, so put the
# Job inside the (temporary) overlay directory instead of relaxing the restriction.
sed 's/^  name: django-migrate$/  name: '"$JOB_NAME"'/' "$WORK/$MIGRATE_JOB" > "$work_overlay/migrate-job.yaml"
grep -q "^  name: ${JOB_NAME}\$" "$work_overlay/migrate-job.yaml" \
  || die "$EXIT_PREFLIGHT" "could not rename the Job in $MIGRATE_JOB (expected metadata.name: django-migrate)"

# Add the Job to resources and pin the image tag (exactly one of each must exist).
(($(grep -c '^resources:' "$work_kustomization") == 1)) || die "$EXIT_PREFLIGHT" "expected one top-level 'resources:' in $OVERLAY/kustomization.yaml"
(($(grep -c '^[[:space:]]*newTag:' "$work_kustomization") == 1)) || die "$EXIT_PREFLIGHT" "expected one images[].newTag in $OVERLAY/kustomization.yaml"
sed -i -e '/^resources:/a\  - migrate-job.yaml' \
       -e 's/^\([[:space:]]*newTag:\).*/\1 "'"$IMAGE_TAG"'"/' "$work_kustomization"

kubectl kustomize "$work_overlay" > "$WORK/rendered.yaml" || die "$EXIT_PREFLIGHT" "kustomize render failed"

# Split the multi-document output into one file per object.
mkdir -p "$WORK/split"
awk -v dir="$WORK/split" '
  function flush() { if (buf != "") { n++; f = sprintf("%s/%03d.yaml", dir, n); printf "%s", buf > f; close(f); buf = "" } }
  /^---$/ { flush(); next }
  { buf = buf $0 "\n" }
  END { flush() }
' "$WORK/rendered.yaml"

: > "$WORK/configmaps.yaml"
: > "$WORK/job.yaml"
: > "$WORK/app.yaml"
for doc in "$WORK"/split/*.yaml; do
  kind="$(sed -n 's/^kind:[[:space:]]*//p' "$doc" | head -n1)"
  case "$kind" in
    Job) target="$WORK/job.yaml" ;;
    ConfigMap) target="$WORK/configmaps.yaml"; { echo '---'; cat "$doc"; } >> "$WORK/app.yaml" ;;
    *) target="$WORK/app.yaml" ;;
  esac
  { echo '---'; cat "$doc"; } >> "$target"
done

# Sanity checks: the Job and Deployment must share image, ConfigMap, and proxy config.
[[ -s "$WORK/job.yaml" && -s "$WORK/configmaps.yaml" ]] || die "$EXIT_PREFLIGHT" "render is missing the Job or ConfigMap"
grep -q "image: ${IMAGE}\$" "$WORK/job.yaml" || die "$EXIT_PREFLIGHT" "rendered Job does not use $IMAGE"
grep -q "image: ${IMAGE}\$" "$WORK/app.yaml" || die "$EXIT_PREFLIGHT" "rendered Deployment does not use $IMAGE"
grep -q 'CSQL_PROXY_INSTANCE_CONNECTION_NAME' "$WORK/job.yaml" || die "$EXIT_PREFLIGHT" "rendered Job has no proxy connection name"
grep -q "namespace: ${NAMESPACE}\$" "$WORK/job.yaml" || die "$EXIT_PREFLIGHT" "rendered Job is not in namespace $NAMESPACE"
config_name="$(sed -n 's/^  name:[[:space:]]*//p' "$WORK/configmaps.yaml" | head -n1)"
grep -q "name: ${config_name}\$" "$WORK/job.yaml" || die "$EXIT_PREFLIGHT" "rendered Job does not reference ConfigMap $config_name"
rendered_docs=("$WORK"/split/*.yaml)
echo "rendered ${#rendered_docs[@]} objects; Job $JOB_NAME; ConfigMap $config_name"

# Hostname for the smoke test: first hostname of the HTTPRoute that has backends.
SMOKE_HOST=""
for doc in "$WORK"/split/*.yaml; do
  if grep -q '^kind: HTTPRoute$' "$doc" && grep -q 'backendRefs:' "$doc"; then
    SMOKE_HOST="$(awk '/^  hostnames:/ { getline; sub(/^[[:space:]]*-[[:space:]]*/, ""); print; exit }' "$doc")"
    break
  fi
done

if $DRY_RUN; then
  log "Server-side dry run"
  kubectl apply --dry-run=server -f "$WORK/app.yaml"
  if kubectl -n "$NAMESPACE" get job "$JOB_NAME" >/dev/null 2>&1; then
    echo "job.batch/$JOB_NAME already exists; a real deploy would delete and recreate it"
  else
    kubectl apply --dry-run=server -f "$WORK/job.yaml"
  fi
  echo
  echo "Dry run passed. Smoke test host would be: ${SMOKE_HOST:-<none found>}"
  exit 0
fi

# ---------------------------------------------------------------- 3. migrate
job_diagnostics() {
  log "Migration Job diagnostics ($JOB_NAME)"
  kubectl -n "$NAMESPACE" describe job "$JOB_NAME" || true
  local pods pod
  pods="$(kubectl -n "$NAMESPACE" get pods -l "job-name=$JOB_NAME" -o name 2>/dev/null | tr -d '\r' || true)"
  for pod in $pods; do
    echo "--- events for $pod"
    kubectl -n "$NAMESPACE" get events --field-selector "involvedObject.name=${pod#pod/}" --sort-by=.lastTimestamp || true
    echo "--- logs: $pod (django)"
    kubectl -n "$NAMESPACE" logs "$pod" -c django --tail=200 || true
    echo "--- logs: $pod (cloud-sql-proxy)"
    kubectl -n "$NAMESPACE" logs "$pod" -c cloud-sql-proxy --tail=100 || true
  done
  echo "--- events for job/$JOB_NAME"
  kubectl -n "$NAMESPACE" get events --field-selector "involvedObject.name=$JOB_NAME" --sort-by=.lastTimestamp || true
}

log "Migrate"
kubectl apply -f "$WORK/configmaps.yaml"
if kubectl -n "$NAMESPACE" get job "$JOB_NAME" >/dev/null 2>&1; then
  echo "Job $JOB_NAME already exists (re-deploying the same SHA); deleting it first"
  kubectl -n "$NAMESPACE" delete job "$JOB_NAME" --cascade=foreground --wait=true
fi
kubectl apply -f "$WORK/job.yaml"

migrate_deadline=$((SECONDS + $(to_seconds "$MIGRATE_TIMEOUT")))
while :; do
  conditions="$(kubectl -n "$NAMESPACE" get job "$JOB_NAME" \
    -o jsonpath='{range .status.conditions[?(@.status=="True")]}{.type}{" "}{end}' 2>/dev/null | tr -d '\r' || true)"
  if [[ " $conditions " == *" Complete "* ]]; then
    JOB_RESULT="succeeded ($JOB_NAME)"
    echo "Migration Job completed"
    break
  fi
  if [[ " $conditions " == *" Failed "* ]]; then
    JOB_RESULT="failed ($JOB_NAME)"
    job_diagnostics
    summary
    die "$EXIT_MIGRATE" "migration Job failed; the Deployment was not updated"
  fi
  if ((SECONDS >= migrate_deadline)); then
    JOB_RESULT="timed out after $MIGRATE_TIMEOUT ($JOB_NAME)"
    job_diagnostics
    summary
    die "$EXIT_MIGRATE" "migration Job did not finish within $MIGRATE_TIMEOUT; the Deployment was not updated"
  fi
  sleep 5
done

# ---------------------------------------------------------------- 4. deploy
current_revision() {
  kubectl -n "$NAMESPACE" get deployment "$DEPLOYMENT" \
    -o jsonpath='{.metadata.annotations.deployment\.kubernetes\.io/revision}' 2>/dev/null | tr -d '\r' || true
}

deployment_diagnostics() {
  log "Deployment diagnostics ($DEPLOYMENT)"
  local selector="app.kubernetes.io/name=$DEPLOYMENT" pod ready
  kubectl -n "$NAMESPACE" get pods -l "$selector" -o wide || true
  for pod in $(kubectl -n "$NAMESPACE" get pods -l "$selector" -o name 2>/dev/null | tr -d '\r'); do
    ready="$(kubectl -n "$NAMESPACE" get "$pod" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null | tr -d '\r' || true)"
    [[ "$ready" == "True" ]] && continue
    echo "--- describe $pod (not ready)"
    kubectl -n "$NAMESPACE" describe "$pod" || true
    echo "--- logs: $pod (django)"
    kubectl -n "$NAMESPACE" logs "$pod" -c django --tail=100 || true
    echo "--- logs: $pod (cloud-sql-proxy)"
    kubectl -n "$NAMESPACE" logs "$pod" -c cloud-sql-proxy --tail=50 || true
  done
  echo "--- recent events in $NAMESPACE"
  kubectl -n "$NAMESPACE" get events --sort-by=.lastTimestamp | tail -n 30 || true
}

# Roll back to the revision that was live before this run (not just "the previous
# one", which would be wrong if this run didn't create a new revision).
rollback() {
  local now
  now="$(current_revision)"
  if [[ -z "$PREV_REVISION" ]]; then
    warn "no previous revision (first deploy); nothing to roll back to"
    return 1
  fi
  if [[ "$now" == "$PREV_REVISION" ]]; then
    warn "Deployment is still on revision $PREV_REVISION; nothing to roll back"
    return 0
  fi
  log "Rolling back $DEPLOYMENT to revision $PREV_REVISION"
  kubectl -n "$NAMESPACE" rollout undo "deployment/$DEPLOYMENT" --to-revision="$PREV_REVISION" \
    && kubectl -n "$NAMESPACE" rollout status "deployment/$DEPLOYMENT" --timeout="$ROLLOUT_TIMEOUT"
}

log "Deploy"
PREV_REVISION="$(current_revision)"
echo "revision before deploy: ${PREV_REVISION:-<none>}"
kubectl apply -f "$WORK/app.yaml"

if kubectl -n "$NAMESPACE" rollout status "deployment/$DEPLOYMENT" --timeout="$ROLLOUT_TIMEOUT"; then
  ROLLOUT_RESULT="succeeded (revision $(current_revision))"
else
  deployment_diagnostics
  if rollback; then
    ROLLOUT_RESULT="failed; rolled back to revision $PREV_REVISION"
  else
    ROLLOUT_RESULT="failed; ROLLBACK DID NOT COMPLETE, check the cluster"
  fi
  summary
  die "$EXIT_ROLLOUT" "rollout failed"
fi

# ---------------------------------------------------------------- 5. smoke test
http_status() {
  curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$1" 2>/dev/null || echo 000
}

if $SKIP_SMOKE; then
  SMOKE_RESULT="skipped (--skip-smoke)"
else
  log "Smoke test"
  if [[ -z "$SMOKE_HOST" ]]; then
    SMOKE_RESULT="failed: no hostname found in the rendered HTTPRoute"
  else
    smoke_deadline=$((SECONDS + SMOKE_TIMEOUT_SECONDS))
    while :; do
      health="$(http_status "https://$SMOKE_HOST/healthz/")"
      root="$(http_status "https://$SMOKE_HOST/")"
      echo "https://$SMOKE_HOST/healthz/ -> $health, https://$SMOKE_HOST/ -> $root"
      if [[ "$health" == 200 && ("$root" == 200 || "$root" == 3??) ]]; then
        SMOKE_RESULT="passed (/healthz/ $health, / $root)"
        break
      fi
      if ((SECONDS >= smoke_deadline)); then
        SMOKE_RESULT="failed after ${SMOKE_TIMEOUT_SECONDS}s (/healthz/ $health, / $root)"
        break
      fi
      sleep "$SMOKE_INTERVAL_SECONDS"
    done
  fi

  if [[ "$SMOKE_RESULT" == failed* ]]; then
    if rollback; then
      ROLLOUT_RESULT="$ROLLOUT_RESULT; rolled back to revision $PREV_REVISION after smoke test"
    else
      ROLLOUT_RESULT="$ROLLOUT_RESULT; ROLLBACK DID NOT COMPLETE, check the cluster"
    fi
    summary
    die "$EXIT_SMOKE" "smoke test failed"
  fi
fi

# ---------------------------------------------------------------- 6. summary
summary
echo
echo "Deployed $IMAGE"

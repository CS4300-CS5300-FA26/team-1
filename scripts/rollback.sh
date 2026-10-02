#!/usr/bin/env bash
# Roll the FitPro deployment back to a previous revision.
#
# Usage: PROJECT_ID=... CLUSTER=... REGION=... scripts/rollback.sh [REVISION]
#   REVISION  optional revision number from `kubectl rollout history`;
#             defaults to the previous revision.
set -euo pipefail

: "${PROJECT_ID:?PROJECT_ID must be set}"
: "${CLUSTER:?CLUSTER must be set}"
: "${REGION:?REGION must be set}"
NAMESPACE="${NAMESPACE:-app}"
DEPLOYMENT="${DEPLOYMENT:-django-app}"
REVISION="${1:-}"

if [[ -n "$REVISION" && ! "$REVISION" =~ ^[0-9]+$ ]]; then
  echo "REVISION must be a number, got: $REVISION" >&2
  exit 1
fi

print_images() {
  kubectl -n "$NAMESPACE" get deployment "$DEPLOYMENT" \
    -o jsonpath='{range .spec.template.spec.containers[*]}  {.name}: {.image}{"\n"}{end}'
}

# The cluster's IP endpoint is disabled, so credentials must use the DNS endpoint.
gcloud container clusters get-credentials "$CLUSTER" \
  --project "$PROJECT_ID" --location "$REGION" --dns-endpoint

echo
echo "Current images for $NAMESPACE/$DEPLOYMENT:"
print_images
echo
kubectl -n "$NAMESPACE" rollout history deployment "$DEPLOYMENT"

target="the previous revision"
[[ -n "$REVISION" ]] && target="revision $REVISION"
read -r -p "Roll back $NAMESPACE/$DEPLOYMENT to $target? [y/N] " answer
if [[ ! "$answer" =~ ^[Yy]$ ]]; then
  echo "Aborted."
  exit 1
fi

undo_args=()
[[ -n "$REVISION" ]] && undo_args+=(--to-revision="$REVISION")
kubectl -n "$NAMESPACE" rollout undo deployment "$DEPLOYMENT" ${undo_args[@]+"${undo_args[@]}"}
kubectl -n "$NAMESPACE" rollout status deployment "$DEPLOYMENT" --timeout=300s

echo
echo "New images for $NAMESPACE/$DEPLOYMENT:"
print_images

cat <<'EOF'

Rollback complete. Next steps:
  * Revert the bad commit on main (git revert + PR). Otherwise the next merge
    redeploys from main, including the broken change.
  * Database migrations were NOT undone. If the bad release ran migrations, make
    sure the rolled-back code still works with the current schema, or write a
    reverse migration.
EOF

#!/usr/bin/env bash
set -euo pipefail

name=engrammic-dev-box
zone=europe-north1-a
project=engrammic

case "${1:-ssh}" in
  ssh)    tailscale ssh dev@$name ;;
  iap)    gcloud compute ssh $name --zone=$zone --project=$project --tunnel-through-iap ;;
  start)  gcloud compute instances start $name --zone=$zone --project=$project ;;
  stop)   gcloud compute instances stop $name --zone=$zone --project=$project ;;
  status)
    gcloud compute instances describe $name --zone=$zone --project=$project --format="value(status)"
    tailscale status | grep $name || echo "not on tailnet"
    ;;
  *) echo "unknown action '$1' (ssh|iap|start|stop|status)" >&2; exit 1 ;;
esac

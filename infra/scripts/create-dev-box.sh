#!/bin/bash
# Create engrammic-dev-box: a lightweight personal dev VM, reachable over
# Tailscale SSH, on the existing dev VPC (no public IP, NAT egress).
#
# Standalone gcloud provisioning - deliberately NOT through Pulumi, because the
# `dev` Pulumi stack currently has destructive drift (would delete the running
# SigNoz host). This touches no Pulumi state and nothing in beta.
#
# Prerequisite: the Tailscale auth key must already be in Secret Manager as
# `engrammic-dev-tailscale-authkey`, and the dev SA must have accessor on it.
set -euo pipefail

PROJECT="engrammic"
ZONE="europe-north1-a"
NAME="engrammic-dev-box"
SA="stateful-host-dev@engrammic.iam.gserviceaccount.com"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

gcloud compute instances create "$NAME" \
    --project="$PROJECT" --zone="$ZONE" \
    --machine-type=e2-standard-2 \
    --provisioning-model=SPOT --no-restart-on-failure \
    --image-family=debian-12 --image-project=debian-cloud \
    --boot-disk-size=30GB --boot-disk-type=pd-balanced \
    --network=engrammic-dev-vpc --subnet=engrammic-dev-private --no-address \
    --service-account="$SA" \
    --scopes=cloud-platform \
    --metadata-from-file=startup-script="$SCRIPT_DIR/dev-box-startup.sh"

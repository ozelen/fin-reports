#!/bin/sh
# Replay local salary-client seed on TrueNAS prod (k3s ix-charts).
#
# Wait until the backup job has landed, then run from this Mac:
#   ./scripts/sync_salary_clients_prod.sh
#
# Does: copy agreement PDFs into the API pod, upsert clients,
# upload documents, match salary inflows. Idempotent.
set -eu

HOST="${NAS_HOST:-ozelen@192.168.1.185}"
NS="${API_NS:-ix-income-share-api}"
REMOTE_DIR="/tmp/agreements"
CMD_LOCAL="$(cd "$(dirname "$0")/.." && pwd)/backend/core/management/commands/sync_salary_clients.py"
AUTODESK_DIR="/Users/oleksiyzelenyuk/Library/Mobile Documents/com~apple~CloudDocs/[00] Root/[03] Job/[06] Autodesk"

PINUP_LOCAL=""
for p in \
  "/Users/oleksiyzelenyuk/.cursor/projects/Users-oleksiyzelenyuk-Projects-income-share/attachments/d2f081fb-4e2c-49a9-a0b6-cf83ee676160/Software_development_Oleksiy_Zelenyuk_signed_both.pdf" \
  "/Users/oleksiyzelenyuk/Library/Mobile Documents/com~apple~CloudDocs/[00] Root/[01] Documents/[01] Oleksiy/[02] Spanish/[02] Autonomo/[04] Agreements/[01] Pin-Up/Software development_Oleksiy Zelenyuk_signed_both.pdf"
do
  if [ -f "$p" ]; then PINUP_LOCAL="$p"; break; fi
done

BLACKTHORN_LOCAL=""
for p in \
  "/Users/oleksiyzelenyuk/.cursor/projects/Users-oleksiyzelenyuk-Projects-income-share/attachments/d2f081fb-4e2c-49a9-a0b6-cf83ee676160/SA_DEV0226_BlackthornAI_Oleksiy_Zelenyuk.pdf" \
  "/Users/oleksiyzelenyuk/Library/Mobile Documents/com~apple~CloudDocs/[00] Root/[01] Documents/[01] Oleksiy/[02] Spanish/[02] Autonomo/[04] Agreements/Blackthorn/SA DEV0226 BlackthornAI_Oleksiy Zelenyuk.pdf"
do
  if [ -f "$p" ]; then BLACKTHORN_LOCAL="$p"; break; fi
done

if [ -z "$PINUP_LOCAL" ] || [ -z "$BLACKTHORN_LOCAL" ]; then
  echo "Need both agreement PDFs on this Mac." >&2
  echo "Pin-Up: ${PINUP_LOCAL:-missing}" >&2
  echo "Blackthorn: ${BLACKTHORN_LOCAL:-missing}" >&2
  exit 1
fi

CONTRACT_LOCAL="$AUTODESK_DIR/Oleksiy_Zelenyuk__Autodesk_September_2026_SIGNED (2).pdf"
NDA_LOCAL="$AUTODESK_DIR/Autodesk Contingent Worker Onboarding Documents_NDA_SIGNED.pdf"
INSURANCE_LOCAL="$AUTODESK_DIR/Fenero Umbrella Insurance Certificate 26-27 (1).pdf"
POLICY_LOCAL="$AUTODESK_DIR/Policy Schedule Document - Shareable (1) (1).pdf"

for f in "$CONTRACT_LOCAL" "$NDA_LOCAL" "$INSURANCE_LOCAL" "$POLICY_LOCAL" "$CMD_LOCAL"; do
  if [ ! -f "$f" ]; then
    echo "Missing: $f" >&2
    exit 1
  fi
done

echo "Pin-Up: $PINUP_LOCAL"
echo "Blackthorn: $BLACKTHORN_LOCAL"
echo "Autodesk contract: $CONTRACT_LOCAL"

POD=$(ssh -o BatchMode=yes "$HOST" \
  "sudo k3s kubectl -n $NS get pods --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}'")
if [ -z "$POD" ]; then
  echo "No pod in $NS" >&2
  exit 1
fi
echo "Pod: $POD"

ssh -o BatchMode=yes "$HOST" "sudo k3s kubectl -n $NS exec $POD -- mkdir -p $REMOTE_DIR"

# Host → NAS /tmp, then kubectl cp into the pod (kubectl cp wants a local path on the NAS).
scp -o BatchMode=yes "$PINUP_LOCAL" "$HOST:/tmp/pinup.pdf"
scp -o BatchMode=yes "$BLACKTHORN_LOCAL" "$HOST:/tmp/blackthorn.pdf"
scp -o BatchMode=yes "$CONTRACT_LOCAL" "$HOST:/tmp/autodesk-contract.pdf"
scp -o BatchMode=yes "$NDA_LOCAL" "$HOST:/tmp/autodesk-nda.pdf"
scp -o BatchMode=yes "$INSURANCE_LOCAL" "$HOST:/tmp/autodesk-insurance.pdf"
scp -o BatchMode=yes "$POLICY_LOCAL" "$HOST:/tmp/autodesk-policy.pdf"
scp -o BatchMode=yes "$CMD_LOCAL" "$HOST:/tmp/sync_salary_clients.py"
ssh -o BatchMode=yes "$HOST" \
  "sudo k3s kubectl -n $NS cp /tmp/pinup.pdf $POD:$REMOTE_DIR/pinup.pdf && \
   sudo k3s kubectl -n $NS cp /tmp/blackthorn.pdf $POD:$REMOTE_DIR/blackthorn.pdf && \
   sudo k3s kubectl -n $NS cp /tmp/autodesk-contract.pdf $POD:$REMOTE_DIR/autodesk-contract.pdf && \
   sudo k3s kubectl -n $NS cp /tmp/autodesk-nda.pdf $POD:$REMOTE_DIR/autodesk-nda.pdf && \
   sudo k3s kubectl -n $NS cp /tmp/autodesk-insurance.pdf $POD:$REMOTE_DIR/autodesk-insurance.pdf && \
   sudo k3s kubectl -n $NS cp /tmp/autodesk-policy.pdf $POD:$REMOTE_DIR/autodesk-policy.pdf && \
   sudo k3s kubectl -n $NS cp /tmp/sync_salary_clients.py $POD:/app/core/management/commands/sync_salary_clients.py && \
   rm -f /tmp/pinup.pdf /tmp/blackthorn.pdf /tmp/autodesk-*.pdf /tmp/sync_salary_clients.py"

ONLY_NAME="${1:-}"
if [ -n "$ONLY_NAME" ]; then
  ssh -o BatchMode=yes "$HOST" \
    "sudo k3s kubectl -n $NS exec $POD -- \
       python manage.py sync_salary_clients --username ozelen --docs-dir $REMOTE_DIR --name \"$ONLY_NAME\""
else
  ssh -o BatchMode=yes "$HOST" \
    "sudo k3s kubectl -n $NS exec $POD -- \
       python manage.py sync_salary_clients --username ozelen --docs-dir $REMOTE_DIR"
fi

echo "Done. Check Clients + Taxes on http://192.168.1.185:18022/ (or https://fin.zelen.uk)."

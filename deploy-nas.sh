#!/usr/bin/env bash
# Envia para a NAS QNAP o .tar da imagem e, com --dados, o que a app precisa para
# continuar de onde o Mac ficou. O import na Container Station é manual — ver
# DEPLOY-NAS.md.
#
#   ./deploy-nas.sh /tmp/cristopher-nas-v1.tar           # só a imagem
#   ./deploy-nas.sh --dados                               # só os dados
#   ./deploy-nas.sh /tmp/cristopher-nas-v1.tar --dados   # os dois
#
# --dados leva: uma fotografia da base, os recibos, o token do Garmin, a chave do
# banco e as chaves dos avisos. Recusa-se a pisar uma base que já esteja na NAS —
# depois de a app lá correr, a base da NAS é a verdadeira. --forcar passa por cima.
#
# Credenciais: .env.nas (ver .env.nas.example) ou variáveis de ambiente.
set -euo pipefail

cd "$(dirname "$0")"
[ -f .env.nas ] && source .env.nas

TAR=""
DADOS=false
FORCAR=false
for arg in "$@"; do
  case "$arg" in
    --dados) DADOS=true ;;
    --forcar) FORCAR=true ;;
    *) TAR="$arg" ;;
  esac
done
[ -n "$TAR" ] || $DADOS || { echo "uso: ./deploy-nas.sh [imagem.tar] [--dados] [--forcar]"; exit 1; }
[ -z "$TAR" ] || [ -f "$TAR" ] || { echo "não existe: $TAR"; exit 1; }

NAS_HOST="${NAS_HOST:-NASPEDRO02.myqnapcloud.com}"
NAS_USER="${NAS_USER:?falta NAS_USER}"
NAS_PASS="${NAS_PASS:?falta NAS_PASS}"
DEST_IMAGEM="/Web/cristopher"
DEST_DADOS="/Container/cristopher-dados"

CURL="curl -sk --max-time 3600"

urlenc() { printf '%s' "$1" | sed 's|/|%2F|g; s| |%20|g'; }

# O painel da NAS já mudou de porta uma vez (443 -> 2030), por isso procura-se
# em vez de assumir. NAS_PORT no .env.nas passa à frente da procura.
echo "-> procurar o painel em $NAS_HOST"
BASE=""
SID=""
for porta in ${NAS_PORT:-443 2030 8080 80}; do
  esquema=https; [ "$porta" = 80 ] && esquema=http
  tentativa="$esquema://$NAS_HOST:$porta"
  sid=$($CURL --max-time 20 -X POST "$tentativa/cgi-bin/authLogin.cgi" \
          -d "user=$NAS_USER" -d "pwd=$(printf '%s' "$NAS_PASS" | base64)" 2>/dev/null \
        | sed -n 's/.*<authSid><!\[CDATA\[\([^]]*\)\]\].*/\1/p') || true
  if [ -n "$sid" ]; then BASE="$tentativa"; SID="$sid"; echo "   sessão aberta em $tentativa"; break; fi
done
[ -n "$SID" ] || {
  echo "login falhou em todas as portas."
  echo "A API do File Station tem de estar acessível de fora — ver DEPLOY-NAS.md."
  exit 1
}

API="$BASE/cgi-bin/filemanager/utilRequest.cgi"

mkdir_nas() { # $1 = caminho completo na NAS; cria cada nível que faltar
  local feito="" parte
  IFS=/ read -ra partes <<<"${1#/}"
  for parte in "${partes[@]}"; do
    $CURL -G "$API" --data-urlencode "func=createdir" --data-urlencode "sid=$SID" \
      --data-urlencode "dest_path=${feito:-/}" --data-urlencode "dest_folder=$parte" >/dev/null
    feito="$feito/$parte"
  done
}

enviar() { # $1 = ficheiro local, $2 = pasta na NAS
  local f="$1" kb
  kb=$(( $(wc -c <"$f") / 1024 ))
  echo "-> $(basename "$f") (${kb} KB) para $2"
  $CURL -X POST "$API?func=upload&type=standard&sid=$SID&dest_path=$(urlenc "$2")&overwrite=1&progress=x" \
    -F "file=@$f;filename=$(basename "$f")" | grep -q '"status": 1' \
    || { echo "   FALHOU: $f"; exit 1; }
}

existe_na_nas() { # $1 = pasta, $2 = nome. 0 existe, 1 não existe, 2 não deu para ver
  $CURL -G "$API" --data-urlencode "func=get_list" --data-urlencode "sid=$SID" \
    --data-urlencode "path=$1" --data-urlencode "limit=1000" --data-urlencode "start=0" \
    --data-urlencode "is_iso=0" --data-urlencode "list_mode=all" \
  | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(2)
if d.get("status") not in (None, 1) and "datas" not in d:
    sys.exit(1)          # a pasta ainda não existe
sys.exit(0 if any(x.get("filename") == sys.argv[1] for x in d.get("datas", [])) else 1)
' "$2"
}

if [ -n "$TAR" ]; then
  mkdir_nas "$DEST_IMAGEM"
  enviar "$TAR" "$DEST_IMAGEM"
fi

if $DADOS; then
  BD=backend/cristopher.db
  [ -f "$BD" ] || { echo "não existe: $BD"; exit 1; }

  rc=0; existe_na_nas "$DEST_DADOS" cristopher.db || rc=$?
  if [ "$rc" = 2 ]; then
    echo "não consegui ver o que está em $DEST_DADOS — parei, para não pisar nada"; exit 1
  fi
  if [ "$rc" = 0 ] && ! $FORCAR; then
    echo "já há uma cristopher.db na NAS. Se a app já lá corre, essa é a verdadeira."
    echo "Para a substituir mesmo: parar a aplicação na Container Station e usar --forcar."
    exit 1
  fi

  # Os ficheiros do WAL são da base que lá está. Deixá-los por baixo de uma base
  # nova é corrupção à espera de acontecer.
  for lixo in cristopher.db-wal cristopher.db-shm; do
    rc=0; existe_na_nas "$DEST_DADOS" "$lixo" || rc=$?
    if [ "$rc" = 0 ]; then
      echo "-> apagar $lixo (é da base antiga)"
      $CURL -G "$API" --data-urlencode "func=delete" --data-urlencode "sid=$SID" \
        --data-urlencode "path=$DEST_DADOS" --data-urlencode "file_name=$lixo" \
        --data-urlencode "file_total=1" --data-urlencode "force=1" >/dev/null
    fi
  done

  TMPD=$(mktemp -d)
  trap 'rm -rf "$TMPD"' EXIT
  # VACUUM INTO: fotografia consistente mesmo com o backend do Mac a escrever
  echo "-> fotografia da base"
  sqlite3 "$BD" "VACUUM INTO '$TMPD/cristopher.db'"

  mkdir_nas "$DEST_DADOS/garmin"
  enviar "$TMPD/cristopher.db" "$DEST_DADOS"

  for f in backend/enablebanking.pem backend/push_keys.json backend/push_key.pem; do
    [ -f "$f" ] && enviar "$f" "$DEST_DADOS"
  done

  TOKEN_GARMIN="${GARMIN_TOKENS_DIR:-$HOME/.garminconnect}/garmin_tokens.json"
  [ -f "$TOKEN_GARMIN" ] && enviar "$TOKEN_GARMIN" "$DEST_DADOS/garmin"

  # recibos: sobem com a mesma estrutura de pastas
  (cd backend && find uploads -type f ! -name '.DS_Store') | while read -r rel; do
    pasta="$DEST_DADOS/$(dirname "$rel")"
    mkdir_nas "$pasta"
    enviar "backend/$rel" "$pasta"
  done
fi

echo
echo "pronto. Falta importar na Container Station — ver DEPLOY-NAS.md"

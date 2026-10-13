#!/bin/bash
# Serve o Cristopher por HTTPS na tailnet.
#
# Porquê: no telemóvel, a app instalada (PWA) e os avisos só funcionam em
# contexto seguro. Por http://100.x.y.z o iPhone recusa instalar e ignora os
# avisos; com isto passa a haver um endereço https://<mac>.<tailnet>.ts.net.
#
# Pré-requisitos (uma vez, no admin do Tailscale):
#   • MagicDNS ligado
#   • HTTPS Certificates ligado
set -e

if ! command -v tailscale >/dev/null 2>&1; then
  echo "Tailscale não está instalado." >&2
  exit 1
fi

if ! tailscale status >/dev/null 2>&1; then
  echo "Tailscale está parado. Arranca-o primeiro (app do Tailscale ou 'tailscale up')." >&2
  exit 1
fi

DOMINIO=$(tailscale status --json | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['Self']['DNSName'].rstrip('.'))")
echo "Domínio: $DOMINIO"

# frontend na raiz, backend em /api — assim a app e os dados partilham origem
# (sem isto o browser bloqueia os pedidos por serem de outra origem).
tailscale serve --bg --https=443 --set-path=/ http://127.0.0.1:3001
tailscale serve --bg --https=443 --set-path=/api http://127.0.0.1:8001/api

echo
tailscale serve status
echo
echo "Pronto. No telemóvel abre https://$DOMINIO e adiciona ao ecrã principal."
echo "Depois, em Avisos → 'receber avisos aqui'."

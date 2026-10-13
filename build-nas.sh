#!/usr/bin/env bash
# Constrói a imagem do Cristopher para a NAS QNAP, verifica que nenhuma biblioteca
# que a app carrega fica mal alinhada (a NAS usa páginas de 32K) e exporta no
# formato clássico que a Container Station consegue importar.
#
#   IMG=cristopher:v2 ./build-nas.sh /tmp/cristopher-nas-v2.tar
set -euo pipefail

cd "$(dirname "$0")"
# etiqueta com versão: reutilizar ":latest" faz a Container Station ficar com a
# imagem antiga em cache e o contentor arranca com a versão errada
IMG=${IMG:-cristopher:v1}
SAIDA=${1:-/tmp/cristopher-nas.tar}
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

echo "-> build armv7 ($IMG)"
docker buildx build --platform linux/arm/v7 -f Dockerfile.nas -t "$IMG" --load .

echo "-> verificar alinhamento do que a app carrega (tem de ser >= 32K)"
docker run --rm --platform linux/arm/v7 -i --entrypoint python "$IMG" - \
  < scripts/verifica-alinhamento.py

echo "-> exportar e converter para o formato clássico (Container Station)"
# `docker save` e não um segundo build com --output: o exportador "docker" do
# buildx não existe em todos os motores (o OrbStack recusa-o), e a imagem já
# está carregada aqui do passo anterior.
docker save "$IMG" -o "$TMP/oci.tar"
python3 scripts/para-formato-classico.py "$TMP/oci.tar" "$SAIDA" "$TMP/conv"

echo "-> validar que o ficheiro carrega"
docker image rm -f "$IMG" >/dev/null 2>&1 || true
docker load -i "$SAIDA" | tail -1

echo
echo "pronto: $SAIDA"

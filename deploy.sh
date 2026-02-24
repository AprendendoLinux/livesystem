#!/bin/bash
# Script de Deploy Automático

# Cores para feedback visual
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}>>> INICIANDO AUTO-DEPLOY (Dev -> Main -> GHCR)${NC}"

# 1. Verifica se há arquivos não salvos (Segurança)
if [[ $(git status --porcelain) ]]; then
    echo -e "${RED}ERRO: Você tem alterações não salvas.${NC}"
    echo "Faça commit ou stash na branch dev antes de rodar o deploy."
    exit 1
fi

# 2. Garante que a branch Dev está sincronizada
echo -e "${GREEN}1. Sincronizando branch Dev...${NC}"
git checkout dev
git pull origin dev

# 3. Vai para Main, atualiza e faz o Merge AUTOMÁTICO
echo -e "${GREEN}2. Atualizando Main e fazendo Merge da Dev...${NC}"
git checkout main
git pull origin main

# --- MUDANÇA AQUI: Mensagem automática com data/hora ---
DATA_HORA=$(date "+%d/%m/%Y às %H:%Mh")
MENSAGEM="Merge branch 'dev' em $DATA_HORA"

if ! git merge dev -m "$MENSAGEM"; then
    echo -e "${RED}ERRO: Conflito no merge. Resolva manualmente.${NC}"
    exit 1
fi
# -------------------------------------------------------

# 4. CÁLCULO AUTOMÁTICO DA VERSÃO
echo -e "${GREEN}3. Calculando próxima versão...${NC}"

# Busca todas as tags do repositório remoto para não errar a conta
git fetch --tags

# Pega a última tag que segue o padrão v*.*.* (ex: v1.0.5)
LAST_TAG=$(git tag --list 'v*.*.*' --sort=-v:refname | head -n 1)

if [ -z "$LAST_TAG" ]; then
    # Se não existir nenhuma tag, começa na v1.0.0
    NEW_TAG="v1.0.0"
    echo -e "Nenhuma tag encontrada. Iniciando versão: ${YELLOW}$NEW_TAG${NC}"
else
    # Remove o 'v' inicial para fazer a conta (ex: 1.0.5)
    VERSION=${LAST_TAG#v}
    
    # Quebra em partes pelo ponto (Major.Minor.Patch)
    IFS='.' read -r -a parts <<< "$VERSION"
    MAJOR=${parts[0]}
    MINOR=${parts[1]}
    PATCH=${parts[2]}
    
    # Soma 1 no Patch (último número)
    NEW_PATCH=$((PATCH + 1))
    
    # Monta a nova tag
    NEW_TAG="v$MAJOR.$MINOR.$NEW_PATCH"
    echo -e "Versão Anterior: $LAST_TAG"
    echo -e "NOVA VERSÃO:     ${YELLOW}$NEW_TAG${NC}"
fi

# Pausa rápida para você conferir (opcional, pode remover o read se quiser 100% direto)
read -p "Pressione [Enter] para confirmar o lançamento da $NEW_TAG..."

# 5. Envia para o GitHub (Dispara o Actions)
echo -e "${GREEN}4. Enviando para o GitHub...${NC}"

# Cria a tag e faz o push de tudo
git tag "$NEW_TAG"
git push origin main
git push origin "$NEW_TAG"

# 6. Volta para a dev para continuar trabalhando
echo -e "${GREEN}5. Voltando para a Dev...${NC}"
git checkout dev

echo -e "${YELLOW}>>> SUCESSO! O GitHub Actions já está trabalhando.${NC}"
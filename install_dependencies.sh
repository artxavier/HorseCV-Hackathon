#!/bin/bash

echo "=== Verificando dependências do sistema ==="

# Verifica o Python 3
if ! command -v python3 &> /dev/null; then
    echo "ERRO: Python 3 não está instalado. Instale-o e tente novamente."
    exit 1
else
    echo "✅ Python 3 encontrado."
fi

# Verifica o NPM (para TypeScript/Node)
if ! command -v npm &> /dev/null; then
    echo "ERRO: npm não está instalado. Necessário para instalar as dependências da web e da api."
    exit 1
else
    if ! command -v tsc &> /dev/null; then
        echo "AVISO: TypeScript não instalado globalmente (as dependências locais cuidarão disso)."
    else
        echo "✅ TypeScript encontrado."
    fi
fi

echo ""
# Interação para nomear o ambiente virtual
read -p "Digite o nome para o ambiente virtual Python (ou pressione Enter para usar 'venv'): " VENV_NAME

# Se o usuário deixar vazio, usa 'venv' como padrão
if [ -z "$VENV_NAME" ]; then
    VENV_NAME="venv"
fi

echo ""
echo "Criando o ambiente virtual '$VENV_NAME'..."
python3 -m venv $VENV_NAME

echo "Ativando o ambiente virtual..."
source $VENV_NAME/bin/activate
pip install -U pip

echo ""
echo "=== Instalando dependências na pasta 'web' ==="
if [ -d "web" ]; then
    cd web
    
    if [ -f "package.json" ]; then
        echo "📦 Instalando dependências NPM na pasta 'web'..."
        npm install
    fi

    if [ -f "requirements.txt" ]; then
        echo "🐍 Instalando dependências Python na pasta 'web'..."
        pip install -r requirements.txt
    fi
    
    # Volta para a raiz
    cd ..
else
    echo "⚠️ Pasta 'web' não encontrada. Pulando..."
fi

echo ""
echo "=== Instalando dependências na pasta 'api' ==="
if [ -d "api" ]; then
    cd api
    
    if [ -f "package.json" ]; then
        echo "📦 Instalando dependências NPM na pasta 'api'..."
        npm install
    fi

    if [ -f "requirements.txt" ]; then
        echo "🐍 Instalando dependências Python na pasta 'api'..."
        pip install -r requirements.txt
    fi
    
    # Volta para a raiz
    cd ..
else
    echo "⚠️ Pasta 'api' não encontrada. Pulando..."
fi

echo ""
echo "✅ Configuração finalizada com sucesso!"
echo "👉 Para usar o ambiente virtual no seu terminal, não esqueça de rodar: source $VENV_NAME/bin/activate"
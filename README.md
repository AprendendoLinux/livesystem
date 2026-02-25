# 📡 LiveSystem - Servidor de Streaming de Webcam

**LiveSystem** é uma aplicação completa e conteinerizada para transmissão de vídeo em tempo real a partir de uma webcam local (host). Desenvolvida por **Henrique Fagundes**, a ferramenta contorna limitações comuns de rede em ambientes Docker utilizando a tecnologia de WebSockets aliada ao processamento de imagem do OpenCV.

![Python](https://img.shields.io/badge/Python-3.10-blue?style=flat-square&logo=python)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker)
![OpenCV](https://img.shields.io/badge/OpenCV-Headless-5C3EE8?style=flat-square&logo=opencv)
![MySQL](https://img.shields.io/badge/MySQL-Supported-4479A1?style=flat-square&logo=mysql)
![SQLite](https://img.shields.io/badge/SQLite-Supported-003B57?style=flat-square&logo=sqlite)

---

## ✨ Principais Funcionalidades

* **🎥 Streaming em Tempo Real (TCP):** Transmissão de vídeo fluida através de WebSockets, eliminando os problemas de NAT do Docker comuns ao WebRTC.
* **🧠 Gerenciamento Inteligente de Hardware:** A câmera (`/dev/video0`) é ativada apenas quando há espectadores. Se todos desconectarem, o hardware é liberado automaticamente.
* **👥 Gestão de Usuários Completa:** Painel em formato de *cards* com janelas modais nativas para criação, edição de senhas/privilégios e exclusão de contas.
* **🛡️ Autenticação Segura:** Sistema de login com sessões baseadas em Token (UUID) e senhas criptografadas via `bcrypt`.
* **🎨 Interface Futurista e Responsiva:** Design *dark/neon*, totalmente adaptado para visualização em computadores e dispositivos móveis, com botões para controle de Zoom, Tela Cheia e Ligar/Desligar câmera.
* **🗄️ Banco de Dados Híbrido:** Capacidade de rodar perfeitamente em **MySQL** (produção) ou **SQLite** (testes/ambientes leves).
* **⚙️ CI/CD Integrado:** Pipeline pronto no GitHub Actions para versionamento semântico automatizado e publicação no GitHub Container Registry (GHCR).

---

## 🏗️ Arquitetura e Tecnologias

O backend foi construído em **Python (aiohttp)** para máxima performance de I/O assíncrono. O vídeo é capturado fisicamente pelo **OpenCV** nativo do Linux, comprimido em JPEG e transmitido em dados binários (`blob`) pelo canal do WebSocket. O front-end intercepta esses dados e os renderiza no navegador, realizando gestão de memória dinâmica (`URL.revokeObjectURL`) para evitar vazamentos (*memory leaks*). O template HTML é renderizado no servidor via **Jinja2**.

---

## 🚀 Como Instalar e Rodar

### Pré-requisitos
* Um sistema host Linux com uma webcam conectada (geralmente mapeada em `/dev/video0`).
* **Docker** e **Docker Compose** instalados.

### Entendendo o `docker-compose.yml`

O projeto foi desenhado para ser flexível. O arquivo `docker-compose.yml` permite que você escolha qual motor de banco de dados deseja usar.

#### Mapeamento de Hardware e Volumes
O serviço principal (`webrtc-stream`) repassa a câmera física do servidor Linux para dentro do contêiner através da diretiva `devices`. Além disso, mapeamos os diretórios locais para garantir que seus bancos de dados não sejam perdidos caso os contêineres sejam reiniciados.

#### Escolhendo o Banco de Dados

1. **Para usar SQLite (Mais rápido e fácil):**
   Mantenha a variável `DB_TYPE=sqlite`. O banco será salvo automaticamente em `/srv/webcam/sqlite/stream.db`. Você não precisará subir o contêiner do MySQL.
   
```
   environment:
     - PYTHONUNBUFFERED=1
     - DB_TYPE=sqlite
     - DB_NAME=/app/data/stream.db
```

2. **Para usar MySQL (Recomendado para Produção):**
Comente a sessão do SQLite e descomente a área do MySQL no seu arquivo. O sistema conectará automaticamente ao serviço `db` (MySQL 8+) definido no fim do compose.

```
environment:
  - PYTHONUNBUFFERED=1
  - DB_TYPE=mysql
  - DB_HOST=db
  - DB_USER=stream_user
  - DB_PASS=stream_pass
  - DB_NAME=stream_db
```
*Nota: O compose também inclui um contêiner opcional do **Adminer** na porta 8081 para administração gráfica do banco de dados.*

### Passo a Passo de Execução

1. Clone o repositório e acesse a pasta do projeto.
2. Certifique-se de que a câmera está conectada ao Linux.
3. Suba o ambiente com o Docker Compose:

```bash
docker-compose up -d --build

```

4. Acesse pelo seu navegador na porta 8080: `http://IP_DO_SERVIDOR:8080`

---

## 🔐 Primeiro Acesso

Ao iniciar o sistema pela primeira vez, o banco de dados criará automaticamente um usuário administrador padrão.

* **Usuário:** `admin`
* **Senha:** `admin123`

> **Aviso de Segurança:** É altamente recomendado acessar a aba **"Usuários"** no menu superior, alterar a senha deste usuário ou criar um novo administrador com uma senha forte e excluir a conta padrão.

---

## 🔄 Deploy e Versionamento Automático

O projeto inclui um script `deploy.sh` e uma rotina no `.github/workflows/docker-publish.yml`.
Ao desenvolver na branch `dev` e rodar o script de deploy, o sistema automaticamente:

1. Sincroniza e faz o merge para a branch `main`.
2. Calcula a nova versão da tag (ex: `v1.0.1` -> `v1.0.2`).
3. Faz o push acionando o GitHub Actions.
4. O GitHub Actions empacota a imagem Docker, injeta a versão visual no rodapé (Jinja2) e publica no GHCR (`ghcr.io`).
5. (Opcional) Dispara Webhooks do Portainer para atualizar instâncias de produção automaticamente.

---

**Desenvolvido com ☕ e código aberto por [Henrique Fagundes](https://www.henrique.tec.br).**

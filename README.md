# OpenSCC — Plataforma Integrada de Gestão Acadêmica, Eventos, Avaliações Inteligentes (Mimir) e Inteligência Institucional (Odin)

O **OpenSCC** (*Sistema Aberto de Controle de Conferências e Gestão Acadêmica*) é uma plataforma modular desenvolvida em **Django** que integra gestão de eventos científicos, ensino baseado em problemas (PBL), elaboração e correção inteligente de avaliações com IA generativa e visão computacional (**Mimir**), além de gestão curricular, iniciação científica e inteligência preditiva de vestibular (**Odin**).

---

## Sumário

- [Visão Geral da Arquitetura](#visão-geral-da-arquitetura)
- [Módulos do Sistema](#módulos-do-sistema)
  - [1. Submission — Conferências, Eventos e Certificados](#1-submission--conferências-eventos-e-certificados)
  - [2. Mimir — Avaliações, PBL, PD&I e IA Pedagógica](#2-mimir--avaliações-pbl-pdi-e-ia-pedagógica)
  - [3. Odin — Gestão Acadêmica, Iniciação Científica e Predição de Vestibular](#3-odin--gestão-acadêmica-iniciação-científica-e-predição-de-vestibular)
  - [4. Commons — Serviços Compartilhados e Orquestração de LLM](#4-commons--serviços-compartilhados-e-orquestração-de-llm)
- [Principais Funcionalidades Recentes](#principais-funcionalidades-recents)
- [Tecnologias Utilizadas](#tecnologias-utilizadas)
- [Configuração e Instalação](#configuração-e-instalação)
- [Configuração Dinâmica de Modelos LLM (Django Admin)](#configuração-dinâmica-de-modelos-llm-django-admin)
- [Estrutura de Diretórios](#estrutura-de-diretórios)

---

## Visão Geral da Arquitetura

```
openscc/
├── commons/       # Orquestração de LLMs (Gemini), autenticação, perfis e serviços compartilhados
├── submission/    # Gestão de conferências, submissão de artigos, presença por QR Code e certificados
├── mimir/         # Banco de questões, Avaliações Unificadas, OMR/Visão Computacional, PBL, Fontes PDF e PD&I
├── odin/          # PPCs, Matrizes Curriculares, Iniciação Científica (CEPE) e Inteligência de Vestibular (ML)
└── openscc/       # Configurações globais do projeto Django, rotas principais e WSGI/ASGI
```

---

## Módulos do Sistema

### 1. `submission` — Conferências, Eventos e Certificados
Módulo voltado à organização de eventos acadêmicos e científicos:
- **Gestão de Conferências e Atividades**: Programação por data, controle de vagas e inscrições de participantes.
- **Submissão de Trabalhos (Papers)**: Fluxo de envio e acompanhamento de artigos científicos.
- **Credenciamento e Presença via QR Code**: Geração e leitura de QR Codes individuais por atividade e participante.
- **Emissão e Validação Pública de Certificados**: Geração de certificados em PDF com código UUID único e página pública de verificação de autenticidade.

---

### 2. `mimir` — Avaliações, PBL, PD&I e IA Pedagógica
Ambiente inteligente de apoio ao docente e ao estudante:

- **Banco de Questões Avançado**:
  - Criação manual e geração assistida por IA a partir de fontes bibliográficas.
  - **Construtor Interativo de Alternativas** para questões objetivas (presets `A–E`, `A–D`, `V/F`, colagem em lote, embaralhamento com preservação do gabarito e sincronização automática).
  - **Estúdio de Código Fonte com Syntax Highlight**: Suporte a múltiplas linguagens (`Python`, `JavaScript`, `TypeScript`, `Java`, `C`, `C++`, `C#`, `SQL`, `HTML/XML`, `CSS`, `PHP`, `Bash`, `JSON`, `Portugol`), com numeração de linhas e destaque de sintaxe tanto em tela quanto na impressão/PDF.
  - Suporte a múltiplas imagens vinculadas ao enunciado (`ImagemPergunta`) e revisão por especialistas (fluxo de *feedback* docente).

- **Avaliação Unificada de Módulo**:
  - Composição estruturada em **5 partes parametrizáveis**:
    1. *Parte I*: Questões Objetivas de Conhecimentos Gerais (padrão: 3 questões);
    2. *Parte II*: Questão Dissertativa de Conhecimento Geral (padrão: 1 questão);
    3. *Parte III*: Questões Objetivas por Matéria/Assunto do Módulo (padrão: 3 questões por matéria vinculada);
    4. *Parte IV*: Questão Dissertativa Técnica do Módulo (padrão: 1 questão);
    5. *Parte V*: Questões sobre a Sensação e Autoavaliação do Aluno (peso zero na nota).
  - Preenchimento automático a partir do banco de questões ou geração das questões faltantes via IA respeitando as cotas de cada seção.
  - **Impressão Tripla (HTML/WeasyPrint PDF)**:
    1. *Caderno de Prova Completo* (com blocos de código destacados e imagens embutidas);
    2. *Folha de Respostas OMR/Foto* (com marcadores fiduciais nos 4 cantos, bolhas `A–E` e quadros delimitados para transcrição dissertativa);
    3. *Gabarito Oficial e Matriz de Correção*.
  - **Correção Automática por Foto (Visão Computacional + IA Multimodal)**:
    - Leitura de fotos ou scans da Folha de Respostas ou do caderno de prova;
    - Identificação das alternativas marcadas nas questões objetivas, transcrição OCR das respostas dissertativas manuscritas e avaliação pedagógica com nota e justificativa por critério.

- **Estúdio Visual de Fatiamento de PDFs para Fontes (`pdf_fontes_studio.py`)**:
  - Visualizador interativo de páginas do PDF diretamente no navegador (`PDF.js`);
  - Marcação visual de início (`[ Início aqui`) e fim (`Fim aqui ]`) de blocos/capítulos na própria página;
  - Detecção automática de sumário/capítulos (bookmarks e heurística textual) para transformar livros inteiros em fontes específicas por capítulo.

- **Aprendizagem Baseada em Problemas (PBL)**:
  - Geração e versionamento de problemas em partes, vínculo com objetivos de aprendizagem e mídias;
  - Geração e edição de **Guia do Tutor**, sessões em pequenos grupos e liberação progressiva de partes.

- **Módulo de Projetos de PD&I**:
  - Submissão e edição colaborativa de projetos por edital, copiloto de escrita por campo com IA, gestão de referências (`BibTeX`), revisão por pares e análise preditiva de aderência.

---

### 3. `odin` — Gestão Acadêmica, Iniciação Científica e Predição de Vestibular
Módulo de governança acadêmica e inteligência estratégica:

- **Gestão Curricular**:
  - Cadastro de Eixos Tecnológicos, Eixos Formativos, Modalidades, Cursos, Disciplinas, Projetos Pedagógicos de Curso (**PPC**) e Matrizes Curriculares.
- **Iniciação Científica (IC & CEPE)**:
  - Fluxo completo para Aluno (submissão de projeto), Orientador (aceite), Comitê **CEPE** (designação e julgamento) e Parecerista *Ad-hoc* (avaliação cega).
- **Campanhas de Vestibular, Captação de Leads e Predição por Machine Learning**:
  - Gestão de campanhas de vestibular, delegação de ações de divulgação para docentes, controle de despesas, fotos e captação de leads (Landing Page pública + QR Code + API REST `/odin/api/v1/leads/`).
  - **Preditor ML & Simulador de Vestibular (`vestibular_ml_predictor`)**:
    - Curva S logística de inscrições, projeção por curso, velocidade diária, funil de conversão (Inscritos → Pagos/Isentos), análise de elasticidade de canais e recomendações táticas.
  - **Painel Executivo Compartilhável (Link Público Assinado)**:
    - Geração de links externos assinados criptograficamente (`django.core.signing`) com expiração configurável (7, 15, 30, 90 dias) ou revogação imediata;
    - Permite que gestores e diretores sem conta no sistema visualizem os KPIs e utilizem o **Simulador Interativo "E Se?"** (ajuste de orçamento e ações em escolas para simular o impacto projetado nas inscrições).

---

### 4. `commons` — Serviços Compartilhados e Orquestração de LLM
- Integração centralizada com a API do **Google Gemini** (`google-genai`) e geração de embeddings (`SentenceTransformer`).
- **Troca de Modelo LLM em Tempo Real**: Qualquer chamada de IA realizada no sistema consulta automaticamente o modelo marcado como ativo no painel administrativo, com *fallback* transparente para a configuração padrão (`settings.TOM_MODEL`).
- Auditoria de requisições de IA via `LLMLog`.

---

## Principais Funcionalidades Recentes

1. **Painel Executivo Externo do Vestibular**: Compartilhamento seguro via token criptografado sem necessidade de login, incluindo simulador interativo de cenários para tomada de decisão.
2. **Avaliação Unificada de Módulo (Criação, Impressão e Correção por Foto)**: Suporte completo às 5 seções da prova unificada, folha de respostas OMR e correção automatizada por imagem.
3. **Estúdio Visual de Fatiamento de PDF**: Seleção visual página a página para extrair capítulos de livros em PDF como fontes independentes no Mimir.
4. **Chaveamento Dinâmico de Modelo LLM no Django Admin**: Cadastro de múltiplos modelos (`gemini-2.5-flash`, `gemini-2.5-pro`, `gemini-2.0-flash`, etc.) no Admin com ativação imediata em tempo real.
5. **Construtor de Questões Objetivas + Syntax Highlight**: Criação visual de alternativas `A–E` e blocos de código fonte com destaque de sintaxe tanto na interface web quanto na impressão/PDF.

---

## Tecnologias Utilizadas

- **Backend**: Python 3.11+ • Django 4.2+
- **Banco de Dados**: MySQL / MariaDB (configuração padrão em `settings.py`)
- **IA Generativa & Visão**: Google GenAI SDK (`google-genai`), `SentenceTransformers`
- **Manipulação e Geração de PDF**: `pypdf`, `WeasyPrint`, `PDF.js` (renderização client-side no estúdio de fontes)
- **Análise de Dados & Machine Learning**: `NumPy`, `Pandas`, `Scikit-Learn` (modelos de regressão, curva logística e simulação de campanha no Odin)
- **Frontend**: Bootstrap 5, Bootstrap Icons, FontAwesome, Chart.js, Highlight.js + Colorizador Nativo Server/Client-Side

---

## Configuração e Instalação

### 1. Pré-requisitos
- Python 3.11 ou superior
- MySQL Server (ou MariaDB)
- Dependências de sistema para o `WeasyPrint` (ex.: `libpango`, `libcairo`, `libffi` no Linux)

### 2. Clonar o repositório e criar o ambiente virtual
```bash
git clone <url-do-repositorio>
cd openscc
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Instalar as dependências
```bash
pip install django mysqlclient django-widget-tweaks google-genai sentence-transformers pypdf weasyprint pillow numpy pandas scikit-learn qrcode
```

### 4. Configurar variáveis de ambiente e banco de dados
Configure sua chave de API do Gemini no ambiente (ou em `openscc/openscc/settings.py`):
```bash
export GEMINI_API_KEY="sua-chave-api-aqui"
```
Verifique as credenciais do banco MySQL em [`openscc/openscc/settings.py`](file:///mnt/17786ee3-9d2c-418f-9dea-5e545e6b46ee/Projects/openscc/openscc/openscc/settings.py#L82-L91) e execute as migrações:
```bash
cd openscc
python manage.py migrate
python manage.py createsuperuser
```

### 5. Iniciar o servidor de desenvolvimento
```bash
python manage.py runserver
```
Acesse:
- **Portal de Conferências (`submission`)**: `http://localhost:8000/`
- **Mimir (Avaliações, PBL e Fontes)**: `http://localhost:8000/mimir/`
- **Odin (Gestão Acadêmica, IC e Vestibular)**: `http://localhost:8000/odin/`
- **Painel de Administração Django**: `http://localhost:8000/admin/`

---

## Configuração Dinâmica de Modelos LLM (Django Admin)

Para cadastrar e alternar em tempo real o modelo de linguagem utilizado pelo Mimir:
1. Acesse o **Django Admin** (`/admin/`) → seção **Mimir** → **Configurações de Modelos LLM (Tempo Real)**.
2. Cadastre os modelos desejados informando o **Identificador Técnico** (ex.: `gemini-2.5-flash`, `gemini-2.5-pro`, `gemini-2.0-flash`).
3. Marque a caixa **Modelo Ativo** no modelo que deseja utilizar (ou utilize a ação em lote *"Ativar este modelo em tempo real"*).
4. O sistema desativará automaticamente os demais modelos e todas as novas requisições de geração de questões, problemas PBL, copiloto de PD&I e correção de provas passarão a usar o modelo selecionado imediatamente, sem necessidade de reiniciar o servidor.

---

## Estrutura de Diretórios

```text
openscc/
├── README.md
└── openscc/
    ├── manage.py
    ├── commons/
    │   ├── models.py                  # Perfis de usuário e estrutura comum
    │   └── services.py                # Cliente Gemini, resolução dinâmica do modelo ativo e embeddings
    ├── mimir/
    │   ├── admin.py                   # Gestão de modelos LLM (ConfiguracaoModeloLLM) e entidades Mimir
    │   ├── avaliacao_unificada.py     # Motor da Avaliação Unificada (cotas, geração IA e correção OMR/Foto)
    │   ├── pdf_fontes_studio.py       # Estúdio de inspeção e fatiamento de PDFs em capítulos/blocos
    │   ├── models.py                  # Perguntas, Provas, Problemas PBL, Fontes, Projetos PD&I e Syntax Highlight
    │   ├── views.py                   # Controladores do Mimir
    │   └── templates/mimir/           # Interfaces do Mimir, Construtor de Questões, Estúdio PDF e Impressão
    ├── odin/
    │   ├── models.py                  # Cursos, PPCs, Iniciação Científica, Campanhas e Leads de Vestibular
    │   ├── ml_vestibular.py           # Motor preditivo (Curva S, projeções e simulador de vestibular)
    │   ├── views.py                   # Controladores do Odin e Painel Executivo Público
    │   └── templates/odin/            # Dashboards analíticos e simulador interativo
    └── submission/
        ├── models.py                  # Conferências, Atividades, Submissões e Certificados
        ├── views.py                   # Inscrições, QR Code de presença e emissão/validação de certificados
        └── templates/                 # Interfaces públicas e administrativas de eventos
```

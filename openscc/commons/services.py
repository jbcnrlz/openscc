import os, base64, io, json, re, pdfplumber, time, ast
from typing import List, Optional

from django.conf import settings
from PIL import Image
from pydantic import BaseModel, Field

# LangChain Core & Models
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_ollama import ChatOllama
from langchain_huggingface import HuggingFaceEmbeddings

# LangChain Tools (Map-Reduce e RAG)
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_classic.chains.summarize import load_summarize_chain
from langchain_community.vectorstores import FAISS

from mimir.models import LLMLog, Edital, ConfiguracaoModeloLLM

# ==========================================
# CONFIGURAÇÃO DE MODELOS E EMBEDDINGS
# ==========================================
def get_active_model_label() -> str:
    """Retorna o identificador do modelo LLM atualmente ativo no Django Admin."""
    cfg = ConfiguracaoModeloLLM.get_modelo_ativo()
    if cfg:
        return f"{cfg.model_id} ({cfg.get_provedor_display()})"
    if settings.GEMINI_API_KEY is None or settings.GEMINI_API_KEY == "":
        return "gemma3:12b (Ollama)"
    return "gemini-3.1-flash-lite (Gemini)"


def get_llm(temperature_override: Optional[float] = None):
    """
    Retorna uma instância configurada do LLM em tempo real consultando o modelo
    marcado como ativo (`ativo=True`) em `ConfiguracaoModeloLLM` no Django Admin.
    """
    cfg = ConfiguracaoModeloLLM.get_modelo_ativo()
    if cfg:
        temp = temperature_override if temperature_override is not None else float(cfg.temperatura)
        if cfg.provedor == "ollama":
            ollama_kwargs = {
                "model": cfg.model_id.strip(),
                "temperature": temp,
            }
            if cfg.base_url and cfg.base_url.strip():
                ollama_kwargs["base_url"] = cfg.base_url.strip()
            return ChatOllama(**ollama_kwargs)

        # Provedor Gemini (Google Generative AI)
        api_key = (cfg.api_key_override or "").strip() or getattr(settings, "GEMINI_API_KEY", None)
        if api_key:
            return ChatGoogleGenerativeAI(
                model=cfg.model_id.strip(),
                google_api_key=api_key,
                temperature=temp,
                max_tokens=None,
                timeout=None,
                max_retries=int(cfg.max_retries or 2),
            )
        # Se o modelo ativo for Gemini mas não houver API key configurada, cai para Ollama local
        return ChatOllama(
            model="gemma3:12b",
            temperature=temp,
        )

    # Fallback padrão caso não haja configuração no banco
    temp_fallback = temperature_override if temperature_override is not None else 0.7
    if settings.GEMINI_API_KEY is None or settings.GEMINI_API_KEY == "":
        print("Usando modelo Ollama Gemma 3 localmente")
        return ChatOllama(
            model="gemma3:12b",
            temperature=temp_fallback
            #base_url="http://192.168.86.20:11434",
        )
    return ChatGoogleGenerativeAI(
        model="gemini-3.1-flash-lite",  # ou "gemini-1.5-flash"
        google_api_key=settings.GEMINI_API_KEY,
        temperature=temp_fallback,
        max_tokens=None,
        timeout=None,
        max_retries=2,
    )

def get_embeddings():
    """Fábrica de Embeddings agnóstica para RAG"""
    if settings.GEMINI_API_KEY is None or settings.GEMINI_API_KEY == "":
        print("Usando modelo de embeddings local (HuggingFace)")
        return HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
        
    # Com os pacotes atualizados, o modelo 004 será reconhecido sem erros
    return GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001", google_api_key=settings.GEMINI_API_KEY)


# ==========================================
# FUNÇÕES DE APOIO E PARSERS
# ==========================================
def extrair_texto_puro(content):
    """Extrai o texto puro da resposta do LangChain"""
    if isinstance(content, str):
        return content.strip()
    
    if isinstance(content, list):
        text_parts = []
        for block in content:
            if isinstance(block, dict) and 'text' in block:
                text_parts.append(block['text'])
            elif isinstance(block, str):
                text_parts.append(block)
        return "\n".join(text_parts).strip()
        
    return str(content).strip()

def invoke_chain(chain, inputs, endpoint, user=None, model_name=None):
    """Executa uma chain do LangChain e registra o log."""
    start_time = time.time()
    error = None
    response = None
    status = 'success'
    tokens_input = None
    tokens_output = None
    model_used = model_name or get_active_model_label()
    
    try:
        response = chain.invoke(inputs)
        if hasattr(response, 'usage_metadata'):
            tokens_input = response.usage_metadata.get('input_tokens')
            tokens_output = response.usage_metadata.get('output_tokens')
    except Exception as e:
        status = 'error'
        error = str(e)
        raise e  
    finally:
        duration = int((time.time() - start_time) * 1000)
        
        response_content = None
        if response:
            if hasattr(response, 'content'):
                response_content = response.content
            elif isinstance(response, str):
                response_content = response
            else:
                response_content = str(response)
        
        LLMLog.objects.create(
            user=user,
            prompt=str(inputs)[:5000],  # Truncado por segurança no banco de dados
            response=response_content,
            model_used=model_used,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            duration_ms=duration,
            status=status,
            error_message=error,
            endpoint=endpoint
        )
    
    return response


# ==========================================
# ESQUEMAS (PYDANTIC)
# ==========================================
class QuestaoSchema(BaseModel):
    tipo: str = Field(description="Tipo da questão (ex: múltipla escolha, discursiva)")
    enunciado: str = Field(description="Texto completo do enunciado da questão")
    alternativas: Optional[List[str]] = Field(default=None, description="Lista de alternativas para questões de múltipla escolha")
    resposta: str = Field(description="Gabarito ou padrão de resposta esperado")

class PerguntasSchema(BaseModel):
    perguntas: List[QuestaoSchema] = Field(description="Lista de questões geradas")

class CorrecaoSchema(BaseModel):
    nota: float = Field(description="Nota de 0 a 10", ge=0, le=10)
    justificativa: str = Field(description="Análise detalhada da resposta")

class GuiaTutorSchema(BaseModel):
    guia_tutor: str = Field(description="Texto completo do guia do tutor")

class AnaliseAprovacaoSchema(BaseModel):
    probabilidade_aprovacao: int = Field(description="Probabilidade estimada de aprovação de 0 a 100")
    pontos_fortes: List[str] = Field(description="Lista de 3 a 5 pontos fortes do projeto atual")
    pontos_fracos: List[str] = Field(description="Lista de 3 a 5 pontos fracos ou riscos baseados no histórico de reprovações")
    mitigacoes: List[str] = Field(description="Recomendações práticas e diretas de como reescrever ou alterar o projeto para mitigar os pontos fracos")


# ==========================================
# TEMPLATES DE PROMPT (PBL E CORREÇÃO)
# ==========================================
def criar_template_analise_projeto():
    """Cria template para análise preditiva de projetos baseada em histórico"""
    parser = JsonOutputParser(pydantic_object=AnaliseAprovacaoSchema)
    
    template = """TODO TEXTO QUE VOCÊ GERAR DEVE SER EM JSON, SIGA AS INSTRUÇÕES ABAIXO.

Você é um avaliador sênior de projetos acadêmicos e de inovação tecnológica (com expertise em agências de fomento e comitês institucionais).
Sua tarefa é analisar o RASCUNHO DO PROJETO ATUAL e prever sua probabilidade de aprovação com base no HISTÓRICO DE AVALIAÇÕES PASSADAS de projetos similares.

# HISTÓRICO DE PARECERES E FEEDBACKS RELEVANTES:
{contexto_historico}

# RASCUNHO DO PROJETO ATUAL A SER AVALIADO:
{projeto_atual}

# DIRETRIZES DE AVALIAÇÃO:
1. Compare as falhas criticadas no histórico com o que está escrito no projeto atual. Se o projeto atual comete os mesmos erros, diminua a probabilidade de aprovação.
2. Compare os elogios do histórico. Se o projeto atual possui as mesmas qualidades, aumente a probabilidade.
3. Seja extremamente crítico e realista.
4. As "mitigações" devem ser sugestões acionáveis (ex: "Detalhar o tamanho da amostra na seção de metodologia", "Incluir referências mais recentes sobre o impacto financeiro").

# INSTRUÇÕES DE FORMATO:
- FORMATE TODA A SAÍDA EM JSON
- NÃO UTILIZE NENHUMA TAG HTML OU MARKDOWN FORA DO BLOCO JSON
- RETORNE EXATAMENTE AS CHAVES: probabilidade_aprovacao (número inteiro), pontos_fortes (array de strings), pontos_fracos (array de strings), mitigacoes (array de strings)

{format_instructions}
"""
    return ChatPromptTemplate.from_template(template), parser

guia_tutor_template = ChatPromptTemplate.from_messages([
    ("system", "Você é um especialista em criação de materiais educacionais."),
    ("human", """Com base no problema abaixo, gere um GUIA DO TUTOR detalhado seguindo EXATAMENTE a estrutura fornecida:
# TÍTULO DO PROBLEMA: {titulo}
TEMA: {tema}
ASSUNTO: {assunto}
OBJETIVOS DE APRENDIZAGEM: {objetivos}

# TEXTO COMPLETO DO PROBLEMA:
{texto_problema}

# FONTES DE REFERÊNCIA:
{fontes_info}

--- ESTRUTURA DO GUIA DO TUTOR ---
{instrucoesGuia}
""")
])

regerar_parte_template = ChatPromptTemplate.from_messages([
    ("system", "Você é um Professor Doutor em {tema} especialista na metodologia de Aprendizado Baseado em Problemas (PBL). Sua tarefa é criar um Problema inédito para estudantes."),
    ("human", """TEMA: {tema}
ASSUNTO: {assunto}
OBJETIVOS: {objetivos}

FONTES DE REFERÊNCIA:
{fontes}

CONTEXTO ANTERIOR (Partes 1 a {parte_ordem_anterior}):
{contexto_anterior}

PARTE ORIGINAL {parte_ordem} (para referência):
{parte_original}

INSTRUÇÕES DE LAYOUT:
{instrucoes_layout}

INSTRUÇÕES ESPECÍFICAS DO USUÁRIO:
{instrucoes}

Sua tarefa é gerar uma NOVA VERSÃO para a PARTE {parte_ordem} que:
1. Siga rigorosamente as instruções do usuário acima
2. Mantenha coerência total com o contexto anterior
3. Preserve os objetivos de aprendizagem originais
4. Integre as fontes de referência quando relevante
5. Mantenha o mesmo nível de detalhe e complexidade
6. Seja uma melhoria clara em relação à versão original
7. Siga as instruções de layout fornecidas

Forneça APENAS o texto da nova parte {parte_ordem}, sem marcações, números ou comentários.
""")
])

criar_parte_template = ChatPromptTemplate.from_messages([
    ("system", "Você é um Professor Doutor em {tema} especialista na metodologia de Aprendizado Baseado em Problemas (PBL). Sua tarefa é criar um Problema inédito para estudantes."),
    ("human", """TEMA: {tema}
ASSUNTO: {assunto}
OBJETIVOS: {objetivos}

FONTES DE REFERÊNCIA:
{fontes}

CONTEXTO ANTERIOR:
{contexto_anterior}

INSTRUÇÕES DE LAYOUT (siga rigorosamente):
{instrucoes_layout}

Gere a PARTE {parte_atual} de {total_partes} deste problema.

IMPORTANTE, SIGA ESSAS INSTRUÇÕES SEM FALHA - Esta parte deve:
- Mantenha coerência total com o contexto anterior
- Preserve os objetivos de aprendizagem originais
- Integre as fontes de referência quando relevante
- Mantenha o mesmo nível de detalhe e complexidade
- Siga as instruções de layout fornecidas na estruturação do caso

OBSERVAÇÕES FINAIS:
- Mantenha o fluxo narrativo natural, como se fosse uma história real.
- Não adicione * ou qualquer outro tipo de caracter de marcação.
- Sempre que forem os personagens da história falando, coloque o conteúdo entre aspas
- Forneça apenas o texto da parte {parte_atual} em texto puro.
""")
])

def criar_template_questoes():
    parser = JsonOutputParser(pydantic_object=PerguntasSchema)
    template = """TODO TEXTO QUE VOCÊ GERAR DEVE SER EM JSON VÁLIDO. SIGA RIGOROSAMENTE AS INSTRUÇÕES ABAIXO.

BASEADO NO SEGUINTE EXTRATO DE DOCUMENTO / CONTEÚDO DE REFERÊNCIA:
{conteudo_pdf}

GERE EXATAMENTE {total_perguntas} QUESTÕES DE PROVA DISTRIBUÍDAS NOS SEGUINTES TIPOS:
{tipo_perguntas}

DIRETRIZES E ESPECIFICAÇÕES DE CADA TIPO DE QUESTÃO:
{info_extras}

# REGRAS OBRIGATÓRIAS DE ESTRUTURA E FORMATO JSON:
1. Formate TODA a saída em um único objeto JSON com a chave `"perguntas"`, cujo valor é um array de objetos contendo EXATAMENTE as chaves:
   - `"tipo"`: Nome exato do tipo de questão solicitado.
   - `"enunciado"`: Texto do comando/enunciado da questão (para questões objetivas, NÃO coloque as alternativas A, B, C, D, E dentro de `"enunciado"`, coloque-as exclusivamente no array `"alternativas"`).
   - `"alternativas"`: Array JSON de strings `["A) ...", "B) ...", "C) ...", "D) ...", "E) ..."]`.
     * ATENÇÃO: Para QUALQUER questão de múltipla escolha, objetiva, asserção-razão, análise de afirmativas ou verdadeiro/falso, a chave `"alternativas"` (no plural!) NUNCA pode ser vazia ou nula — ela DEVE conter todas as alternativas como elementos separados do array!
     * Apenas para questões puramente dissertativas/abertas `"alternativas"` deve ser `[]`.
   - `"resposta"`: Gabarito oficial. Para questões objetivas, indique claramente a letra correta seguida do texto da alternativa e uma breve justificativa (ex: `"B) Texto da alternativa B — Justificativa..."`). Para questões dissertativas, forneça o padrão de resposta esperado detalhado.
2. NÃO utilize tags HTML fora de blocos de código.
3. Gere EXATAMENTE as {total_perguntas} questões solicitadas.
{format_instructions}

IMPORTANTE - DE FORMA ALGUMA ADICIONE TEXTO FORA DO JSON.
"""
    return ChatPromptTemplate.from_template(template), parser

correcao_template = ChatPromptTemplate.from_messages([
    ("system", "Você é um professor doutor no tema da pergunta."),
    ("human", """FAÇA O PAPEL DE UM PROFESSOR DOUTOR NO TEMA DA PERGUNTA, DADA A SEGUINTE PERGUNTA:
{enunciado}

UTILIZE O SEGUINTE PADRÃO DE RESPOSTA / GABARITO PARA A CORREÇÃO:             
{gabarito}

PARA A CORREÇÃO DA RESPOSTA DO ALUNO ABAIXO:
{resposta_aluno}

#INSTRUÇÕES FINAIS        
- AVALIE A RESPOSTA DO ALUNO COM BASE NO GABARITO FORNECIDO. 
- FORNEÇA UMA NOTA DE 0 A 10, CONSIDERANDO A COMPLETUDE E CORREÇÃO DA RESPOSTA.
- Justificativa deve analisar a qualidade técnica da resposta
- Identifique acertos, erros e omissões
- Retorne APENAS um JSON no formato:
{{
  "nota": 0-10,
  "justificativa": "análise detalhada"
}}
- TRATE O ALUNO NA SEGUNDA PESSOA DO SINGULAR (VOCÊ)
""")
])


# ==========================================
# LÓGICA DE NEGÓCIO PRINCIPAL
# ==========================================
def processar_edital_business_logic(edital_id, user=None):
    """
    Nova Arquitetura Agnóstica (Map-Reduce).
    Processa editais gigantes fragmentando-os em blocos para evitar estouro de contexto
    independentemente do modelo configurado.
    """
    try:
        llm = get_llm()
        edital = Edital.objects.get(id=edital_id)
        
        # 1. Extração do texto
        texto_completo = "\n".join(extrair_texto_pdf(edital.arquivo_edital.path))
        
        # 2. Fragmentação Segura (4000 caracteres garante encaixe em modelos locais e APIs)
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=4000, chunk_overlap=200)
        docs = text_splitter.create_documents([texto_completo])
        
        # 3. Definição da Cadeia Map-Reduce para RESUMO
        map_resumo_prompt = PromptTemplate(
            template="Extraia as informações mais importantes sobre prazos, valores e objeto do seguinte trecho de edital:\nTRECHO:\n{text}\nRESUMO:", 
            input_variables=["text"]
        )
        reduce_resumo_prompt = PromptTemplate(
            template="Com base nos seguintes resumos parciais, crie um Resumo Executivo final coeso, destacando: Objeto do edital, Valores máximos, Prazos e Itens financiáveis.\nRESUMOS PARCIAIS:\n{text}\nRESUMO EXECUTIVO FINAL:", 
            input_variables=["text"]
        )
        chain_resumo = load_summarize_chain(llm, chain_type="map_reduce", map_prompt=map_resumo_prompt, combine_prompt=reduce_resumo_prompt)
        
        # 4. Definição da Cadeia Map-Reduce para INSIGHTS
        map_insights_prompt = PromptTemplate(
            template="Levante os critérios de elegibilidade, restrições e dicas de aprovação presentes no trecho:\nTRECHO:\n{text}\nINSIGHTS:", 
            input_variables=["text"]
        )
        reduce_insights_prompt = PromptTemplate(
            template="Com base nos levantamentos parciais, crie uma lista final e estratégica contendo: critérios de elegibilidade críticos, restrições de submissão e dicas táticas de aprovação.\nLEVANTAMENTOS PARCIAIS:\n{text}\nLISTA DE INSIGHTS:", 
            input_variables=["text"]
        )
        chain_insights = load_summarize_chain(llm, chain_type="map_reduce", map_prompt=map_insights_prompt, combine_prompt=reduce_insights_prompt)

        # ==========================================
        # EXECUÇÃO 1: RESUMO DO EDITAL
        # ==========================================
        start_time = time.time()
        res_resumo = chain_resumo.invoke({"input_documents": docs})
        duracao_resumo = int((time.time() - start_time) * 1000)
        texto_resumo_gerado = res_resumo.get("output_text", "")
        
        LLMLog.objects.create(
            user=user,
            prompt="Processamento Map-Reduce: Resumo do Edital",
            response=texto_resumo_gerado,
            model_used=getattr(llm, 'model', 'unknown'),
            duration_ms=duracao_resumo,
            status='success',
            endpoint='processar_edital_business_logic - resumo'
        )

        # ==========================================
        # EXECUÇÃO 2: INSIGHTS DO EDITAL
        # ==========================================
        start_time = time.time()
        res_insights = chain_insights.invoke({"input_documents": docs})
        duracao_insights = int((time.time() - start_time) * 1000)
        texto_insights_gerado = res_insights.get("output_text", "")
        
        LLMLog.objects.create(
            user=user,
            prompt="Processamento Map-Reduce: Insights do Edital",
            response=texto_insights_gerado,
            model_used=getattr(llm, 'model', 'unknown'),
            duration_ms=duracao_insights,
            status='success',
            endpoint='processar_edital_business_logic - insights'
        )

        # Atualização no BD
        edital.resumo_llm = texto_resumo_gerado
        edital.insights_llm = texto_insights_gerado
        edital.save()
        return True
        
    except Exception as e:
        print(f"Falha global ao processar o edital {edital_id}: {str(e)}")
        LLMLog.objects.create(
            user=user, prompt=f"Falha ao processar edital ID {edital_id}",
            status='error', error_message=str(e), endpoint='processar_edital_business_logic'
        )
        return False

def getQuestionsFromSource(file_path, qtPerguntas, infoExtras, user=None, assunto_nome=""):
    """
    Gera questões de prova a partir de fontes PDF (com RAG FAISS e fallback automático
    para texto direto caso o serviço de embeddings falhe) ou diretamente a partir do
    Assunto e Diretrizes do professor caso nenhuma fonte PDF tenha sido selecionada.
    """
    totalPerguntas = sum(qtPerguntas.values())
    textoPerguntas = "\n".join([f'- {v} questão(ões) do tipo "{k}"' for k, v in qtPerguntas.items()])

    try:
        # 1. Extrair e juntar texto bruto das fontes PDF selecionadas (se houver)
        completoTudo = ""
        nomes_fontes = []
        for fp in (file_path or []):
            caminho = fp[0] if isinstance(fp, (list, tuple)) else fp
            nome_f = fp[1] if isinstance(fp, (list, tuple)) and len(fp) > 1 else str(caminho)
            if caminho and os.path.exists(str(caminho)):
                conteudo_extraido = extrair_texto_pdf(caminho)
                texto_arq = "\n".join(conteudo_extraido).strip()
                if texto_arq:
                    nomes_fontes.append(nome_f)
                    completoTudo += f"=== FONTE: {nome_f} ===\n{texto_arq}\n\n"

        # 2. Obter o trecho de conteúdo mais relevante (RAG FAISS com fallback direto resiliente)
        conteudo_referencia = ""
        if completoTudo.strip():
            # Se o texto total cabe confortavelmente na janela de contexto (< 28.000 chars),
            # passa direto sem risco de perder partes importantes ou falhar no embedding
            if len(completoTudo) <= 28000:
                conteudo_referencia = completoTudo
            else:
                try:
                    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1800, chunk_overlap=200)
                    docs = text_splitter.create_documents([completoTudo])
                    embeddings = get_embeddings()
                    vectorstore = FAISS.from_documents(docs, embeddings)
                    retriever = vectorstore.as_retriever(search_kwargs={"k": 8})
                    query_busca = f"Assunto: {assunto_nome}. {infoExtras or ''} {', '.join(qtPerguntas.keys())}".strip()
                    docs_retrieved = retriever.invoke(query_busca)
                    conteudo_referencia = "\n\n".join([d.page_content for d in docs_retrieved])
                except Exception as emb_err:
                    print(f"Aviso: Fallback de embeddings acionado ({emb_err}). Usando extrato direto do PDF.")
                    conteudo_referencia = completoTudo[:28000]
        else:
            conteudo_referencia = (
                f"Nenhuma fonte PDF anexada. Elabore as questões com rigor acadêmico sobre a disciplina/assunto: "
                f"'{assunto_nome or 'Tema solicitado nas diretrizes'}', seguindo fielmente as diretrizes abaixo."
            )

        # 3. Execução do LLM com parser resiliente (evita falha se o LLM envolver JSON em ```json)
        prompt_template, parser = criar_template_questoes()
        llm = get_llm()
        chain = prompt_template | llm

        inputs = {
            "conteudo_pdf": conteudo_referencia,
            "total_perguntas": totalPerguntas,
            "tipo_perguntas": (
                f"Assunto/Disciplina: {assunto_nome}\n{textoPerguntas}"
                if assunto_nome
                else textoPerguntas
            ),
            "info_extras": infoExtras,
            "format_instructions": parser.get_format_instructions(),
        }

        raw_response = invoke_chain(chain, inputs, endpoint="getQuestionsFromSource", user=user)
        texto_resposta = extrair_texto_puro(raw_response.content if hasattr(raw_response, "content") else raw_response)
        texto_limpo = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto_resposta.strip())
        parsed_data = extrair_json_da_resposta(texto_limpo)

        # Caso o LLM tenha retornado uma lista direta de questões em vez de {"perguntas": [...]}
        if isinstance(parsed_data, list):
            parsed_data = {"perguntas": parsed_data}

        return json.dumps(parsed_data, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps({
            "perguntas": [],
            "erro": f"Erro ao gerar questões com a IA: {str(e)}"
        }, ensure_ascii=False)


# ==========================================
# OUTRAS FUNÇÕES DE ROTEAMENTO (Mantidas inalteradas)
# ==========================================
def criarPromptGuiaTutor(titulo, tema, assunto, objetivos, texto_problema, fontes_info, instrucoesGuia):
    chain = guia_tutor_template | get_llm()
    response = chain.invoke({
        "titulo": titulo, "tema": tema, "assunto": assunto,
        "objetivos": ", ".join(objetivos), "texto_problema": texto_problema,
        "fontes_info": fontes_info, "instrucoesGuia": instrucoesGuia
    })
    conteudo = response.content
    try:
        if isinstance(conteudo, list) and len(conteudo) > 0:
            if isinstance(conteudo[0], dict) and 'text' in conteudo[0]:
                return conteudo[0]['text']
        elif isinstance(conteudo, str) and conteudo.strip().startswith('['):
            try:
                dados = json.loads(conteudo)
            except json.JSONDecodeError:
                dados = ast.literal_eval(conteudo)
            if isinstance(dados, list) and len(dados) > 0 and isinstance(dados[0], dict) and 'text' in dados[0]:
                return dados[0]['text']
    except Exception as e:
        import logging
        logging.error(f"Erro ao limpar retorno do LLM no Guia do Tutor: {e}")
    return conteudo if isinstance(conteudo, str) else str(conteudo)

def regerarParte(tema, assunto, objetivos, parte_ordem, contexto_anterior, fontes, instrucoes, parte_original, instrucoes_layout="", user=None):
    chain = regerar_parte_template | get_llm()
    inputs = {
        "tema": tema, "assunto": assunto, "objetivos": ", ".join(objetivos),
        "parte_ordem": parte_ordem, "parte_ordem_anterior": parte_ordem - 1,
        "contexto_anterior": contexto_anterior, "fontes": fontes,
        "instrucoes": instrucoes, "parte_original": parte_original,
        "instrucoes_layout": instrucoes_layout
    }
    response = invoke_chain(chain, inputs, endpoint='regerarParte', user=user)
    return extrair_texto_puro(response.content) if hasattr(response, 'content') else str(response)

def criarPromptParaParte(tema, assunto, objetivos, parte_atual, total_partes, contexto_anterior, fontes, instrucoes_layout="", user=None):
    chain = criar_parte_template | get_llm()
    inputs = {
        "tema": tema, "assunto": assunto, "objetivos": ", ".join(objetivos),
        "parte_atual": parte_atual, "total_partes": total_partes if total_partes else "N",
        "contexto_anterior": contexto_anterior, "fontes": fontes,
        "instrucoes_layout": instrucoes_layout
    }
    response = invoke_chain(chain, inputs, endpoint='criarPromptParaParte', user=user)
    return extrair_texto_puro(response.content) if hasattr(response, 'content') else str(response)

def chamarApiLLM(prompt, user=None, endpoint='chamarApiLLM'):
    llm = get_llm()
    model_name = getattr(llm, 'model', 'unknown')
    start_time = time.time()
    error = None
    response_content = None
    status = 'success'
    try:
        response = llm.invoke(prompt)
        response_content = extrair_texto_puro(response.content) if hasattr(response, 'content') else extrair_texto_puro(response)
    except Exception as e:
        status = 'error'
        error = str(e)
        raise e
    finally:
        duration = int((time.time() - start_time) * 1000)
        LLMLog.objects.create(
            user=user, prompt=prompt[:5000], response=response_content,
            model_used=model_name, duration_ms=duration, status=status,
            error_message=error, endpoint=endpoint
        )
    return response_content

def fazerCorrecaoComModelo(enunciado, gabarito, resposta_aluno, user=None):
    try:
        parser = JsonOutputParser()
        chain = correcao_template | get_llm() | parser
        inputs = { "enunciado": enunciado, "gabarito": gabarito, "resposta_aluno": resposta_aluno }
        response = invoke_chain(chain, inputs, endpoint='fazerCorrecaoComModelo', user=user)
        return json.dumps(response, ensure_ascii=False)
    except Exception as e:
        return json.dumps({ "nota": 0, "justificativa": f"Erro na correção: {str(e)}" })

def corrigirRespostaMultimodal(enunciado, gabarito, resposta_aluno, imagens_pergunta=None, user=None):
    start_time = time.time()
    error = None
    response_content = None
    status = 'success'
    cfg_ativo = ConfiguracaoModeloLLM.get_modelo_ativo()
    model_name = cfg_ativo.model_id.strip() if cfg_ativo else "gemini-2.5-flash"
    tokens_input = None
    tokens_output = None
    output = None
    try:
        llm = get_llm(temperature_override=0.3)
        conteudos = []
        prompt_texto = f"ENUNCIADO DA PERGUNTA:\n{enunciado}\n\nGABARITO/PADRÃO DE RESPOSTA:\n{gabarito}\n\nRESPOSTA DO ALUNO:\n"
        conteudos.append(HumanMessage(content=prompt_texto))
        
        if imagens_pergunta:
            for imagem_info in imagens_pergunta:
                try:
                    imagem = Image.open(imagem_info['caminho_absoluto'])
                    buffered = io.BytesIO()
                    imagem.save(buffered, format="PNG")
                    img_str = base64.b64encode(buffered.getvalue()).decode()
                    conteudos.append(HumanMessage(content=[
                        {"type": "text", "text": f"IMAGEM DO ENUNCIADO: {imagem_info['nome']}"},
                        {"type": "image_url", "image_url": f"data:image/png;base64,{img_str}"}
                    ]))
                except Exception as e:
                    print(f"Erro ao carregar imagem do enunciado: {e}")
        
        try:
            if isinstance(resposta_aluno, str):
                try:
                    imagem_resposta = Image.open(resposta_aluno)
                    buffered = io.BytesIO()
                    imagem_resposta.save(buffered, format="PNG")
                    img_str = base64.b64encode(buffered.getvalue()).decode()
                    conteudos.append(HumanMessage(content=[{"type": "text", "text": "RESPOSTA DO ALUNO (IMAGEM):"},{"type": "image_url", "image_url": f"data:image/png;base64,{img_str}"}]))
                except:
                    conteudos.append(HumanMessage(content=f"RESPOSTA DO ALUNO (TEXTO):\n{resposta_aluno}"))
            else:
                buffered = io.BytesIO()
                resposta_aluno.save(buffered, format="PNG")
                img_str = base64.b64encode(buffered.getvalue()).decode()
                conteudos.append(HumanMessage(content=[{"type": "text", "text": "RESPOSTA DO ALUNO (IMAGEM):"},{"type": "image_url", "image_url": f"data:image/png;base64,{img_str}"}]))
        except Exception as e:
            conteudos.append(HumanMessage(content=f"RESPOSTA DO ALUNO (não processada): {str(resposta_aluno)}"))
        
        conteudos.append(HumanMessage(content="""
        #INSTRUÇÕES FINAIS        
        - AVALIE A RESPOSTA DO ALUNO COM BASE NO GABARITO FORNECIDO. 
        - SEJA CRITERIONOSO E JUSTO.
        - FORNEÇA UMA NOTA DE 0 A 10, CONSIDERANDO A COMPLETUDE E CORREÇÃO DA RESPOSTA.
        - Retorne APENAS um JSON no formato: {"nota": 0-10, "justificativa": "análise detalhada"}
        - TRATE O ALUNO NA SEGUNDA PESSOA DO SINGULAR (VOCÊ)
        """))
        
        response = llm.invoke(conteudos)
        response_content = response.content
        if hasattr(response, 'usage_metadata'):
            tokens_input = response.usage_metadata.get('input_tokens')
            tokens_output = response.usage_metadata.get('output_tokens')
        
        json_match = re.search(r'\{.*\}', response_content, re.DOTALL)
        if json_match:
            output = json_match.group()
            try:
                json.loads(output)
            except json.JSONDecodeError:
                output = json.dumps({"nota": 0, "justificativa": f"A resposta da IA não pôde ser interpretada. Conteúdo: {response_content[:200]}..."})
        else:
            output = json.dumps({"nota": 0, "justificativa": f"Resposta não pôde ser processada. Conteúdo: {response_content[:200]}..."})
        return output
    except Exception as e:
        status = 'error'
        error = str(e)
        return json.dumps({"nota": 0, "justificativa": f"Erro na correção multimodal: {str(e)}"})
    finally:
        duration = int((time.time() - start_time) * 1000)
        try:
            from mimir.models import LLMLog
            LLMLog.objects.create(
                user=user, prompt=f"Multimodal - enunciado: {enunciado[:200]}...", response=response_content,
                model_used=model_name, tokens_input=tokens_input, tokens_output=tokens_output,
                duration_ms=duration, status=status, error_message=error, endpoint='corrigirRespostaMultimodal'
            )
        except Exception as log_error:
            print(f"Erro ao salvar log: {log_error}")

def extrair_texto_pdf(caminho_arquivo):
    try:
        if isinstance(caminho_arquivo, (list, tuple)) and len(caminho_arquivo) > 0:
            caminho_arquivo = caminho_arquivo[0]

        caminho_str = str(caminho_arquivo)
        if caminho_str.lower().endswith(('.txt', '.md')):
            with open(caminho_str, 'r', encoding='utf-8', errors='replace') as f:
                conteudo = f.read().strip()
            return [conteudo] if conteudo else ["Nenhum texto extraído do arquivo"]

        texto = []
        with pdfplumber.open(caminho_str) as pdf:
            for i, pagina in enumerate(pdf.pages, 1):
                try:
                    texto_pagina = pagina.extract_text()
                    if texto_pagina and texto_pagina.strip():
                        texto.append(f"--- PÁGINA {i} ---")
                        texto.append(texto_pagina.strip())
                        texto.append("") 
                except Exception as e:
                    texto.append(f"Erro na página {i}: {str(e)}")
        return texto if texto else ["Nenhum texto extraído do PDF"]
    except ImportError:
        return ["Biblioteca pdfplumber não instalada. Execute: pip install pdfplumber"]
    except Exception as e:
        return [f"Erro na extração do PDF: {str(e)}"]

def _limpar_prefixo_alternativa(texto: str) -> str:
    return re.sub(r'^\s*(?:[A-Ha-h][\)\.\-:]|\([A-Ha-h]\))\s*', '', (texto or '').strip()).strip()


def _extrair_alternativas_de_texto_multiline(texto: str) -> tuple[str, list[str]]:
    """
    Se o LLM colocou as alternativas A) ... B) ... dentro do enunciado ou como uma única
    string com quebras de linha, separa o enunciado limpo e a lista de alternativas.
    """
    if not texto:
        return "", []
    linhas = str(texto).splitlines()
    linhas_enunciado = []
    alts = []
    inside_fence = False

    for linha in linhas:
        m = None if inside_fence else re.match(r'^\s*(?:\(([A-Ha-h])\)|([A-Ha-h])[\)\.\-:])\s*(.+)$', linha)
        if m:
            corpo = (m.group(3) or '').strip()
            alts.append(corpo)
        elif not alts:
            linhas_enunciado.append(linha)
        elif linha.strip() or inside_fence:
            alts[-1] = (alts[-1] + "\n" + linha).strip()
        fences = len(re.findall(r'```', linha))
        if fences % 2 == 1:
            inside_fence = not inside_fence

    if len(alts) >= 2:
        letras = "ABCDEFGH"
        alts_formatadas = [f"{letras[idx]}) {_limpar_prefixo_alternativa(a)}" for idx, a in enumerate(alts[:8]) if _limpar_prefixo_alternativa(a)]
        return "\n".join(linhas_enunciado).strip(), alts_formatadas
    return str(texto).strip(), []


def normalizar_alternativas_questao(raw_alts, enunciado_raw: str = "") -> tuple[str, list[str], list[str]]:
    """
    Normaliza alternativas vindas da IA em qualquer formato:
      - Lista de strings: ["A) ...", "B) ..."] ou ["...", "..."]
      - Dicionário: {"A": "...", "B": "..."}
      - String única multiline ou inline: "A) ...\nB) ..."
      - Embutidas ao final do próprio enunciado
    Retorna: (enunciado_limpo, alternativas_com_prefixo, alternativas_sem_prefixo)
    """
    letras = "ABCDEFGH"
    lista_bruta = []

    if isinstance(raw_alts, dict):
        for k in sorted(raw_alts.keys()):
            val = str(raw_alts[k] or '').strip()
            if val:
                lista_bruta.append(val)
    elif isinstance(raw_alts, str) and raw_alts.strip():
        txt = raw_alts.strip()
        # Tenta separar por padrão A) B) C) na mesma linha ou em várias linhas
        partes = re.split(r'(?:^|\n|\s{2,})(?=\(?[A-Ha-h][\)\.\-:]\s+)', txt)
        if len(partes) >= 2:
            lista_bruta = [p.strip() for p in partes if p.strip()]
        else:
            lista_bruta = [l.strip() for l in txt.splitlines() if l.strip()]
    elif isinstance(raw_alts, (list, tuple)):
        for item in raw_alts:
            if isinstance(item, dict):
                txt_item = str(item.get("texto") or item.get("alternativa") or item.get("opcao") or "").strip()
                if txt_item:
                    lista_bruta.append(txt_item)
            elif item is not None and str(item).strip():
                txt_item = str(item).strip()
                # Se a IA colocou todas as alternativas dentro de um único elemento da lista
                if len(raw_alts) == 1 and "\n" in txt_item:
                    _, extraidas = _extrair_alternativas_de_texto_multiline(txt_item)
                    if len(extraidas) >= 2:
                        lista_bruta.extend(extraidas)
                        continue
                lista_bruta.append(txt_item)

    enunciado_limpo, alts_do_enunciado = _extrair_alternativas_de_texto_multiline(enunciado_raw)
    if not lista_bruta and len(alts_do_enunciado) >= 2:
        lista_bruta = alts_do_enunciado
    elif lista_bruta and len(alts_do_enunciado) >= 2:
        # Remove as alternativas duplicadas do enunciado
        enunciado_raw = enunciado_limpo

    alts_com_prefixo = []
    alts_sem_prefixo = []
    for item in lista_bruta:
        limpo = _limpar_prefixo_alternativa(item)
        if not limpo:
            continue
        idx = len(alts_com_prefixo)
        if idx >= len(letras):
            break
        letra = letras[idx]
        alts_com_prefixo.append(f"{letra}) {limpo}")
        alts_sem_prefixo.append(limpo)

    enunciado_final = enunciado_limpo if (len(alts_do_enunciado) >= 2 or alts_com_prefixo) else (enunciado_raw or "").strip()
    return enunciado_final, alts_com_prefixo, alts_sem_prefixo


def processarRespostaIA(resposta_ia):
    """
    Processa e normaliza o JSON retornado pelo LLM na geração de questões, garantindo que
    qualquer questão objetiva/múltipla escolha tenha suas alternativas extraídas e estruturadas.
    """
    try:
        if isinstance(resposta_ia, dict):
            dados = resposta_ia
        else:
            resposta_limpa = re.sub(r'^```(?:json)?\s*|\s*```$', '', (resposta_ia or '').strip())
            dados = extrair_json_da_resposta(resposta_limpa)

        if not isinstance(dados, dict):
            return {"perguntas": []}

        perguntas_raw = dados.get("perguntas")
        if not isinstance(perguntas_raw, list):
            return dados

        from mimir.models import TiposDePergunta
        tipos_db = list(TiposDePergunta.objects.all())

        perguntas_normalizadas = []
        for idx_q, q in enumerate(perguntas_raw, 1):
            if not isinstance(q, dict):
                continue

            tipo_str = str(q.get("tipo") or q.get("tipo_pergunta") or "").strip()
            enunciado_raw = str(q.get("enunciado") or q.get("pergunta") or "").strip()
            resposta_raw = str(q.get("resposta") or q.get("gabarito") or "").strip()

            # Captura alternativas independentemente da chave usada pela IA (alternativas, alternativa, opcoes, options)
            raw_alts = (
                q.get("alternativas")
                if q.get("alternativas") is not None
                else (
                    q.get("alternativa")
                    if q.get("alternativa") is not None
                    else (q.get("opcoes") or q.get("options") or [])
                )
            )

            enunciado_limpo, alts_com_prefixo, alts_sem_prefixo = normalizar_alternativas_questao(raw_alts, enunciado_raw)

            # Vincula ao TiposDePergunta correspondente no banco
            tipo_obj = None
            for t in tipos_db:
                if t.descricao.strip().lower() == tipo_str.lower():
                    tipo_obj = t
                    break
            if not tipo_obj and tipo_str:
                for t in tipos_db:
                    if tipo_str.lower() in t.descricao.lower() or t.descricao.lower() in tipo_str.lower():
                        tipo_obj = t
                        break

            eh_objetiva = bool(alts_com_prefixo) or (tipo_obj.is_objetiva if tipo_obj else any(
                p in tipo_str.lower() for p in ["múltipla", "multipla", "objetiva", "alternativa", "escolha", "asserção", "assercao", "afirmativa", "verdadeiro"]
            ))

            # Se o tipo é objetivo mas a IA não enviou alternativas separadas, garante 5 espaços editáveis
            if eh_objetiva and len(alts_com_prefixo) < 2:
                qtd_padrao = tipo_obj.qtd_alternativas if tipo_obj else 5
                letras = "ABCDEFGH"[:max(2, qtd_padrao)]
                alts_com_prefixo = []
                alts_sem_prefixo = []
                for idx_l, l in enumerate(letras):
                    txt_op = (
                        _limpar_prefixo_alternativa(resposta_raw)
                        if (idx_l == 0 and resposta_raw)
                        else f"Opção {l} (edite o texto desta alternativa)"
                    )
                    alts_com_prefixo.append(f"{l}) {txt_op}")
                    alts_sem_prefixo.append(txt_op)

            # Identifica a letra correta (A-E) para pré-marcar no editor de revisão
            letra_correta = "A"
            if eh_objetiva and resposta_raw:
                m_gab = re.match(r'^\s*(?:letra|alternativa|opção|resposta|gabarito)?\s*[:\-]?\s*\(?([A-Ha-h])(?:\b|[\)\.\-:])', resposta_raw, re.IGNORECASE)
                if m_gab:
                    letra_cand = m_gab.group(1).upper()
                    if letra_cand in "ABCDEFGH"[:max(2, len(alts_com_prefixo))]:
                        letra_correta = letra_cand
                else:
                    # Tenta casar pelo texto da alternativa
                    resp_norm = _limpar_prefixo_alternativa(resposta_raw).lower()
                    for i_alt, txt_alt in enumerate(alts_sem_prefixo):
                        if txt_alt.lower() == resp_norm or (len(txt_alt) > 10 and txt_alt.lower() in resp_norm):
                            letra_correta = "ABCDEFGH"[i_alt]
                            break

            perguntas_normalizadas.append({
                "tipo": tipo_obj.descricao if tipo_obj else (tipo_str or "Múltipla Escolha"),
                "tipo_id": tipo_obj.id if tipo_obj else "",
                "is_objetiva": eh_objetiva,
                "enunciado": enunciado_limpo,
                "alternativas": alts_com_prefixo,
                "alternativas_sem_prefixo": alts_sem_prefixo,
                "letra_correta": letra_correta,
                "resposta": resposta_raw,
            })

        dados["perguntas"] = perguntas_normalizadas
        return dados
    except Exception as e:
        print(f"Erro ao processar resposta da IA: {str(e)}")
        return {"perguntas": [], "erro": str(e)}


def _reparar_json_string_llm(raw_json: str) -> str:
    r"""
    Repara problemas clássicos de JSON gerados por LLMs (Gemini / Ollama):
      1. Quebras de linha literais (\n, \r) e tabulações (\t) não escapadas dentro de strings JSON.
      2. Barras invertidas (\) inválidas em JSON (ex.: LaTeX \frac, regex \d, caminhos).
      3. Aspas duplas internas não escapadas dentro de valores de texto/código.
      4. Vírgulas sobrando antes de } ou ].
    """
    s = (raw_json or "").strip()
    if not s:
        return s

    out = []
    in_string = False
    n = len(s)
    i = 0

    while i < n:
        ch = s[i]
        if not in_string:
            if ch == '"':
                in_string = True
                out.append(ch)
            else:
                out.append(ch)
            i += 1
            continue

        # Dentro de uma string JSON ("...")
        if ch == '\\':
            if i + 1 < n:
                nxt = s[i + 1]
                if nxt in ('"', '\\', '/', 'b', 'f', 'n', 'r', 't'):
                    out.append('\\')
                    out.append(nxt)
                    i += 2
                    continue
                elif nxt == 'u' and i + 5 < n and all(c in '0123456789abcdefABCDEF' for c in s[i + 2:i + 6]):
                    out.append(s[i:i + 6])
                    i += 6
                    continue
            # Barra invertida solta (ex: \d, \s, \frac) -> escapa como \\
            out.append('\\\\')
            i += 1
            continue

        if ch == '\n':
            out.append('\\n')
            i += 1
            continue
        if ch == '\r':
            i += 1
            continue
        if ch == '\t':
            out.append('\\t')
            i += 1
            continue
        if ord(ch) < 32:
            out.append(' ')
            i += 1
            continue

        if ch == '"':
            # Verifica se esta aspa realmente fecha a string JSON (seguida de :, ,, }, ] após espaços)
            j = i + 1
            while j < n and s[j] in (' ', '\t', '\r', '\n'):
                j += 1
            if j >= n or s[j] in (':', ',', '}', ']'):
                in_string = False
                out.append('"')
            else:
                # Aspa dupla no meio do texto/código sem escape -> escapa como \"
                out.append('\\"')
            i += 1
            continue

        out.append(ch)
        i += 1

    reparado = "".join(out)
    reparado = re.sub(r',\s*([\}\]])', r'\1', reparado)
    return reparado


def _normalizar_estrutura_raiz_perguntas(obj) -> dict | None:
    """
    Aceita qualquer variação de estrutura JSON retornada pelo LLM:
      - {"perguntas": [...]}
      - {"questoes": [...]} / {"questions": [...]} / {"itens": [...]}
      - [{"enunciado": ...}, ...] (lista direta)
      - {"tipo": ..., "enunciado": ..., "resposta": ...} (objeto de questão única)
      - {"1": {"enunciado": ...}, "2": {"enunciado": ...}} (dicionário indexado)
    """
    if isinstance(obj, list):
        validos = [x for x in obj if isinstance(x, dict) and (x.get("enunciado") or x.get("pergunta") or x.get("question") or x.get("texto"))]
        if validos:
            return {"perguntas": validos}
        return None

    if not isinstance(obj, dict):
        return None

    for chave_lista in ("perguntas", "questoes", "questões", "questions", "itens", "items", "dados", "data"):
        val = obj.get(chave_lista)
        if isinstance(val, list) and len(val) > 0:
            return {"perguntas": val}
        if isinstance(val, dict):
            sub_vals = [v for v in val.values() if isinstance(v, dict)]
            if sub_vals:
                return {"perguntas": sub_vals}

    # Caso o LLM tenha retornado um único objeto de questão direto na raiz
    if obj.get("enunciado") or obj.get("pergunta") or obj.get("question") or obj.get("texto"):
        return {"perguntas": [obj]}

    # Caso o LLM tenha retornado {"questao_1": {...}, "questao_2": {...}}
    valores_dict = [
        v for v in obj.values()
        if isinstance(v, dict) and (v.get("enunciado") or v.get("pergunta") or v.get("question") or v.get("texto"))
    ]
    if valores_dict:
        return {"perguntas": valores_dict}

    return None


def _extrair_objetos_json_balanceados(texto: str) -> list[str]:
    """
    Varre o texto e extrai blocos JSON `{...}` balanceados (ignorando chaves dentro de strings),
    permitindo recuperar questões individuais mesmo quando o JSON geral está truncado ou corrompido.
    """
    blocos = []
    n = len(texto)
    i = 0
    while i < n:
        if texto[i] == '{':
            depth = 0
            in_str = False
            escape = False
            start = i
            j = i
            while j < n:
                c = texto[j]
                if in_str:
                    if escape:
                        escape = False
                    elif c == '\\':
                        escape = True
                    elif c == '"':
                        in_str = False
                else:
                    if c == '"':
                        in_str = True
                    elif c == '{':
                        depth += 1
                    elif c == '}':
                        depth -= 1
                        if depth == 0:
                            blocos.append(texto[start:j + 1])
                            break
                j += 1
            i = start + 1
        else:
            i += 1
    return blocos


def _extrair_perguntas_de_texto_markdown(texto: str) -> list[dict]:
    """
    Fallback final: caso o LLM (ex.: modelo local) tenha respondido em texto livre / Markdown
    em vez de JSON, extrai as questões, alternativas A-E e gabaritos do texto.
    """
    linhas = [l.rstrip() for l in (texto or "").splitlines()]
    if not linhas:
        return []

    # Divide por cabeçalhos como "Questão 1", "1.", "### Pergunta 1"
    blocos_q = re.split(
        r'(?m)^(?:\s*#{1,4}\s*|\s*\*{1,2})?(?:Quest[ãa]o|Pergunta)\s+\d+[:\.\-\)\*]*\s*|^(?=\s*\d+[\.\)]\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ\[])',
        texto,
        flags=re.IGNORECASE,
    )
    blocos_q = [b.strip() for b in blocos_q if b and len(b.strip()) > 25]
    if not blocos_q and len(texto.strip()) > 30:
        blocos_q = [texto.strip()]

    perguntas = []
    for bloco in blocos_q:
        # Procura linha de Gabarito / Resposta no final do bloco
        m_gab = re.search(
            r'(?mi)^\s*[\*\-_]*(?:Gabarito|Resposta(?:\s+correta|\s+esperada)?|Padr[ãa]o\s+de\s+resposta)[\*\-_]*\s*[:\-]\s*([\s\S]+)$',
            bloco,
        )
        if m_gab:
            resposta = m_gab.group(1).strip()
            corpo_pergunta = bloco[:m_gab.start()].strip()
        else:
            resposta = "A"
            corpo_pergunta = bloco.strip()

        enunc_limpo, alts_extraidas = _extrair_alternativas_de_texto_multiline(corpo_pergunta)
        if enunc_limpo:
            perguntas.append({
                "tipo": "Múltipla Escolha" if len(alts_extraidas) >= 2 else "Dissertativa",
                "enunciado": enunc_limpo,
                "alternativas": alts_extraidas,
                "resposta": resposta,
            })

    return perguntas


def extrair_json_da_resposta(texto):
    """
    Extrai e repara JSON retornado pelo LLM (objeto {"perguntas": [...]}, lista [...] ou
    variações de chaves), tratando blocos markdown ```json, quebras de linha literais em
    strings, aspas internas em código, barras invertidas e fallback Markdown.
    """
    norm_direto = _normalizar_estrutura_raiz_perguntas(texto)
    if norm_direto:
        return norm_direto

    bruto = (str(texto or "")).strip()
    if not bruto:
        return {"perguntas": [], "erro": "A IA retornou uma resposta vazia."}

    # 1. Tenta o parser nativo do LangChain primeiro
    try:
        parsed_lc = JsonOutputParser().parse(bruto)
        norm_lc = _normalizar_estrutura_raiz_perguntas(parsed_lc)
        if norm_lc:
            return norm_lc
    except Exception:
        pass

    # 2. Remove cercas markdown ```json ... ``` externas
    limpo = re.sub(r'^\s*```(?:json)?\s*', '', bruto, flags=re.IGNORECASE)
    limpo = re.sub(r'\s*```\s*$', '', limpo)

    candidatos = [limpo]

    idx_obj_ini = limpo.find('{')
    idx_obj_fim = limpo.rfind('}')
    idx_arr_ini = limpo.find('[')
    idx_arr_fim = limpo.rfind(']')

    if idx_obj_ini != -1 and idx_obj_fim > idx_obj_ini:
        if idx_arr_ini != -1 and idx_arr_ini < idx_obj_ini and idx_arr_fim > idx_obj_fim:
            candidatos.append(limpo[idx_arr_ini:idx_arr_fim + 1])
        candidatos.append(limpo[idx_obj_ini:idx_obj_fim + 1])
    elif idx_arr_ini != -1 and idx_arr_fim > idx_arr_ini:
        candidatos.append(limpo[idx_arr_ini:idx_arr_fim + 1])

    for cand in candidatos:
        for tentativa in (cand, _reparar_json_string_llm(cand)):
            for loader in (json.loads, ast.literal_eval):
                try:
                    res = loader(tentativa)
                    norm = _normalizar_estrutura_raiz_perguntas(res)
                    if norm:
                        return norm
                except Exception:
                    pass

    # 3. Extração de objetos JSON `{...}` individuais balanceados (caso o JSON externo tenha quebrado)
    objetos_recuperados = []
    for bloco_q in _extrair_objetos_json_balanceados(limpo):
        if len(bloco_q) < 20 or ('"enunciado"' not in bloco_q and '"pergunta"' not in bloco_q and '"question"' not in bloco_q):
            continue
        for t_q in (bloco_q, _reparar_json_string_llm(bloco_q)):
            try:
                obj_q = json.loads(t_q)
                if isinstance(obj_q, dict) and (obj_q.get("enunciado") or obj_q.get("pergunta") or obj_q.get("question")):
                    # Evita adicionar o objeto raiz caso ele também tenha sido capturado sem lista válida
                    if not isinstance(obj_q.get("perguntas"), list):
                        objetos_recuperados.append(obj_q)
                    break
            except Exception:
                continue

    if objetos_recuperados:
        return {"perguntas": objetos_recuperados}

    # 4. Fallback de texto livre / Markdown (nunca falha se o LLM escreveu as questões fora de JSON)
    perguntas_md = _extrair_perguntas_de_texto_markdown(limpo)
    if perguntas_md:
        return {"perguntas": perguntas_md}

    return {"perguntas": [], "erro": "Não foi possível processar o formato retornado pelo modelo."}


def construirTextoPerguntaCompleto(enunciado, tipo_pergunta, pergunta_id, post_data):
    """
    Constrói o texto completo da pergunta (`enunciado` + `A) ... B) ... C) ...`) ao salvar
    perguntas geradas por IA ou formulários em lote.
    Funciona para QUALQUER tipo de pergunta que possua alternativas preenchidas no POST
    (não apenas tipos cujo nome contenha a palavra 'múltipla').
    """
    enunciado_base = (enunciado or "").strip()
    prefixo = f'pergunta_{pergunta_id}'
    modo_post = (post_data.get(f'{prefixo}_modo_questao') or '').strip().lower()

    # Coleta alternativas enviadas como lista `pergunta_{id}_alternativa_item[]` ou indexadas `pergunta_{id}_alternativa_{i}`
    alternativas_brutas = []
    if hasattr(post_data, 'getlist'):
        lista_items = post_data.getlist(f'{prefixo}_alternativa_item[]')
        if lista_items:
            alternativas_brutas = [x.strip() for x in lista_items if (x or '').strip()]

    if not alternativas_brutas:
        for i in range(1, 12):
            alternativa_key = f'{prefixo}_alternativa_{i}'
            val = (post_data.get(alternativa_key) or '').strip()
            if val:
                alternativas_brutas.append(val)

    # Se o usuário explicitamente marcou como dissertativa no card de revisão, retorna apenas o enunciado
    if modo_post == 'dissertativa':
        return enunciado_base

    if alternativas_brutas:
        # Remove eventuais alternativas duplicadas que já estivessem no final do enunciado
        enunciado_limpo, _ = _extrair_alternativas_de_texto_multiline(enunciado_base)
        if enunciado_limpo:
            enunciado_base = enunciado_limpo

        letras = "ABCDEFGH"
        linhas_alts = []
        for idx, alt in enumerate(alternativas_brutas[:len(letras)]):
            txt_limpo = _limpar_prefixo_alternativa(alt)
            if txt_limpo:
                linhas_alts.append(f"{letras[idx]}) {txt_limpo}")

        if linhas_alts:
            return f"{enunciado_base}\n\n" + "\n".join(linhas_alts)

    return enunciado_base

def processar_pdf_em_lotes(file_path, fileName, max_pages_per_batch=20):
    textos_por_lote = []
    try:
        with pdfplumber.open(file_path) as pdf:
            total_paginas = len(pdf.pages)
            lotes = [pdf.pages[i:i+max_pages_per_batch] for i in range(0, total_paginas, max_pages_per_batch)]
            for indice_lote, lote_paginas in enumerate(lotes):
                texto_lote = f"FONTE: {fileName} - LOTE {indice_lote + 1}\n"
                for i, pagina in enumerate(lote_paginas, 1):
                    try:
                        texto_pagina = pagina.extract_text()
                        if texto_pagina and texto_pagina.strip():
                            texto_lote += f"--- PÁGINA {(indice_lote * max_pages_per_batch) + i} ---\n{texto_pagina.strip()}\n\n"
                    except Exception as e:
                        texto_lote += f"Erro na página {(indice_lote * max_pages_per_batch) + i}: {str(e)}\n"
                textos_por_lote.append(texto_lote)
    except Exception as e:
        textos_por_lote.append(f"Erro ao processar {file_path}: {str(e)}")
    return textos_por_lote

def avaliarProbabilidadeProjeto(texto_projeto_atual, lista_feedbacks_passados, user=None):
    """
    Cruza o projeto atual com feedbacks antigos usando RAG em memória 
    para prever a aprovação e gerar insights de mitigação.
    """
    try:
        # 1. Se não houver histórico, criamos um contexto genérico para o LLM não falhar
        if not lista_feedbacks_passados or len(lista_feedbacks_passados) == 0:
            texto_historico_consolidado = "Não há histórico de feedbacks passados no sistema. Avalie o projeto apenas com base em boas práticas universais de redação científica e estruturação de projetos."
            retriever = None
        else:
            # Consolida o histórico e fragmenta para o RAG
            texto_historico_consolidado = "\n\n--- NOVO PARECER/FEEDBACK ---\n\n".join(lista_feedbacks_passados)
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=150)
            docs_historico = text_splitter.create_documents([texto_historico_consolidado])
            
            # Cria o Banco Vetorial FAISS com o histórico
            embeddings = get_embeddings()
            vectorstore = FAISS.from_documents(docs_historico, embeddings)
            
            # O Retriever vai buscar as avaliações passadas mais parecidas com o tema do projeto atual
            retriever = vectorstore.as_retriever(search_kwargs={"k": 5})

        # 2. Prepara a Corrente LCEL
        prompt_template, parser = criar_template_analise_projeto()
        llm = get_llm()

        # Função auxiliar para extrair texto do retriever
        def get_contexto(projeto_text):
            if retriever:
                docs = retriever.invoke(projeto_text)
                return "\n\n".join([d.page_content for d in docs])
            return texto_historico_consolidado

        rag_chain = (
            {
                "contexto_historico": lambda x: get_contexto(x["projeto_atual"]),
                "projeto_atual": lambda x: x["projeto_atual"],
                "format_instructions": lambda x: x["format_instructions"]
            }
            | prompt_template
            | llm
            | parser
        )

        inputs = {
            "projeto_atual": texto_projeto_atual,
            "format_instructions": parser.get_format_instructions()
        }

        # 3. Execução e Log
        response = invoke_chain(rag_chain, inputs, endpoint='avaliarProbabilidadeProjeto', user=user)
        return json.dumps(response, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps({
            "probabilidade_aprovacao": 0,
            "pontos_fortes": [],
            "pontos_fracos": [],
            "mitigacoes": [f"Erro ao processar análise preditiva: {str(e)}"]
        }, ensure_ascii=False)
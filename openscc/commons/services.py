import base64, io, json, re, pdfplumber, time, ast
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

from mimir.models import LLMLog, Edital

# ==========================================
# CONFIGURAÇÃO DE MODELOS E EMBEDDINGS
# ==========================================
def get_llm():
    """Retorna uma instância configurada do LLM"""
    if settings.GEMINI_API_KEY is None or settings.GEMINI_API_KEY == "":
        print("Usando modelo Ollama Gemma 3 localmente")
        return ChatOllama(
            model="gemma3:12b",
            temperature=0.7
            #base_url="http://192.168.86.20:11434",
        )
    return ChatGoogleGenerativeAI(
        model="gemini-3.1-flash-lite",  # ou "gemini-1.5-flash"
        google_api_key=settings.GEMINI_API_KEY,
        temperature=0.7,
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
    model_used = model_name or 'unknown'
    
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
    template = """TODO TEXTO QUE VOCÊ GERAR DEVE SER EM JSON, SIGA AS INSTRUÇÕES ABAIXO.

BASEADO NO SEGUINTE EXTRATO DE DOCUMENTO:
{conteudo_pdf}

GERE {total_perguntas} QUESTÕES DE PROVA SOBRE O ASSUNTO:
{tipo_perguntas}

{info_extras}

# INSTRUÇÕES DE FORMATO:
- GERE O GABARITO DE TODAS
- PARA AS DISSERTATIVAS, GERE O PADRÃO DE RESPOSTA ESPERADO        
- FORMATE TODA A SAÍDA EM JSON COM A CHAVE "perguntas" E O VALOR SENDO UM ARRAY DE OBJETOS COM "tipo", "enunciado", "alternativa" E "resposta"
- NÃO UTILIZE NENHUMA TAG HTML
- AO GERAR AS ALTERNATIVAS, UTILIZE LETRAS PARA IDENTIFICAR CADA ALTERNATIVA
- AS ALTERNATIVAS SEMPRE DEVEM CONTER O SEGUINTE FORMATO: "A) texto\n B) texto\n C) texto\n D) texto\n E) texto"
- A CHAVE "alternativas" NO JSON SEMPRE DEVE SER UM ARRAY E NUNCA UM OBJETO
- VOCÊ DEVE GERAR EXATAMENTE O NÚMERO DE QUESTÕES SOLICITADO
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

def getQuestionsFromSource(file_path, qtPerguntas, infoExtras, user=None):
    """
    Nova Arquitetura Agnóstica (RAG In-Memory).
    Extrai informações usando Banco Vetorial FAISS para evitar estouro de contexto
    na criação de questões de prova em documentos extensos.
    """
    totalPerguntas = sum(qtPerguntas.values())
    textoPerguntas = "\n".join([f"{k};" for k in qtPerguntas])
    
    try:
        # 1. Extrair e juntar texto bruto
        completoTudo = ''
        for fp in file_path:
            conteudo_extraido = extrair_texto_pdf(fp[0])
            completoTudo += "\n".join(conteudo_extraido) + "\n\n"
            
        # 2. Fragmentar em blocos de conhecimento semântico
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=150)
        docs = text_splitter.create_documents([completoTudo])
        
        # 3. Criação do Banco Vetorial e do Buscador (Retriever)
        embeddings = get_embeddings()
        vectorstore = FAISS.from_documents(docs, embeddings)
        
        # Traz os 6 chunks mais relevantes relacionados ao tema das perguntas
        retriever = vectorstore.as_retriever(search_kwargs={"k": 6})
        
        # 4. Formatação da corrente LCEL
        prompt_template, parser = criar_template_questoes()
        llm = get_llm()
        
        def format_docs(docs_retrieved):
            return "\n\n".join([d.page_content for d in docs_retrieved])

        rag_chain = (
            {
                "conteudo_pdf": lambda x: format_docs(retriever.invoke(x["query"])),
                "total_perguntas": lambda x: x["total_perguntas"],
                "tipo_perguntas": lambda x: x["tipo_perguntas"],
                "info_extras": lambda x: x["info_extras"],
                "format_instructions": lambda x: x["format_instructions"]
            }
            | prompt_template
            | llm
            | parser
        )
        
        # Monta a query para o Retriever puxar apenas a área do PDF relevante para as questões
        query_busca = f"Conteúdo sobre: {', '.join(qtPerguntas.keys())}"
        
        inputs = {
            "query": query_busca,
            "total_perguntas": totalPerguntas,
            "tipo_perguntas": textoPerguntas,
            "info_extras": infoExtras,
            "format_instructions": parser.get_format_instructions()
        }
        
        response = invoke_chain(rag_chain, inputs, endpoint='getQuestionsFromSource', user=user)
        print(response)
        return json.dumps(response, ensure_ascii=False, indent=2)
        
    except Exception as e:
        return json.dumps({
            "perguntas": [],
            "erro": f"Erro ao gerar questões via RAG: {str(e)}"
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
    model_name = "gemini-2.5-flash"
    tokens_input = None
    tokens_output = None
    output = None
    try:
        llm = ChatGoogleGenerativeAI(model=model_name, google_api_key=settings.GEMINI_API_KEY, temperature=0.3)
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
        texto = []
        with pdfplumber.open(caminho_arquivo) as pdf:
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

def processarRespostaIA(resposta_ia):
    try:
        resposta_limpa = re.sub(r'^```json\n|\n```$', '', resposta_ia.strip())
        return json.loads(resposta_limpa)
    except Exception as e:
        print(f"Erro ao processar resposta da IA: {str(e)}")
        return []

def extrair_json_da_resposta(texto):
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        match = re.search(r'\{[\s\S]*\}', texto)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                json_str = match.group()
                json_str = re.sub(r',\s*}', '}', json_str)
                json_str = re.sub(r',\s*]', ']', json_str)
                try:
                    return json.loads(json_str)
                except:
                    pass
        return {"perguntas": [], "erro": "Não foi possível processar o JSON"}

def construirTextoPerguntaCompleto(enunciado, tipo_pergunta, pergunta_id, post_data):
    tipo_pergunta = tipo_pergunta.lower() if tipo_pergunta else ''
    if 'múltipla' in tipo_pergunta.lower() or 'multipla' in tipo_pergunta.lower():
        alternativas = []
        prefixo = f'pergunta_{pergunta_id}'
        i = 1
        while True:
            alternativa_key = f'{prefixo}_alternativa_{i}'
            alternativa = post_data.get(alternativa_key, '').strip()
            if not alternativa: break
            alternativas.append(alternativa)
            i += 1
        if alternativas:
            texto_pergunta = enunciado + "\n\n"
            for j, alternativa in enumerate(alternativas, 1):
                texto_pergunta += f"{alternativa}\n"
            return texto_pergunta.strip()
    return enunciado

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
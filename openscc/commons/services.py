import base64, io, json, re, pdfplumber, time
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from PIL import Image
from django.core.files.storage import default_storage
from django.conf import settings
from langchain_ollama import ChatOllama
from typing import List, Optional
from mimir.models import LLMLog
# Configuração do modelo LangChain
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

def invoke_chain(chain, inputs, endpoint, user=None, model_name=None):
    """
    Executa uma chain do LangChain e registra o log.
    Retorna o objeto resposta original.
    """
    start_time = time.time()
    error = None
    response = None
    status = 'success'
    tokens_input = None
    tokens_output = None
    model_used = model_name or 'unknown'
    
    try:
        response = chain.invoke(inputs)
        # Tenta extrair tokens de uso (se disponível)
        if hasattr(response, 'usage_metadata'):
            tokens_input = response.usage_metadata.get('input_tokens')
            tokens_output = response.usage_metadata.get('output_tokens')
    except Exception as e:
        status = 'error'
        error = str(e)
        raise e  # Relança para que a aplicação trate o erro
    finally:
        duration = int((time.time() - start_time) * 1000)
        
        # Conteúdo da resposta (string)
        response_content = None
        if response:
            if hasattr(response, 'content'):
                response_content = response.content
            elif isinstance(response, str):
                response_content = response
            else:
                response_content = str(response)
        
        # Cria o registro no banco
        LLMLog.objects.create(
            user=user,
            prompt=str(inputs),  # Pode ser muito grande, considere truncar se necessário
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

# Esquema para questões individuais
class QuestaoSchema(BaseModel):
    tipo: str = Field(description="Tipo da questão (ex: múltipla escolha, discursiva)")
    enunciado: str = Field(description="Texto completo do enunciado da questão")
    alternativas: Optional[List[str]] = Field(default=None, description="Lista de alternativas para questões de múltipla escolha")
    resposta: str = Field(description="Gabarito ou padrão de resposta esperado")

# Esquema para lista de perguntas
class PerguntasSchema(BaseModel):
    perguntas: List[QuestaoSchema] = Field(description="Lista de questões geradas")

# Esquema para correção
class CorrecaoSchema(BaseModel):
    nota: float = Field(description="Nota de 0 a 10", ge=0, le=10)
    justificativa: str = Field(description="Análise detalhada da resposta")

# Esquema para guia do tutor
class GuiaTutorSchema(BaseModel):
    guia_tutor: str = Field(description="Texto completo do guia do tutor")

# Criar prompt templates
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
8. Identificação e Queixa: Dados sociodemográficos e motivo da consulta.
9. Relato Espontâneo: Citações diretas da paciente expressando sentimentos, dúvidas e ansiedades (essencial para a dimensão biopsicossocial).
10. Anamnese e Exame Físico: Descrição técnica detalhada, incluindo sinais vitais e dados antropométricos.
11. Exames Complementares: Resultados com Valores de Referência (VR).
12. Evolução: Progressão no tempo (ex: retorno semanas depois) e desfecho (ex: descrição da placenta e parto).

Diretrizes importantes:
- Foque em atender especificamente às instruções do usuário
- Mantenha o fluxo narrativo natural
- Não quebre a continuidade com as partes seguintes
- Se as instruções pedirem mudanças específicas, implemente-as claramente

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
- O problema deve ter um título relevante e isso deve aparecer na parte 1, mas não precisa ser repetido nas partes seguintes.
- Mantenha o fluxo narrativo natural, como se fosse uma história real.
- Não adicione * ou qualquer outro tipo de caracter de marcação.
- Sempre que forem os personagens da história falando, coloque o conteúdo entre aspas
- Forneça apenas o texto da parte {parte_atual} em texto puro.
""")
])

# Template para geração de questões
def criar_template_questoes():
    """Cria template com instruções de JSON explícitas"""
    parser = JsonOutputParser(pydantic_object=PerguntasSchema)
    
    template = """TODO TEXTO QUE VOCÊ GERAR DEVE SER EM JSON, SIGA AS INSTRUÇÕES ABAIXO.

BASEADO NO CONTEÚDO ABAIXO DE UM DOCUMENTO PDF:
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
- AS LETRAS NÃO DEVEM SER CHAVES DO JSON, APENAS O TEXTO DA ALTERNATIVA
- AS ALTERNATIVAS SEMPRE DEVEM CONTER O SEGUINTE FORMATO: "A) texto da alternativa\n B) texto da alternativa\n C) texto da alternativa\n D) texto da alternativa\n E) texto da alternativa"
- A CHAVE "alternativas", EM CASO DE QUESTÃO QUE AS TENHAM, NO JSON SEMPRE DEVE SER UM ARRAY E NUNCA UM OBJETO
- O PADRÃO DE RESPOSTA E O GABARITO DE ALTERNATIVAS DEVEM FICAR NA CHAVE "resposta"
- CONTEMPLE TODOS OS MATERIAIS PARA A GERAÇÃO DAS QUESTÕES, OU SEJA, PELO MENOS UMA QUESTÃO DE CADA TEMA SOLICITADO
- VOCÊ DEVE GERAR EXATAMENTE O NÚMERO DE QUESTÕES SOLICITADO PARA CADA TIPO, NEM MAIS, NEM MENOS
- NO CAMPO TIPO DO JSON COLOQUE O TIPO DE QUESTÃO SOLICITADO CONFORME ENVIADO PELO PROMPT
- O TIPO DEVE SER IGUAL AO TIPO SOLICITADO
{format_instructions}

REGRAS:
Para questões dissertativas: use "alternativas": null
Para múltipla escolha: "alternativas" deve ter 5 itens no formato "A) texto"
Use apenas aspas duplas
Não adicione texto fora do JSON
Não use markdown além do bloco json

IMPORTANTE - DE FORMA ALGUMA ADICIONE TEXTO FORA DO JSON
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
- SEJA CRITERIONOSO E JUSTO.
- FORNEÇA UMA NOTA DE 0 A 10, CONSIDERANDO A COMPLETUDE E CORREÇÃO DA RESPOSTA.
- Justificativa deve analisar a qualidade técnica da resposta
- Compare com o gabarito oficial
- Identifique acertos, erros e omissões
- Seja construtivo e educativo
- Retorne APENAS um JSON no formato:
{{
  "nota": 0-10,
  "justificativa": "análise detalhada"
}}
- NÃO UTILIZE NENHUMA TAG HTML
- TRATE O ALUNO NA SEGUNDA PESSOA DO SINGULAR (VOCÊ)
""")
])


# Funções principais convertidas
def criarPromptGuiaTutor(titulo, tema, assunto, objetivos, texto_problema, fontes_info, instrucoesGuia):
    """Cria guia do tutor usando LangChain"""
    chain = guia_tutor_template | get_llm()
    
    response = chain.invoke({
        "titulo": titulo,
        "tema": tema,
        "assunto": assunto,
        "objetivos": ", ".join(objetivos),
        "texto_problema": texto_problema,
        "fontes_info": fontes_info,
        "instrucoesGuia": instrucoesGuia
    })
    
    return response.content

def regerarParte(tema, assunto, objetivos, parte_ordem, contexto_anterior, fontes, instrucoes, parte_original, instrucoes_layout="", user=None):
    """Regera parte usando LangChain"""
    chain = regerar_parte_template | get_llm()
    
    inputs = {
        "tema": tema,
        "assunto": assunto,
        "objetivos": ", ".join(objetivos),
        "parte_ordem": parte_ordem,
        "parte_ordem_anterior": parte_ordem - 1,
        "contexto_anterior": contexto_anterior,
        "fontes": fontes,
        "instrucoes": instrucoes,
        "parte_original": parte_original,
        "instrucoes_layout": instrucoes_layout
    }

    response = invoke_chain(chain, inputs, endpoint='regerarParte',user=user)
    
    return response.content if hasattr(response, 'content') else str(response)

def criarPromptParaParte(tema, assunto, objetivos, parte_atual, total_partes, contexto_anterior, fontes, instrucoes_layout="", user=None):
    """Cria parte do problema usando LangChain"""
    chain = criar_parte_template | get_llm()

    inputs = {
        "tema": tema,
        "assunto": assunto,
        "objetivos": ", ".join(objetivos),
        "parte_atual": parte_atual,
        "total_partes": total_partes if total_partes else "N",
        "contexto_anterior": contexto_anterior,
        "fontes": fontes,
        "instrucoes_layout": instrucoes_layout
    }

    response = invoke_chain(chain, inputs, endpoint='criarPromptParaParte', user=user)
    
    return response.content if hasattr(response, 'content') else str(response)

def chamarApiLLM(prompt, user=None, endpoint='chamarApiLLM'):
    llm = get_llm()
    model_name = getattr(llm, 'model', 'unknown')
    start_time = time.time()
    error = None
    response_content = None
    status = 'success'
    
    try:
        response = llm.invoke(prompt)
        if hasattr(response, 'content'):
            response_content = response.content
        else:
            response_content = str(response)
    except Exception as e:
        status = 'error'
        error = str(e)
        raise e
    finally:
        duration = int((time.time() - start_time) * 1000)
        LLMLog.objects.create(
            user=user,
            prompt=prompt,
            response=response_content,
            model_used=model_name,
            duration_ms=duration,
            status=status,
            error_message=error,
            endpoint=endpoint
        )
    
    return response_content

def getQuestionsFromSource(file_path, qtPerguntas, infoExtras, user=None):
    """Gera questões a partir do conteúdo do PDF usando LangChain com JSON parsing"""
    totalPerguntas = sum(qtPerguntas.values())
    textoPerguntas = "\n".join([f"{k};" for k in qtPerguntas])
    
    try:
        # Extrair texto do PDF
        completoTudo = ''
        for fp in file_path:
            conteudo_extraido = extrair_texto_pdf(fp[0])
            texto_completo = "\n".join(conteudo_extraido)
            completoTudo += f"FONTE - {fp[1]}\n" + texto_completo + "\n\n"
        
        # Limitar tamanho para evitar timeout
        conteudo_limitado = completoTudo
        
        # Criar chain com parser JSON        
        prompt_template, parser = criar_template_questoes()
        print(prompt_template)

        chain = prompt_template | get_llm() | parser
        
        # Invocar chain
        inputs = {
            "conteudo_pdf": conteudo_limitado,
            "total_perguntas": totalPerguntas,
            "tipo_perguntas": textoPerguntas,
            "info_extras": infoExtras,
            "format_instructions": parser.get_format_instructions()
        }
        print(inputs)
        response = invoke_chain(chain, inputs, endpoint='getQuestionsFromSource', 
                                user=user)
        
        return json.dumps(response, ensure_ascii=False, indent=2)
        
    except Exception as e:
        # Fallback para versão manual se o parsing automático falhar
        return json.dumps({
            "perguntas": [],
            "erro": f"Erro ao gerar questões: {str(e)}"
        }, ensure_ascii=False)

def fazerCorrecaoComModelo(enunciado, gabarito, resposta_aluno, user=None):
    """Corrige resposta usando LangChain"""
    try:
        # Criar chain com parser JSON
        parser = JsonOutputParser()
        chain = correcao_template | get_llm() | parser
        
        # Invocar chain
        inputs = {
            "enunciado": enunciado,
            "gabarito": gabarito,
            "resposta_aluno": resposta_aluno
        }
        response = invoke_chain(chain, inputs, endpoint='fazerCorrecaoComModelo', user=user)
        
        return json.dumps(response, ensure_ascii=False)
        
    except Exception as e:
        return json.dumps({
            "nota": 0,
            "justificativa": f"Erro na correção: {str(e)}"
        })

def corrigirRespostaMultimodal(enunciado, gabarito, resposta_aluno, imagens_pergunta=None, user=None):
    """
    Corrige respostas multimodais usando Gemini (multimodal).
    Registra log da chamada.
    Retorna string JSON com nota e justificativa.
    """
    start_time = time.time()
    error = None
    response_content = None
    status = 'success'
    model_name = "gemini-2.5-flash"
    tokens_input = None
    tokens_output = None
    output = None

    try:
        # Usar Gemini para multimodal
        llm = ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=settings.GEMINI_API_KEY,
            temperature=0.3,
        )
        
        # Preparar conteúdo multimodal
        conteudos = []
        
        # Adicionar texto base
        prompt_texto = f"""
        ENUNCIADO DA PERGUNTA:
        {enunciado}
        
        GABARITO/PADRÃO DE RESPOSTA:
        {gabarito}
        
        RESPOSTA DO ALUNO (pode conter texto e/ou elementos visuais):
        """
        conteudos.append(HumanMessage(content=prompt_texto))
        
        # Adicionar imagens da pergunta (se houver)
        if imagens_pergunta:
            for imagem_info in imagens_pergunta:
                try:
                    imagem = Image.open(imagem_info['caminho_absoluto'])
                    
                    # Converter imagem para base64
                    buffered = io.BytesIO()
                    imagem.save(buffered, format="PNG")
                    img_str = base64.b64encode(buffered.getvalue()).decode()
                    
                    # Criar mensagem com texto e imagem
                    message_content = [
                        {"type": "text", "text": f"IMAGEM DO ENUNCIADO: {imagem_info['nome']}"},
                        {"type": "image_url", "image_url": f"data:image/png;base64,{img_str}"}
                    ]
                    conteudos.append(HumanMessage(content=message_content))
                except Exception as e:
                    # Log do erro mas continua
                    print(f"Erro ao carregar imagem do enunciado: {e}")
        
        # Adicionar resposta do aluno (pode ser imagem ou texto)
        try:
            # Se resposta_aluno for string, verificar se é caminho de arquivo
            if isinstance(resposta_aluno, str):
                # Tenta abrir como imagem
                try:
                    imagem_resposta = Image.open(resposta_aluno)
                    # Converter imagem para base64
                    buffered = io.BytesIO()
                    imagem_resposta.save(buffered, format="PNG")
                    img_str = base64.b64encode(buffered.getvalue()).decode()
                    
                    message_content = [
                        {"type": "text", "text": "RESPOSTA DO ALUNO (IMAGEM):"},
                        {"type": "image_url", "image_url": f"data:image/png;base64,{img_str}"}
                    ]
                    conteudos.append(HumanMessage(content=message_content))
                except:
                    # Se não for imagem, trata como texto
                    conteudos.append(HumanMessage(content=f"RESPOSTA DO ALUNO (TEXTO):\n{resposta_aluno}"))
            else:
                # Assume que é objeto Image
                buffered = io.BytesIO()
                resposta_aluno.save(buffered, format="PNG")
                img_str = base64.b64encode(buffered.getvalue()).decode()
                
                message_content = [
                    {"type": "text", "text": "RESPOSTA DO ALUNO (IMAGEM):"},
                    {"type": "image_url", "image_url": f"data:image/png;base64,{img_str}"}
                ]
                conteudos.append(HumanMessage(content=message_content))
        except Exception as e:
            print(f"Erro ao processar resposta do aluno: {e}")
            # Em caso de erro, adiciona texto simples
            conteudos.append(HumanMessage(content=f"RESPOSTA DO ALUNO (não processada): {str(resposta_aluno)}"))
        
        # Adicionar instruções finais
        instrucoes_finais = """
        #INSTRUÇÕES FINAIS        
        - AVALIE A RESPOSTA DO ALUNO COM BASE NO GABARITO FORNECIDO. 
        - SEJA CRITERIONOSO E JUSTO.
        - FORNEÇA UMA NOTA DE 0 A 10, CONSIDERANDO A COMPLETUDE E CORREÇÃO DA RESPOSTA.
        - Justificativa deve analisar a qualidade técnica da resposta
        - Compare com o gabarito oficial
        - Identifique acertos, erros e omissões
        - Seja construtivo e educativo
        - Retorne APENAS um JSON no formato:
        {
          "nota": 0-10,
          "justificativa": "análise detalhada"
        }
        - NÃO UTILIZE NENHUMA TAG HTML
        - TRATE O ALUNO NA SEGUNDA PESSOA DO SINGULAR (VOCÊ)
        """
        conteudos.append(HumanMessage(content=instrucoes_finais))
        
        # Gerar correção
        response = llm.invoke(conteudos)
        response_content = response.content
        
        # Tentar extrair tokens de uso (se disponível)
        if hasattr(response, 'usage_metadata'):
            tokens_input = response.usage_metadata.get('input_tokens')
            tokens_output = response.usage_metadata.get('output_tokens')
        
        # Extrair JSON da resposta
        json_match = re.search(r'\{.*\}', response_content, re.DOTALL)
        if json_match:
            output = json_match.group()
            # Validar se é JSON válido
            try:
                json.loads(output)
            except json.JSONDecodeError:
                # Se não for válido, criar estrutura padrão
                output = json.dumps({
                    "nota": 0,
                    "justificativa": f"A resposta da IA não pôde ser interpretada. Conteúdo: {response_content[:200]}..."
                })
        else:
            # Se não encontrar JSON, criar um manualmente
            output = json.dumps({
                "nota": 0,
                "justificativa": f"Resposta não pôde ser processada. Conteúdo: {response_content[:200]}..."
            })
        
        return output
        
    except Exception as e:
        status = 'error'
        error = str(e)
        output = json.dumps({
            "nota": 0,
            "justificativa": f"Erro na correção multimodal: {str(e)}"
        })
        return output
    finally:
        duration = int((time.time() - start_time) * 1000)
        # Registrar log
        try:
            from mimir.models import LLMLog
            LLMLog.objects.create(
                user=user,
                prompt=f"Multimodal - enunciado: {enunciado[:200]}...",  # resumo
                response=response_content,
                model_used=model_name,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                duration_ms=duration,
                status=status,
                error_message=error,
                endpoint='corrigirRespostaMultimodal'
            )
        except Exception as log_error:
            # Não deixar o log atrapalhar a resposta
            print(f"Erro ao salvar log: {log_error}")

# Funções auxiliares (mantidas como estão)
def processar_pdf_em_lotes(file_path, fileName, max_pages_per_batch=20):
    """Processa PDF em lotes para evitar timeout"""
    textos_por_lote = []
    
    try:
        with pdfplumber.open(file_path) as pdf:
            total_paginas = len(pdf.pages)
            lotes = [pdf.pages[i:i+max_pages_per_batch] 
                    for i in range(0, total_paginas, max_pages_per_batch)]
            
            for indice_lote, lote_paginas in enumerate(lotes):
                texto_lote = f"FONTE: {fileName} - LOTE {indice_lote + 1}\n"
                
                for i, pagina in enumerate(lote_paginas, 1):
                    try:
                        texto_pagina = pagina.extract_text()
                        if texto_pagina and texto_pagina.strip():
                            texto_lote += f"--- PÁGINA {(indice_lote * max_pages_per_batch) + i} ---\n"
                            texto_lote += texto_pagina.strip() + "\n\n"
                    except Exception as e:
                        texto_lote += f"Erro na página {(indice_lote * max_pages_per_batch) + i}: {str(e)}\n"
                
                textos_por_lote.append(texto_lote)
                
    except Exception as e:
        textos_por_lote.append(f"Erro ao processar {file_path}: {str(e)}")
    
    return textos_por_lote

def extrair_texto_pdf(caminho_arquivo):
    """Extrai texto de PDF com tratamento robusto de erros"""
    try:
        texto = []
        
        with pdfplumber.open(caminho_arquivo) as pdf:
            for i, pagina in enumerate(pdf.pages, 1):
                try:
                    texto_pagina = pagina.extract_text()
                    if texto_pagina and texto_pagina.strip():
                        texto.append(f"--- PÁGINA {i} ---")
                        texto.append(texto_pagina.strip())
                        texto.append("")  # Linha em branco
                except Exception as e:
                    texto.append(f"Erro na página {i}: {str(e)}")
        
        return texto if texto else ["Nenhum texto extraído do PDF"]
        
    except ImportError:
        return ["Biblioteca pdfplumber não instalada. Execute: pip install pdfplumber"]
    except Exception as e:
        return [f"Erro na extração do PDF: {str(e)}"]

def processarRespostaIA(resposta_ia):
    """Processa o JSON retornado pela IA"""
    try:
        # Limpar e parsear o JSON        
        resposta_limpa = re.sub(r'^```json\n|\n```$', '', resposta_ia.strip())
        print(resposta_limpa)
        return json.loads(resposta_limpa)
    except Exception as e:
        print(f"Erro ao processar resposta da IA: {str(e)}")
        return []

def construirTextoPerguntaCompleto(enunciado, tipo_pergunta, pergunta_id, post_data):
    """
    Constrói o texto completo da pergunta incluindo alternativas se for múltipla escolha
    """
    tipo_pergunta = tipo_pergunta.lower() if tipo_pergunta else ''
    
    if 'múltipla' in tipo_pergunta.lower() or 'multipla' in tipo_pergunta.lower():
        alternativas = []
        prefixo = f'pergunta_{pergunta_id}'
        
        i = 1
        while True:
            alternativa_key = f'{prefixo}_alternativa_{i}'
            alternativa = post_data.get(alternativa_key, '').strip()
            
            if not alternativa:
                break
                
            alternativas.append(alternativa)
            i += 1
        
        if alternativas:
            texto_pergunta = enunciado + "\n\n"
            for j, alternativa in enumerate(alternativas, 1):
                texto_pergunta += f"{alternativa}\n"
            
            return texto_pergunta.strip()
    
    return enunciado

# Função auxiliar para processar JSON
def extrair_json_da_resposta(texto):
    """Extrai JSON de uma resposta que pode conter texto adicional"""
    try:
        # Tentar parsear diretamente
        return json.loads(texto)
    except json.JSONDecodeError:
        # Procurar por JSON no texto
        match = re.search(r'\{[\s\S]*\}', texto)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                # Tentar limpar o JSON
                json_str = match.group()
                # Remover caracteres problemáticos
                json_str = re.sub(r',\s*}', '}', json_str)
                json_str = re.sub(r',\s*]', ']', json_str)
                try:
                    return json.loads(json_str)
                except:
                    pass
        
        # Se não encontrar JSON válido, criar estrutura padrão
        return {"perguntas": [], "erro": "Não foi possível processar o JSON"}

from google import genai
from PIL import Image
from django.core.files.storage import default_storage
from django.conf import settings
import pdfplumber, json, re

def criarPromptGuiaTutor(titulo, tema, assunto, objetivos, texto_problema, fontes_info, instrucoesGuia):
        return f"""
        Com base no problema abaixo, gere um GUIA DO TUTOR detalhado seguindo EXATAMENTE a estrutura fornecida:

        # TÍTULO DO PROBLEMA: {titulo}
        TEMA: {tema}
        ASSUNTO: {assunto}
        OBJETIVOS DE APRENDIZAGEM: {', '.join(objetivos)}

        # TEXTO COMPLETO DO PROBLEMA:
        {texto_problema}

        # FONTES DE REFERÊNCIA:
        {fontes_info}

        --- ESTRUTURA DO GUIA DO TUTOR ---

        {instrucoesGuia}
        """

def regerarParte(tema, assunto, objetivos, parte_ordem, contexto_anterior, fontes, instrucoes, parte_original):
        prompt = f"""
        Você é um especialista em {tema} revisando e melhorando um problema de aprendizado.

        TEMA: {tema}
        ASSUNTO: {assunto}
        OBJETIVOS: {', '.join(objetivos)}

        FONTES DE REFERÊNCIA:
        {fontes}

        CONTEXTO ANTERIOR (Partes 1 a {parte_ordem-1}):
        {contexto_anterior}

        PARTE ORIGINAL {parte_ordem} (para referência):
        {parte_original}

        INSTRUÇÕES ESPECÍFICAS DO USUÁRIO:
        {instrucoes}

        Sua tarefa é gerar uma NOVA VERSÃO para a PARTE {parte_ordem} que:
        1. Siga rigorosamente as instruções do usuário acima
        2. Mantenha coerência total com o contexto anterior
        3. Preserve os objetivos de aprendizagem originais
        4. Integre as fontes de referência quando relevante
        5. Mantenha o mesmo nível de detalhe e complexidade
        6. Seja uma melhoria clara em relação à versão original

        Diretrizes importantes:
        - Foque em atender especificamente às instruções do usuário
        - Mantenha o fluxo narrativo natural
        - Não quebre a continuidade com as partes seguintes
        - Se as instruções pedirem mudanças específicas, implemente-as claramente

        Forneça APENAS o texto da nova parte {parte_ordem}, sem marcações, números ou comentários.
        """
        
        return prompt

def criarPromptParaParte(tema, assunto, objetivos, parte_atual, total_partes, contexto_anterior,fontes):
    total_partes = total_partes if total_partes else "N"
    return f"""
    Você é um especialista em {tema} criando um problema de aprendizado sequencial.
    
    TEMA: {tema}
    ASSUNTO: {assunto}
    OBJETIVOS: {', '.join(objetivos)}
    
    FONTES DE REFERÊNCIA:
    {fontes}

    CONTEXTO ANTERIOR:
    {contexto_anterior}
    
    Gere a PARTE {parte_atual} de {total_partes} deste problema.
    
    Esta parte deve:
    1. Desenvolver naturalmente a partir do contexto anterior
    2. Adicionar novas informações ou complicações relevantes
    3. Manter coerência com o tema e objetivos
    4. Ser autocontida mas deixar espaço para desenvolvimento futuro
    5. Incluir elementos práticos e realistas
    
    Forneça apenas o texto da parte {parte_atual}, sem marcações ou números.
    """

def chamarApiLLM(prompt):
    try:
        # Gerar conteúdo
        # Configurar API do Gemini
        client = genai.Client(api_key=settings.GEMINI_API_KEY) # Recomendado: usar settings
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt
        )             
        return response.text                
    except Exception:
        return None

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

def getQuestionsFromSource(file_path,qtPerguntas,infoExtras):
    """Gera questões a partir do conteúdo do PDF"""
    totalPerguntas = sum(qtPerguntas.values())
    textoPerguntas = "\n".join([f"- {qtPerguntas[k]} de {k}" for k in qtPerguntas])
    try:
        # Extrair texto do PDF
        completoTudo = ''
        for fp in file_path:
            conteudo_extraido = extrair_texto_pdf(fp[0])
            texto_completo = "\n".join(conteudo_extraido)
            completoTudo += f"FONTE - {fp[1]}\n" + texto_completo + "\n\n"
        
        # Configurar API do Gemini
        client = genai.Client(api_key=settings.GEMINI_API_KEY) # Recomendado: usar settings
        
        # Criar prompt
        prompt = f"""
        BASEADO NO CONTEÚDO ABAIXO DE UM DOCUMENTO PDF:

        {completoTudo}

        GERE {totalPerguntas} QUESTÕES DE PROVA SOBRE O ASSUNTO:
                
        {textoPerguntas}

        #INSTRUÇÕES FINAIS
        - GERE O GABARITO DE TODAS
        - PARA AS DICURSSIVAS, GERE O PADRÃO DE RESPOSTA ESPERADO        
        - FORMATE TODA A SAÍDA EM JSON COM A CHAVE "perguntas" E O VALOR SENDO UM ARRAY DE OBJETOS COM "tipo", "enunciado", "alternativa" E "resposta"
        - NÃO UTILIZE NENHUMA TAG HTML
        - AO GERAR AS ALTERNATIVAS, UTILIZE LETRAS PARA IDENTIFICAR CADA ALTERNATIVA
        - AS LETRAS NÃO DEVEM SER CHAVES DO JSON, APENAS O TEXTO DA ALTERNATIVA
        - AS ALTERNATIVAS SEMPRE DEVEM CONTER O SEGUINTE FORMATO: "A) texto da alternativa\n B) texto da alternativa\n C) texto da alternativa\n D) texto da alternativa\n E) texto da alternativa"
        - A CHAVE "alternativas", EM CASO DE QUESTÃO QUE AS TENHAM, NO JSON SEMPRE DEVE SER UM ARRAY E NUNCA UM OBJETO
        - O PADRÃO DE RESPOSTA E O GABARITO DE ALTERNATIVAS DEVEM FICAR NA CHAVE "resposta"
        - CONTEMPLE TODOS OS MATERIAIS PARA A GERAÇÃO DAS QUESTÕES, OU SEJA, PELO MENOS UMA QUESTÃO DE CADA TEMA SOLICITADO
        {infoExtras}
        """
        
        # Gerar conteúdo
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt
        )             
        return response.text
        
    except Exception as e:
        return f"Erro ao gerar questões: {str(e)}"

def processarRespostaIA(resposta_ia):
    print(resposta_ia)
    """Processa o JSON retornado pela IA e cria as perguntas geradas"""
    try:
        # Limpar e parsear o JSON
        resposta_limpa = re.sub(r'^```json\n|\n```$', '', resposta_ia.strip())
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
        # Para múltipla escolha, incluir as alternativas no texto
        alternativas = []
        prefixo = f'pergunta_{pergunta_id}'
        
        # Buscar todas as alternativas (alternativa_1, alternativa_2, etc.)
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
    
    # Para outros tipos, retornar apenas o enunciado
    return enunciado

def fazerCorrecaoComModelo(enunciado, gabarito, resposta_aluno):
    try:
        # Configurar API do Gemini
        client = genai.Client(api_key=settings.GEMINI_API_KEY) # Recomendado: usar settings
        
        # Criar prompt
        prompt = f"""
        FAÇA O PAPEL DE UM PROFESSOR DOUTOR NO TEMA DA PERGUNTA, DADA A SEGUINTE PERGUNTA:
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
        """
        
        # Gerar conteúdo
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt
        )             
        return response.text
        
    except Exception as e:
        return f"Erro ao gerar questões: {str(e)}"

def corrigirRespostaMultimodal(enunciado, gabarito, resposta_aluno, imagens_pergunta=None):
    """
    Função para corrigir respostas que podem conter imagens
    tanto na pergunta quanto na resposta do aluno
    """
    try:
        # Configurar API do Gemini para multimodal
        model = genai.Client(api_key=settings.GEMINI_API_KEY) # Recomendado: usar settings        
        
        conteudos = []
        
        # Adicionar prompt base
        prompt_base = f"""
        FAÇA O PAPEL DE UM PROFESSOR DOUTOR NO TEMA DA PERGUNTA, DADA A SEGUINTE PERGUNTA:

        UTILIZE O SEGUINTE PADRÃO DE RESPOSTA / GABARITO PARA A CORREÇÃO:
        {enunciado}

        PARA A CORREÇÃO DA RESPOSTA DO ALUNO ABAIXO:
        {gabarito}

        ANALISE A RESPOSTA DO ALUNO (QUE PODE SER UMA IMAGEM CONTENDO TEXTO, DIAGRAMAS, GRÁFICOS, ETC.):
        """
        conteudos.append(prompt_base)
        
        # Adicionar imagens da pergunta (se houver)
        if imagens_pergunta:
            for imagem_info in imagens_pergunta:
                try:
                    imagem = Image.open(imagem_info['caminho_absoluto'])
                    conteudos.append(f"IMAGEM DO ENUNCIADO: {imagem_info['nome']}")
                    conteudos.append(imagem)
                except Exception as e:
                    print(f"Erro ao carregar imagem do enunciado {imagem_info['nome']}: {e}")
        
        # Adicionar resposta do aluno (imagem)
        try:
            if isinstance(resposta_aluno, str):  # Se for caminho de arquivo
                imagem_resposta = Image.open(resposta_aluno)
            else:  # Se já for um objeto de imagem
                imagem_resposta = resposta_aluno
                
            conteudos.append("RESPOSTA DO ALUNO (IMAGEM):")
            conteudos.append(imagem_resposta)
        except Exception as e:
            print(f"Erro ao carregar imagem da resposta: {e}")
            return json.dumps({
                "nota": 0,
                "justificativa": f"Erro ao processar a imagem da resposta: {str(e)}"
            })
        
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
        conteudos.append(instrucoes_finais)
        
        # Gerar correção
        response = model.models.generate_content(
            model="gemini-2.0-flash",
            contents=conteudos
        ) 
        
        # Processar resposta
        print(response.text)
        return response.text
        
    except Exception as e:
        return json.dumps({
            "nota": 0,
            "justificativa": f"Erro na correção multimodal: {str(e)}"
        })
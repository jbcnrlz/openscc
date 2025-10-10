from google import genai
from django.core.files.storage import default_storage
from django.conf import settings
import pdfplumber, json, re

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
                letra = chr(64 + j)  # A, B, C, D, E...
                texto_pergunta += f"{letra}. {alternativa}\n"
            
            return texto_pergunta.strip()
    
    # Para outros tipos, retornar apenas o enunciado
    return enunciado
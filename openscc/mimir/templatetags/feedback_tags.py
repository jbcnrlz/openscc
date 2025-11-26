from django import template
import os, re
register = template.Library()

@register.filter
def split_feedback(value, separator='---GABARITO---'):
    """
    Divide o feedback em partes usando o separador
    """
    if not value:
        return []
    return value.split(separator)

@register.filter
def get_part(value, index):
    """
    Retorna uma parte específica do array
    """
    try:
        if value and index < len(value):
            return value[index].strip()
        return ''
    except (IndexError, TypeError):
        return ''

@register.filter
def has_gabarito(value):
    """
    Verifica se o feedback tem gabarito separado
    """
    if not value:
        return False
    return '---GABARITO---' in value

@register.filter
def get_item(dictionary, key):
    """Retorna o valor de um dicionário para uma chave específica"""
    return dictionary.get(key)

@register.filter
def basename(value):
    """Retorna o nome do arquivo de um path"""
    return os.path.basename(value)

@register.filter
def extrair_alternativas(texto_pergunta):
    """
    Extrai as alternativas de uma pergunta de múltipla escolha
    Formato esperado: a) texto da alternativa a\n b) texto da alternativa b\n etc.
    """
    alternativas = {}
    
    # Padrão para encontrar alternativas: letra) texto
    padrao = r'([a-e])\)\s*(.+?)(?=\n[a-e]\)|$)'
    matches = re.findall(padrao, texto_pergunta, re.IGNORECASE | re.DOTALL)
    
    for letra, texto in matches:
        alternativas[letra.upper()] = texto.strip()
    
    return alternativas

@register.filter
def multiply(value, arg):
    """Multiplica o valor pelo argumento"""
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0
    
@register.filter
def percentage(value, total):
    """Calcula a porcentagem de value em relação a total"""
    try:
        if total == 0:
            return 0
        return (float(value) / float(total)) * 100
    except (ValueError, ZeroDivisionError, TypeError):
        return 0

@register.filter
def default_zero(value):
    """Retorna 0 se o valor for None"""
    return value if value is not None else 0
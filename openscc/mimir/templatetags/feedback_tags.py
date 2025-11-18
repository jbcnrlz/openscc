from django import template
import os
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
from django import template

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
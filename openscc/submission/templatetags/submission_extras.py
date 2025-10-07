from django import template
import base64
from django.utils import timezone
from submission.models import Atividade

register = template.Library()

@register.filter(name='userRegistered')
def userRegistered(ativide,userID):
    return ativide.isUserRegitered(userID)

@register.filter(name='getStatusPaper')
def getStatusPaper(paper):
    return paper.getStatusPaper()

@register.filter(name='canSubscrive')
def canSubscrive(ativide,userID):
    return ativide.canUserRegister(userID)

@register.filter(name='base64Encode')
def base64Encode(value):    
    return base64.b64encode(value).decode('utf-8')

@register.filter(name='isPresent')
def isPresent(ativide,userID):
    return ativide.isAlreadyPresent(userID)

@register.filter
def has_conflict(atividade, user_id):
    """Verifica se há conflito de horário para o usuário"""
    if atividade.isUserRegitered(user_id):
        return False
    
    # Buscar outras atividades no mesmo horário em que o usuário está inscrito
    conflicting_activities = Atividade.objects.filter(
        data__date=atividade.data.date(),
        data__time=atividade.data.time(),
        participantes__id=user_id
    ).exclude(id=atividade.id)
    
    return conflicting_activities.exists()


@register.filter
def format_time_range(atividade):
    """Formata o horário da atividade"""
    return atividade.data.strftime("%H:%M")

@register.filter
def is_past(atividade):
    """Verifica se a atividade já passou"""
    return atividade.data < timezone.now()

@register.filter
def is_today(atividade):
    """Verifica se a atividade é hoje"""
    return atividade.data.date() == timezone.now().date()
from django import template
import base64

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
from django import template

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
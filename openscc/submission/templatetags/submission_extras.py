from django import template

register = template.Library()

@register.filter(name='userRegistered')
def userRegistered(ativide,userID):
    return ativide.isUserRegitered(userID)
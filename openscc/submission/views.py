from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.template import loader
from django.contrib.auth.models import User
import datetime, json
from django.contrib.auth import logout
from django.urls import reverse
# Create your views here.

from .forms import UserForm
from .models import *

#def login(request):
#    if request.method == 'POST':
#        user = authenticate(username=request.POST.get('txtLogin'),password=request.POST.get('txtLogin'))
#        if user is not None:
#            print('autenticou')
#        else:
#            print('deu erro')
#    template = loader.get_template("submissao/login.html")
#    return HttpResponse(template.render(request=request))

def logoutView(request):
    logout(request)
    return redirect('submission:login')

def cadUser(request):
    if request.method == "POST":
        form = UserForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('submission:login')
    else:
        form = UserForm
    return render(request,"submissao/cadUser.html", {"form" : form})

def conferencia(request,slug,data=None):
    conf = Conferencia.objects.get(slug=slug)
    currData = conf.dataEventoInicio if data is None else datetime.datetime.strptime(data,"%d%m%Y")
    diasConf = conf.getListaDias(currData)
    atvs = Atividade.objects.filter(
        conferencia=conf,
        data__year=currData.year,
        data__month=currData.month,
        data__day=currData.day
    )
    atvs.select_related('tipo').all()    
    return render(request,"submissao/conferencia.html",{"conf" : conf, "daysQt" : diasConf,'atividades' : atvs})

def inscricao(request,id):
    atv = Atividade.objects.get(pk=id)
    atv.participantes.add(request.user)
    return redirect('submission:conferencia',slug=atv.conferencia.slug)

def removerInscricao(request,idAtv):
    atv = Atividade.objects.get(pk=idAtv)
    atv.participantes.remove(request.user)
    return redirect('submission:conferencia',slug=atv.conferencia.slug)

def profile(request):
    atvs = Atividade.objects.filter(participantes__id=request.user.id).order_by('nome').select_related('conferencia')
    conferencias = getConferenciasAndAtividades(atvs)
    return render(request,"submissao/profile.html",{"conferencias":conferencias})

def getConferenciasAndAtividades(atividades):
    returnDict = {}
    for a in atividades:
        confName = a.conferencia.nome
        if confName in returnDict.keys():
            returnDict[confName].append(a)
        else:
            returnDict[confName] = [a]

    return returnDict

def conferencias(request):
    conferenciaList = Conferencia.objects.filter(submissaoClose__gte=datetime.date.today())
    return render(request,"submissao/conferencias.html",{"conferenciaList":conferenciaList})

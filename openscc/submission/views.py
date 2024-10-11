from django.http import HttpResponse
from django.shortcuts import render
from django.template import loader
from django.contrib.auth.models import User
import datetime
# Create your views here.

from .forms import UserForm
from .models import *

def login(request):
    template = loader.get_template("submissao/login.html")
    return HttpResponse(template.render(request=request))

def cadUser(request):
    if request.method == "POST":
        form = UserForm(request.POST)
        if form.is_valid():
            form.save()
    else:
        form = UserForm
    return render(request,"submissao/cadUser.html", {"form" : form})

def conferencia(request,id,data=None):
    conf = Conferencia.objects.get(pk=id)
    diasConf = conf.getListaDias()
    currData = conf.dataEventoInicio if data is None else datetime.datetime.strptime(data,"%d%m%Y")
    atvs = Atividade.objects.filter(
        conferencia=conf,
        data__year=currData.year,
        data__month=currData.month,
        data__day=currData.day
    )
    atvs.select_related('tipo').all()
    return render(request,"submissao/conferencia.html",{"conf" : conf, "daysQt" : diasConf,'atividades' : atvs})

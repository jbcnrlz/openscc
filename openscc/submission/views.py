from django.shortcuts import render, redirect
from django.contrib.auth import logout
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib import messages
# Create your views here.

from .forms import UserForm, ArtigoForm
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
            messages.success(request, 'Cadastro efetuado com sucesso!')
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

@staff_member_required
def visualizeSubscription(request):
    idsAtvs = request.GET.get('ids','').split(',')
    atvs = Atividade.objects.filter(id__in=idsAtvs)
    atvs.select_related('participantes').all() 
    return render(request,"admin/subscriptions.html",{'atividades' : atvs})

def submissaoDesc(request,slug):
    conf = Conferencia.objects.get(slug=slug)
    return render(request,"submissao/subdesc.html",{"conf" : conf})

@login_required(login_url='/login')
def submissionForm(request,slug):
    conf = Conferencia.objects.get(slug=slug)
    if request.method == "POST":
        form = ArtigoForm(request.POST,request.FILES)
        if form.is_valid():
            artigo = form.save(commit=False)
            artigo.conferenciaAtual = conf
            artigo.user = request.user
            artigo.dataEnvio = datetime.date.today()
            artigo.status = 0
            artigo.save()
            # Processar autores dinamicamente
            autores = request.POST.getlist('autores_nome')
            emails = request.POST.getlist('autores_email')
            autores_filiacao = request.POST.getlist('autores_filiacao')

            for nome, email, filiacao in zip(autores, emails, autores_filiacao):                
                autor, created = Autores.objects.get_or_create(nome=nome, email=email, filiacao=filiacao, principal=0)
                artigo.autores.add(autor)

            messages.success(request, 'Submissão efetuada com sucesso!')
            return redirect('submission:artigos')  # Redireciona após o cadastro
    else:
        form = ArtigoForm()    
    return render(request,"submissao/subform.html",{"conf" : conf, "form" : form})

def artigos(request):
    atvs = Artigo.objects.filter(user__id=request.user.id).order_by('titulo').select_related('conferenciaAtual')
    return render(request,"submissao/artigos.html",{"atvs":atvs})

def detailsPaper(request,id):
    artigo = Artigo.objects.get(pk=id)
    return render(request,"submissao/detailsPaper.html",{"artigo":artigo})
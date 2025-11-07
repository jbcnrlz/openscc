from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import logout
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse
from django.utils import timezone
import datetime

from django.contrib import messages
from django.db import transaction
# Create your views here.

from .forms import UserForm, ArtigoForm
from .models import *

import qrcode
from io import BytesIO

import datetime as dt

#def login(request):
#    if request.method == 'POST':
#        user = authenticate(username=request.POST.get('txtLogin'),password=request.POST.get('txtLogin'))
#        if user is not None:
#            print('autenticou')
#        else:
#            print('deu erro')
#    template = loader.get_template("submissao/login.html")
#    return HttpResponse(template.render(request=request))
@staff_member_required
def contabilizarPresenca(request, atvId, partId):
    atv = Atividade.objects.get(pk=atvId)
    dataConf = datetime.datetime.fromtimestamp(atv.data.timestamp())
    if dataConf > datetime.datetime.now():
        messages.error(request, 'A atividade ainda não ocorreu. Presença não pode ser contabilizada.')
    else:
        patv = ParticipanteAtividade.objects.get(atividade__id=atvId, user__id=partId)        
        try:
            patv.presenca = True
            patv.data_registro = datetime.datetime.now()
            patv.save()
            messages.success(request, 'Presença contabilizada com sucesso!')
        except:            
            messages.error(request, 'Erro ao contabilizar presença. Tente novamente.')
    return render(request, 'submissao/contabilizarPresenca.html')

def generateQRCode(request, atvId, partId):
    atv = Atividade.objects.get(pk=atvId)
    part = atv.participantes.get(pk=partId)
    url_redirecionamento = reverse('submission:presenca', args=[atvId,partId])
    url_redirecionamento = request.build_absolute_uri(url_redirecionamento)

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(url_redirecionamento)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    qr_code_image = buffer.getvalue()
    buffer.close()

    context = {
        'atividade': atv,
        'participante': part,
        'qr_code_image': qr_code_image,
        'url_redirecionamento': url_redirecionamento,
    }

    return render(request, 'submissao/qrcode.html', context)

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

def conferencia(request, slug, data=None):
    try:
        conf = Conferencia.objects.get(slug=slug)
        
        # Determinar data atual ou selecionada
        if data is None:
            currData = timezone.now().date()
            # Se a data atual não estiver no range do evento, usar a primeira data
            if currData < conf.dataEventoInicio or currData > conf.dataEventoFim:
                currData = conf.dataEventoInicio
        else:
            # Usar datetime do Python para parsing
            currData = dt.datetime.strptime(data, "%d%m%Y").date()
        
        # Gerar lista de dias do evento
        diasConf = conf.getListaDias(currData)
        
        # Buscar atividades do dia selecionado
        atvs = Atividade.objects.filter(
            conferencia=conf,
            data__date=currData
        ).select_related('tipo', 'palestrante').order_by('data')
        
        # Para cada atividade, verificar se o usuário pode se inscrever
        atividades_com_status = []
        for atividade in atvs:
            if request.user.is_authenticated:
                atividade.user_registered = atividade.isUserRegitered(request.user.id)
                atividade.can_register = atividade.canUserRegister(request.user.id)
                
                # Verificar se há conflito com outras atividades
                if atividade.user_registered:
                    atividade.has_conflict = False
                else:
                    # Buscar outras atividades no mesmo horário em que o usuário está inscrito
                    conflicting_activities = Atividade.objects.filter(
                        data__date=atividade.data.date(),
                        data__time=atividade.data.time(),
                        participantes=request.user
                    ).exclude(id=atividade.id)
                    atividade.has_conflict = conflicting_activities.exists()
            else:
                atividade.user_registered = False
                atividade.can_register = False
                atividade.has_conflict = False
            
            atividades_com_status.append(atividade)
        
        context = {
            "conf": conf,
            "daysQt": diasConf,
            "atividades": atividades_com_status,
            "selected_date": currData
        }
        
        return render(request, "submissao/conferencia.html", context)
        
    except Conferencia.DoesNotExist:
        messages.error(request, "Conferência não encontrada.")
        return redirect('submission:confList')

def inscricao(request, id):
    if not request.user.is_authenticated:
        messages.warning(request, "Você precisa estar logado para se inscrever em atividades.")
        return redirect('submission:login') + f'?next={request.path}'
    
    try:
        with transaction.atomic():
            atv = Atividade.objects.select_for_update().get(pk=id)
            
            # Verificar se o usuário já está inscrito
            if atv.isUserRegitered(request.user.id):
                messages.info(request, "Você já está inscrito nesta atividade.")
                return redirect('submission:conferencia', slug=atv.conferencia.slug)
            
            # Verificar conflito de horário
            if not atv.canUserRegister(request.user.id):
                messages.error(request, 
                    "Você já está inscrito em outra atividade no mesmo horário. "
                    "Cancelar a inscrição anterior para se inscrever nesta."
                )
                return redirect('submission:conferencia', slug=atv.conferencia.slug)
            
            # Fazer a inscrição
            atv.participantes.add(request.user)
            
            messages.success(request, f"Inscrição na atividade '{atv.nome}' realizada com sucesso!")
            
            # Redirecionar mantendo a data selecionada
            selected_date = request.GET.get('date')
            if selected_date:
                return redirect('submission:conferenciaWithDate', slug=atv.conferencia.slug, data=selected_date)
            else:
                return redirect('submission:conferencia', slug=atv.conferencia.slug)
                
    except Atividade.DoesNotExist:
        messages.error(request, "Atividade não encontrada.")
        return redirect('submission:confList')
    except Exception as e:
        messages.error(request, f"Erro ao processar inscrição: {str(e)}")
        return redirect('submission:confList')

def removerInscricao(request, idAtv):
    if not request.user.is_authenticated:
        messages.warning(request, "Você precisa estar logado para gerenciar suas inscrições.")
        return redirect('submission:login')
    
    try:
        atv = Atividade.objects.get(pk=idAtv)
        
        # Verificar se o usuário está inscrito
        if not atv.isUserRegitered(request.user.id):
            messages.info(request, "Você não está inscrito nesta atividade.")
            return redirect('submission:conferencia', slug=atv.conferencia.slug)
        
        # Remover inscrição
        atv.participantes.remove(request.user)
        
        # Remover registro da tabela de participação
        ParticipanteAtividade.objects.filter(
            atividade=atv,
            user=request.user
        ).delete()
        
        messages.success(request, f"Inscrição na atividade '{atv.nome}' cancelada com sucesso!")
        
        # Redirecionar mantendo a data selecionada
        selected_date = request.GET.get('date')
        if selected_date:
            return redirect('submission:conferenciaWithDate', slug=atv.conferencia.slug, data=selected_date)
        else:
            return redirect('submission:conferencia', slug=atv.conferencia.slug)
            
    except Atividade.DoesNotExist:
        messages.error(request, "Atividade não encontrada.")
        return redirect('submission:confList')

def profile(request):
    # Buscar atividades do usuário com relacionamentos otimizados
    atvs = Atividade.objects.filter(participantes__id=request.user.id)\
                          .order_by('data', 'nome')\
                          .select_related('conferencia')\
                          .prefetch_related('participantes')
    
    conferencias = getConferenciasAndAtividades(atvs)
    
    # Obter apenas a data atual (sem hora)
    hoje = timezone.now().date()
    
    # Calcular estatísticas usando __date para comparar apenas a parte da data
    total_atividades = atvs.count()
    atividades_hoje = atvs.filter(data__date=hoje).count()
    atividades_futuras = atvs.filter(data__date__gt=hoje).count()
    atividades_passadas = atvs.filter(data__date__lt=hoje).count()
    
    # Processar dados adicionais para cada atividade
    conferencias_processadas = {}
    for conferencia_nome, atividades in conferencias.items():
        atividades_com_status = []
        for atividade in atividades:
            # Extrair apenas a data da atividade (sem hora)
            data_atividade = atividade.data.date()
            
            # Determinar status da atividade usando apenas dates
            if data_atividade < hoje:
                status = "completed"
                status_text = "Realizada"
                status_class = "status-completed"
            elif data_atividade == hoje:
                status = "today"
                status_text = "Hoje"
                status_class = "status-today"
            else:
                status = "upcoming"
                status_text = "Em Breve"
                status_class = "status-upcoming"
            
            # Verificar se usuário já registrou presença através do modelo ParticipanteAtividade
            try:
                participante_atividade = ParticipanteAtividade.objects.get(
                    atividade=atividade, 
                    user=request.user
                )
                ja_presente = participante_atividade.presenca
                data_registro_presenca = participante_atividade.data_registro
            except ParticipanteAtividade.DoesNotExist:
                ja_presente = False
                data_registro_presenca = None
            
            # Adicionar informações à atividade
            atividade.status = status
            atividade.status_text = status_text
            atividade.status_class = status_class
            atividade.ja_presente = ja_presente
            atividade.data_registro_presenca = data_registro_presenca
            # Adicionar a data formatada para exibição
            atividade.data_display = data_atividade.strftime("%d/%m/%Y")
            
            atividades_com_status.append(atividade)
        
        conferencias_processadas[conferencia_nome] = atividades_com_status
    
    context = {
        "conferencias": conferencias_processadas,
        "usuario": request.user,
        "estatisticas": {
            "total": total_atividades,
            "hoje": atividades_hoje,
            "futuras": atividades_futuras,
            "passadas": atividades_passadas
        },
        "data_hoje": hoje.strftime("%d/%m/%Y")
    }
    
    return render(request, "submissao/profile.html", context)

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
    # Buscar conferências com datas de submissão futuras
    hoje = timezone.now().date()
    conferenciaList = Conferencia.objects.filter(submissaoClose__gte=hoje).order_by('submissaoOpen')
    
    # Calcular estatísticas e status para cada conferência
    conferencias_com_status = []
    for conferencia in conferenciaList:
        # Determinar status baseado nas datas
        if hoje < conferencia.submissaoOpen:
            status = "soon"
            status_text = "Em Breve"
            status_class = "status-soon"
        elif conferencia.submissaoOpen <= hoje <= conferencia.submissaoClose:
            status = "open"
            status_text = "Inscrições Abertas"
            status_class = "status-open"
        else:
            status = "closed"
            status_text = "Inscrições Encerradas"
            status_class = "status-closed"
        
        # Calcular dias restantes para inscrição
        if hoje <= conferencia.submissaoClose:
            dias_restantes = (conferencia.submissaoClose - hoje).days
        else:
            dias_restantes = 0
        
        # Adicionar informações de status ao objeto conferência
        conferencia.status = status
        conferencia.status_text = status_text
        conferencia.status_class = status_class
        conferencia.dias_restantes = dias_restantes
        
        conferencias_com_status.append(conferencia)
    
    # Calcular estatísticas gerais
    total_conferencias = len(conferencias_com_status)
    abertas = len([c for c in conferencias_com_status if c.status == "open"])
    em_breve = len([c for c in conferencias_com_status if c.status == "soon"])
    
    context = {
        "conferenciaList": conferencias_com_status,
        "estatisticas": {
            "total": total_conferencias,
            "abertas": abertas,
            "em_breve": em_breve,
            "hoje": hoje.strftime("%d/%m/%Y")
        }
    }
    
    return render(request, "submissao/conferencias.html", context)

@staff_member_required
def visualizeSubscription(request):
    idsAtvs = request.GET.get('ids','').split(',')
    atvs = Atividade.objects.filter(id__in=idsAtvs)
    atvs.select_related('participantes').all() 
    return render(request,"admin/subscriptions.html",{'atividades' : atvs})

def submissaoDesc(request,slug):
    conf = Conferencia.objects.get(slug=slug)
    return render(request,"submissao/subdesc.html",{"conf" : conf,"hoje" : datetime.date.today()})

@login_required(login_url='/login/')
def submissionForm(request, slug):
    conf = get_object_or_404(Conferencia, slug=slug)
    
    # Verificar se as submissões estão abertas
    hoje = timezone.now().date()
    if hoje < conf.submissaoOpen:
        messages.error(request, 
            f"As submissões para esta conferência abrem em {conf.submissaoOpen.strftime('%d/%m/%Y')}."
        )
        return redirect('submission:conferencia', slug=slug)
    
    if hoje > conf.submissaoClose:
        messages.error(request, 
            f"As submissões para esta conferência encerraram em {conf.submissaoClose.strftime('%d/%m/%Y')}."
        )
        return redirect('submission:conferencia', slug=slug)

    if request.method == "POST":
        form = ArtigoForm(request.POST, request.FILES)
        
        try:
            with transaction.atomic():
                if form.is_valid():
                    # Validar autores
                    autores_nomes = request.POST.getlist('autores_nome')
                    autores_emails = request.POST.getlist('autores_email')
                    autores_filiacoes = request.POST.getlist('autores_filiacao')
                    
                    # Verificar se há pelo menos um autor
                    if not autores_nomes or not all(autores_nomes):
                        messages.error(request, 'É necessário informar pelo menos um autor.')
                        return render(request, "submissao/subform.html", {
                            "conf": conf, 
                            "form": form,
                            "autores_data": zip(autores_nomes, autores_emails, autores_filiacoes)
                        })
                    
                    # Verificar emails duplicados
                    emails = [email.lower() for email in autores_emails if email]
                    if len(emails) != len(set(emails)):
                        messages.error(request, 'Existem e-mails duplicados na lista de autores.')
                        return render(request, "submissao/subform.html", {
                            "conf": conf, 
                            "form": form,
                            "autores_data": zip(autores_nomes, autores_emails, autores_filiacoes)
                        })
                    
                    # Salvar o artigo
                    artigo = form.save(commit=False)
                    artigo.conferenciaAtual = conf
                    artigo.user = request.user
                    artigo.dataEnvio = timezone.now().date()
                    artigo.status = 0  # Aguardando avaliação
                    artigo.save()
                    
                    # Processar autores
                    autores_criados = []
                    for nome, email, filiacao in zip(autores_nomes, autores_emails, autores_filiacoes):
                        if nome and email and filiacao:  # Apenas salvar autores válidos
                            # Verificar se é o autor principal (primeiro da lista)
                            principal = 1 if len(autores_criados) == 0 else 0
                            
                            autor, created = Autores.objects.get_or_create(
                                nome=nome.strip(),
                                email=email.strip().lower(),
                                defaults={
                                    'filiacao': filiacao.strip(),
                                    'principal': principal
                                }
                            )
                            
                            # Se o autor já existe, atualizar a filiação se necessário
                            if not created and autor.filiacao != filiacao.strip():
                                autor.filiacao = filiacao.strip()
                                autor.save()
                            
                            artigo.autores.add(autor)
                            autores_criados.append(autor)
                    
                    # Log da submissão
                    print(f"Artigo '{artigo.titulo}' submetido por {request.user.username} "
                          f"com {len(autores_criados)} autores")
                    
                    messages.success(request, 
                        f'Submissão efetuada com sucesso! Seu artigo "{artigo.titulo}" '
                        f'está agora em processo de avaliação.'
                    )
                    
                    # Enviar email de confirmação (opcional)
                    # enviar_email_confirmacao(request.user, artigo, autores_criados)
                    
                    return redirect('submission:artigos')
                
                else:
                    # Se o formulário não é válido, coletar dados dos autores para repopular
                    autores_nomes = request.POST.getlist('autores_nome')
                    autores_emails = request.POST.getlist('autores_email')
                    autores_filiacoes = request.POST.getlist('autores_filiacao')
                    
                    messages.error(request, 'Por favor, corrija os erros no formulário.')
                    
        except Exception as e:
            messages.error(request, f'Erro ao processar a submissão: {str(e)}')
            # Log do erro
            print(f"Erro na submissão: {str(e)}")
    
    else:
        form = ArtigoForm()
    
    context = {
        "conf": conf, 
        "form": form,
        "hoje": timezone.now().date(),
        "submissao_aberta": conf.submissaoOpen <= timezone.now().date() <= conf.submissaoClose
    }
    
    return render(request, "submissao/subform.html", context)

def artigos(request):
    # Buscar artigos do usuário atual com relacionamentos otimizados
    atvs = Artigo.objects.filter(user__id=request.user.id)\
                        .order_by('-dataEnvio')\
                        .select_related('conferenciaAtual')\
                        .prefetch_related('autores')
    
    # Calcular estatísticas para os cards
    total_artigos = atvs.count()
    aprovados = atvs.filter(status=1).count()
    pendentes = atvs.filter(status=0).count()
    revisao = atvs.filter(status=2).count()
    reprovados = atvs.filter(status=3).count()
    
    # Passar estatísticas para o template
    context = {
        "atvs": atvs,
        "estatisticas": {
            "total": total_artigos,
            "aprovados": aprovados,
            "pendentes": pendentes,
            "revisao": revisao,
            "reprovados": reprovados
        }
    }
    
    return render(request, "submissao/artigos.html", context)

def detailsPaper(request,id):
    artigo = Artigo.objects.get(pk=id)
    return render(request,"submissao/detailsPaper.html",{"artigo":artigo})

@login_required
def submissionStatus(request, slug):
    conf = get_object_or_404(Conferencia, slug=slug)
    hoje = timezone.now().date()
    
    # Verificar se o usuário já submeteu um artigo para esta conferência
    artigo_existente = Artigo.objects.filter(
        conferenciaAtual=conf,
        user=request.user
    ).exists()
    
    context = {
        'conf': conf,
        'hoje': hoje,
        'submissao_aberta': conf.submissaoOpen <= hoje <= conf.submissaoClose,
        'artigo_existente': artigo_existente,
        'dias_restantes': (conf.submissaoClose - hoje).days if hoje <= conf.submissaoClose else 0
    }
    
    return render(request, 'submissao/submissionStatus.html', context)
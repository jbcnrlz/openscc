import uuid
from django.template.loader import render_to_string
from weasyprint import HTML
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

from .forms import *
from .models import *
from django.http import HttpResponse
import qrcode, io
import base64
from io import BytesIO
import datetime as dt
from django.db.models import Sum, Q

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
        try:
            with transaction.atomic():
                # Atualizar presença
                patv = ParticipanteAtividade.objects.get(atividade__id=atvId, user__id=partId)        
                patv.presenca = True
                patv.data_registro = datetime.datetime.now()
                patv.save()
                
                # GERAR CERTIFICADO AUTOMATICAMENTE (apenas para participação)
                try:
                    gerarCertificadoAutomatico(atv, patv.user, request)
                    messages.success(request, 'Presença contabilizada e certificado gerado com sucesso!')
                except Exception as e:
                    messages.warning(request, f'Presença contabilizada, mas houve um erro ao gerar o certificado: {str(e)}')
                    
        except Exception as e:            
            messages.error(request, f'Erro ao contabilizar presença: {str(e)}')
    
    return render(request, 'submissao/contabilizarPresenca.html')

def gerarCertificadoAutomatico(atividade, usuario, request):
    """Gera certificado de participação automaticamente"""
    from django.utils import timezone
    import uuid
    
    # Verificar se já existe certificado para esta atividade e usuário
    certificado_existente = Certificado.objects.filter(
        atividade=atividade,
        participante=usuario,
        tipo_certificado='participacao'
    ).exists()
    
    if certificado_existente:
        return None
    
    # Buscar layout padrão da conferência
    layout_padrao = LayoutCertificado.objects.filter(
        conferencia=atividade.conferencia,
        padrao=True,
        ativo=True
    ).first()
    
    # Se não houver layout padrão, pega o primeiro ativo
    if not layout_padrao:
        layout_padrao = LayoutCertificado.objects.filter(
            conferencia=atividade.conferencia,
            ativo=True
        ).first()
    
    # Criar certificado
    certificado = Certificado(
        participante=usuario,
        atividade=atividade,
        layout=layout_padrao,
        tipo_certificado='participacao',
        data_atividade=atividade.data.date(),
        carga_horaria=layout_padrao.carga_horaria_padrao if layout_padrao else 2.00,
        emitido=True,
        publicado=True,
    )
    
    certificado.save()
    
    return certificado

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

@login_required
def meusCertificados(request):
    # Obter todos os certificados do usuário atual
    certificados = Certificado.objects.filter(
        participante=request.user,
        emitido=True
    ).select_related(
        'participante', 
        'atividade', 
        'layout',
        'atividade__conferencia',
        'atividade__tipo'
    ).order_by('-data_emissao')
    
    # Aplicar filtros
    conferencia_id = request.GET.get('conferencia')
    tipo_certificado = request.GET.get('tipo')
    ano = request.GET.get('ano')
    
    if conferencia_id:
        certificados = certificados.filter(
            Q(atividade__conferencia_id=conferencia_id) | 
            Q(layout__conferencia_id=conferencia_id)
        )
    
    if tipo_certificado:
        certificados = certificados.filter(tipo_certificado=tipo_certificado)
    
    if ano:
        certificados = certificados.filter(data_atividade__year=ano)
    
    # Agrupar certificados por conferência e calcular totais
    certificados_por_conferencia = {}
    certificados_sem_conferencia = []
    totais_por_conferencia = {}  # Para armazenar totais por conferência
    
    for certificado in certificados:
        # Tentar obter a conferência através da atividade
        if certificado.atividade and certificado.atividade.conferencia:
            conferencia = certificado.atividade.conferencia
        # Tentar obter a conferência através do layout
        elif certificado.layout and certificado.layout.conferencia:
            conferencia = certificado.layout.conferencia
        else:
            certificados_sem_conferencia.append(certificado)
            continue
            
        if conferencia.id not in certificados_por_conferencia:
            certificados_por_conferencia[conferencia.id] = {
                'conferencia': conferencia,
                'certificados': [],
                'total_horas': Decimal('0.00')
            }
        
        certificados_por_conferencia[conferencia.id]['certificados'].append(certificado)
        certificados_por_conferencia[conferencia.id]['total_horas'] += certificado.carga_horaria
    
    # Calcular estatísticas
    total_certificados = certificados.count()
    total_carga_horaria = certificados.aggregate(
        total=Sum('carga_horaria')
    )['total'] or Decimal('0.00')
    
    # Adicionar carga horária dos certificados sem conferência
    for cert in certificados_sem_conferencia:
        total_carga_horaria += cert.carga_horaria
    
    # Obter anos disponíveis para filtro
    anos_disponiveis = sorted(set(
        cert.data_atividade.year for cert in certificados
    ), reverse=True)
    
    # Obter todas as conferências disponíveis
    conf_ids = set()
    for cert in certificados:
        if cert.atividade and cert.atividade.conferencia:
            conf_ids.add(cert.atividade.conferencia.id)
        elif cert.layout and cert.layout.conferencia:
            conf_ids.add(cert.layout.conferencia.id)
    
    todas_conferencias = Conferencia.objects.filter(id__in=conf_ids)
    
    context = {
        'certificados_por_conferencia': certificados_por_conferencia.values(),
        'certificados_sem_conferencia': certificados_sem_conferencia,
        'total_certificados': total_certificados,
        'total_carga_horaria': total_carga_horaria,
        'conferencias_count': len(certificados_por_conferencia),
        'todas_conferencias': todas_conferencias,
        'tipos_certificados': Certificado.TIPO_CHOICES,
        'anos_disponiveis': anos_disponiveis,
    }
    return render(request, 'submissao/meusCertificados.html', context)

@login_required
def visualizarCertificado(request, codigo_validacao):
    certificado = get_object_or_404(Certificado, codigo_validacao=codigo_validacao)
    
    # Verificar permissões
    if not (request.user == certificado.participante or request.user.is_staff):
        return render(request, 'erro_acesso.html', {
            'mensagem': 'Você não tem permissão para visualizar este certificado.'
        })
    
    # Obter dados do certificado
    try:
        logos = certificado.get_todos_logos()
    except AttributeError:
        logos = []
    
    try:
        texto_certificado = certificado.get_texto_certificado()
    except AttributeError:
        texto_certificado = ""
    
    try:
        texto_rodape = certificado.get_rodape_certificado()
    except AttributeError:
        texto_rodape = ""
    
    try:
        assinaturas = certificado.get_assinaturas()
    except AttributeError:
        assinaturas = []
    
    try:
        logo_evento = certificado.get_logo_evento()
    except AttributeError:
        logo_evento = None
    
    # Gerar QR Code
    qr_code_data = None
    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        
        # Usar código de validação
        qr_data = str(certificado.codigo_validacao)
        
        qr.add_data(qr_data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Converter para base64
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        qr_code_data = base64.b64encode(buffered.getvalue()).decode()
    except Exception as e:
        print(f"Erro ao gerar QR Code: {e}")
        qr_code_data = None
    
    context = {
        'certificado': certificado,
        'texto_certificado': texto_certificado,
        'texto_rodape': texto_rodape,
        'assinaturas': assinaturas,
        'logos': logos,
        'logo_evento': logo_evento,
        'qr_code': qr_code_data,
        # Adicionando métodos específicos
        'data_extenso': certificado.get_data_extenso(datetime.datetime.now()),
        'cidade_evento': certificado.get_cidade_evento(),
    }
    
    return render(request, 'submissao/visualizarCertificado.html', context)

def validarCertificado(request, codigo_validacao):
    """Página pública para validação de certificado"""
    certificado = get_object_or_404(
        Certificado.objects.select_related(
            'atividade',
            'atividade__conferencia',
            'participante'
        ),
        codigo_validacao=codigo_validacao
    )
    
    # Obter informações de validação
    assinaturas = certificado.get_assinaturas_ordenadas()
    logos = certificado.get_logos_ordenados()
    
    context = {
        'certificado': certificado,
        'valido': certificado.emitido and certificado.publicado,
        'assinaturas': assinaturas,
        'logos': logos,
        'atividade_tipo': certificado.atividade.tipo if certificado.atividade else None,
    }
    
    return render(request, 'submissao/validarCertificado.html', context)

@staff_member_required
def relatorioCertificados(request, conferencia_slug=None):
    """Relatório de certificados emitidos"""
    certificados = Certificado.objects.all().select_related(
        'participante', 'atividade', 'atividade__conferencia', 'tipo_atividade'
    ).prefetch_related('assinaturas', 'logos').order_by('-data_emissao')
    
    if conferencia_slug:
        certificados = certificados.filter(atividade__conferencia__slug=conferencia_slug)
    
    # Agrupar por tipo de atividade
    por_tipo_atividade = {}
    for cert in certificados:
        tipo_nome = cert.tipo_atividade.nome if cert.tipo_atividade else "Sem tipo"
        if tipo_nome not in por_tipo_atividade:
            por_tipo_atividade[tipo_nome] = []
        por_tipo_atividade[tipo_nome].append(cert)
    
    # Estatísticas
    total = certificados.count()
    hoje = timezone.now().date()
    emitidos_hoje = certificados.filter(data_emissao__date=hoje).count()
    total_impressoes = sum(cert.impressoes for cert in certificados)
    
    context = {
        'certificados': certificados,
        'por_tipo_atividade': por_tipo_atividade,
        'estatisticas': {
            'total': total,
            'emitidos_hoje': emitidos_hoje,
            'total_impressoes': total_impressoes,
        },
        'conferencia_slug': conferencia_slug,
    }
    
    return render(request, 'submissao/relatorioCertificados.html', context)

@staff_member_required
def gerenciarLayoutsCertificado(request, conferencia_id):
    """Gerencia layouts de certificado para uma conferência"""
    conferencia = get_object_or_404(Conferencia, id=conferencia_id)
    layouts = LayoutCertificado.objects.filter(conferencia=conferencia)
    
    if request.method == 'POST':
        if 'criar_layout' in request.POST:
            layout = LayoutCertificado.objects.create(
                nome=request.POST.get('nome'),
                conferencia=conferencia,
                cor_fundo=request.POST.get('cor_fundo', '#FFFFFF'),
                cor_texto_titulo=request.POST.get('cor_texto_titulo', '#000000'),
                texto_cabecalho=request.POST.get('texto_cabecalho', 'Certificamos que')
            )
            messages.success(request, 'Layout criado com sucesso!')
            return redirect('submission:editarLayoutCertificado', layout_id=layout.id)
    
    context = {
        'conferencia': conferencia,
        'layouts': layouts,
    }
    
    return render(request, 'submissao/gerenciarLayouts.html', context)

def gerarPdfCertificado(request, codigo):
    """Gera PDF do certificado"""
    certificado = get_object_or_404(Certificado, codigo_validacao=codigo)
    
    # Verificar permissões
    if not (request.user == certificado.participante or request.user.is_staff):
        return HttpResponse("Não autorizado", status=403)
    
    # Renderizar template HTML
    html_string = render_to_string('certificado_pdf.html', {
        'certificado': certificado,
        'request': request,
    })
    
    # Criar PDF
    html = HTML(string=html_string, base_url=request.build_absolute_uri())
    pdf_file = html.write_pdf()
    
    # Registrar impressão
    certificado.registrar_impressao()
    
    # Retornar PDF
    response = HttpResponse(pdf_file, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="certificado_{certificado.codigo_validacao}.pdf"'
    return response

def validarCertificado(request, codigo_validacao):
    """View para validação pública de certificados"""
    try:
        certificado = get_object_or_404(
            Certificado, 
            codigo_validacao=codigo_validacao,
            publicado=True  # Apenas certificados públicos
        )
        
        context = {
            'certificado': certificado,
            'valido': True,
            'mensagem': 'Certificado válido!',
        }
        
    except Exception as e:
        context = {
            'certificado': None,
            'valido': False,
            'mensagem': f'Certificado não encontrado ou inválido. Erro: {str(e)}',
            'codigo': codigo_validacao,
        }
    
    return render(request, 'submissao/validarCertificado.html', context)
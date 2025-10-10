import tempfile, os, json, re
from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from .models import *
from .forms import FontesForm, GeracaoPerguntasForm, PerguntaForm, ProvaForm, TemaForm
from django.contrib import messages
from commons.services import getQuestionsFromSource, processarRespostaIA, construirTextoPerguntaCompleto
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.template.loader import render_to_string
from weasyprint import HTML

@csrf_exempt
@require_POST
@login_required(login_url='/login')
def deleteFile(request):
    try:
        file_id = request.POST.get('file_id')
        file = Fontes.objects.get(id=file_id)
        file_url = file.fonte.url
        if not file_url:
            return JsonResponse({
                'status': 'error',
                'message': 'URL do arquivo não fornecida'
            }, status=400)
        
        # Extrai o caminho relativo do arquivo
        file_path = os.path.join(settings.MEDIA_ROOT, os.path.sep.join(file_url.split('/')[1:]))
        
        # Verifica se o arquivo existe
        if not os.path.exists(file_path):
            return JsonResponse({
                'status': 'error',
                'message': 'Arquivo não encontrado'
            }, status=404)
        
        # Remove o arquivo do sistema de arquivos
        os.remove(file_path)
        
        # Remove a entrada do banco de dados, se aplicável
        file.delete()
        
        return JsonResponse({
            'status': 'success',
            'message': 'Arquivo excluído com sucesso'
        })
    
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'Erro ao excluir o arquivo: {str(e)}'
        }, status=500)

@csrf_exempt
@require_POST
@login_required(login_url='/login')
def uploadFile(request):
    try:
        # Verifica se há arquivo na requisição
        if 'file' not in request.FILES:
            return JsonResponse({
                'status': 'error',
                'message': 'Nenhum arquivo enviado'
            }, status=400)
        
        # Obtém o arquivo
        uploaded_file = request.FILES['file']
        
        # Validações básicas
        if uploaded_file.size == 0:
            return JsonResponse({
                'status': 'error',
                'message': 'Arquivo vazio'
            }, status=400)
        
        # Define o tamanho máximo do arquivo (5MB)
        MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
        if uploaded_file.size > MAX_FILE_SIZE:
            return JsonResponse({
                'status': 'error',
                'message': f'Arquivo muito grande. Tamanho máximo: {MAX_FILE_SIZE//1024//1024}MB'
            }, status=400)
        
        # Define tipos de arquivo permitidos (opcional)
        ALLOWED_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.pdf', '.txt', '.doc', '.docx']
        file_extension = os.path.splitext(uploaded_file.name)[1].lower()
        
        if file_extension not in ALLOWED_EXTENSIONS:
            return JsonResponse({
                'status': 'error',
                'message': f'Tipo de arquivo não permitido. Tipos permitidos: {", ".join(ALLOWED_EXTENSIONS)}'
            }, status=400)
        
        # Define o caminho para salvar o arquivo
        # Você pode personalizar essa lógica conforme sua necessidade
        upload_path = os.path.join('fontes', uploaded_file.name)
        
        # Salva o arquivo
        path = default_storage.save(upload_path, ContentFile(uploaded_file.read()))
        
        # Obtém a URL do arquivo salvo
        file_url = default_storage.url(path)
        file = Fontes(fonte=file_url,user=request.user)
        file.save()
        # Retorna sucesso
        return JsonResponse({
            'status': 'success',
            'message': 'Arquivo enviado com sucesso',
            'file_name': uploaded_file.name,
            'file_size': uploaded_file.size,
            'file_url': file_url,
            'file_path': path,
            'file_id': file.id
        })
        
    except Exception as e:
        # Log do erro (opcional)
        # import logging
        # logger = logging.getLogger(__name__)
        # logger.error(f'Erro no upload: {str(e)}')
        
        return JsonResponse({
            'status': 'error',
            'message': f'Erro interno no servidor: {str(e)}'
        }, status=500)

@login_required(login_url='/login')
def home(request):
    mensagem = ""
    form = FontesForm()
    tiposDePergunta = TiposDePergunta.objects.all()    
    return render(request, "mimir/home.html", {"resposta": mensagem, "form": form, "tiposDePergunta": tiposDePergunta})

@csrf_exempt
@require_POST
@login_required(login_url='/login')
def saveQuestion(request):
    data = json.loads(request.body.decode('utf-8'))
    perguntaData = json.loads(data['pergunta'])    
    tpeg = TiposDePergunta.objects.get(descricao=perguntaData['tipo'])
    ass = Assunto.objects.get(id=int(data['assunto']))

    alternativasText = '' if 'alternativas' not in perguntaData.keys() else '\n'.join(perguntaData['alternativas'])
    peg = Pergunta(
        assunto=ass, 
        pergunta=perguntaData['enunciado'] + '\n' + alternativasText,
        gabarito=perguntaData['resposta'],
        tipoDePergunta=tpeg
    )
    peg.save()
    return JsonResponse({
        'status': 'success',
        'message': 'Pergunta salva com sucesso!',              
    })

@csrf_exempt
@login_required(login_url='/login')
def generateQuestions(request):
    if request.method == "GET":
        try:
            # Extrai os dados do formulário
            qtd_perguntas = {}
            contExtra = ''
            for key, value in request.GET.items():
                if key.startswith('qtd_'):
                    tipo_id = key.split('_')[1]
                    try:
                        qtd = int(value)
                        if qtd > 0:
                            qtd_perguntas[tipo_id] = qtd
                    except ValueError:
                        continue
                elif key.startswith('extra_'):
                    if value != 'None':
                        contExtra += value
            
            # Verifica se alguma quantidade foi especificada
            fontesURL = request.GET.getlist('urlFonte[]')
            if not fontesURL:
                return JsonResponse({
                    'status': 'erro',
                    'message': 'Nenhuma fonte selecionada'
                })            
            if not qtd_perguntas:
                return JsonResponse({
                    'status': 'erro',
                    'message': f"Ocorreu um erro ao gerar as perguntas: {str(e)}"
                })

            fontes = []
            for ft in fontesURL:
                fonte = os.path.join(settings.MEDIA_ROOT,os.path.sep.join(ft.split('/')[1:]))
                fontes.append(fonte)
            
            # Gera as perguntas usando o serviço
            perguntas = getQuestionsFromSource(fontes, qtd_perguntas, contExtra)
            
            if not perguntas:
                return JsonResponse({
                    'status': 'erro',
                    'message': f"Ocorreu um erro ao gerar as perguntas: {str(e)}"
                })
            
            areas = Assunto.objects.filter(user=request.user)
            if not areas.exists():
                return JsonResponse({
                    'status': 'erro',
                    'message': 'Nenhuma área de assunto encontrada para o usuário.'
                })
            
            assuntos = {str(area.id): area for area in areas}
            return JsonResponse({
                'status': 'success',
                'message': 'Arquivo enviado com sucesso',
                'perguntas': perguntas,
                'assuntos': {k: v.nome for k, v in assuntos.items()}
            })
        
        except Exception as e:
            return JsonResponse({
                'status': 'erro',
                'message': f"Ocorreu um erro ao gerar as perguntas: {str(e)}"
            })

@login_required(login_url='/login')
def dashboardProfessor(request):
    return render(request, "mimir/dashboardProfessor.html")

@login_required(login_url='/login')
def visualizarFontes(request):
    sources = Fontes.objects.filter(user=request.user)
    return render(request, "mimir/listarFontes.html", {"sources": sources})

@login_required(login_url='/login')
def addFonte(request):
    form = None
    if request.method == 'POST':
        form = FontesForm(request.POST, request.FILES)
        if form.is_valid():
            # Cria o objeto mas não salva ainda
            fonte = form.save(commit=False)
            # Associa o usuário logado
            fonte.user = request.user
            fonte.save()
            
            messages.success(request, 'Fonte adicionada com sucesso!')
            return redirect('mimir:visualizarFontes')  # Redireciona para a lista
        else:
            messages.error(request, 'Por favor, corrija os erros abaixo.')
    else:
        form = FontesForm()
    
    
    return render(request, "mimir/cadastrarFonte.html", {"source" : None,"form": form})

@login_required(login_url='/login')
def updateFonte(request, fonte_id):
    try:
        fonte = Fontes.objects.get(id=fonte_id, user=request.user)
    except Fontes.DoesNotExist:
        messages.error(request, 'Fonte não encontrada ou você não tem permissão para editá-la.')
        return redirect('mimir:visualizarFontes')
    
    if request.method == 'POST':
        form = FontesForm(request.POST, request.FILES, instance=fonte)
        if form.is_valid():
            form.save()
            messages.success(request, 'Fonte atualizada com sucesso!')
            return redirect('mimir:visualizarFontes')
        else:
            messages.error(request, 'Por favor, corrija os erros abaixo.')
    else:
        form = FontesForm(instance=fonte)
    
    return render(request, "mimir/cadastrarFonte.html", {"source": fonte, "form": form})

@login_required(login_url='/login')
def deletarFonte(request, fonte_id):
    # Obtém a fonte ou retorna 404
    fonte = get_object_or_404(Fontes, id=fonte_id)
    
    # Verifica se o usuário é o dono ou tem permissão
    if fonte.user != request.user and not request.user.is_superuser:
        messages.error(request, 'Você não tem permissão para excluir esta fonte.')
        return redirect('mimir:visualizarFontes')
    
    if request.method == 'POST':
        # Confirma a exclusão
        nome_fonte = fonte.nome
        fonte.delete()
        messages.success(request, f'Fonte "{nome_fonte}" excluída com sucesso!')
        return redirect('mimir:visualizarFontes')
    
    # Se for GET, mostra página de confirmação
    context = {
        'fonte': fonte,
        'titulo': f'Excluir Fonte: {fonte.nome}'
    }
    return render(request, 'mimir/deletarFonte.html', context)

@login_required(login_url='/login')
def listarPerguntas(request):
    perguntas = Pergunta.objects.all()
    return render(request, "mimir/listarPerguntas.html", {"perguntas": perguntas})

@csrf_exempt
@login_required(login_url='/login')
def gerarPerguntas(request):
    if request.method == 'POST':
        form = GeracaoPerguntasForm(request.user, request.POST)
        print("POST data:", request.POST)
        if form.is_valid():
            # Coletar dados do formulário
            fontes_selecionadas = form.cleaned_data['fontes_selecionadas']

            fontesPaths = []
            for ft in fontes_selecionadas:
                fontesPaths.append([ft.fonte.path,ft.nome])

            assunto = form.cleaned_data['assunto']
            prompt_personalizado = form.cleaned_data['prompt_personalizado']
            nivel_dificuldade = form.cleaned_data['nivel_dificuldade']
            contExtra = prompt_personalizado + '\n- AS QUESTÕES DEVEM SER DE NÍVEL ' + nivel_dificuldade.upper() + ' SEGUNDO A TAXONOMIA DE BLOOM\n'
            
            # Coletar quantidades por tipo
            quantidades = {}
            tipos = TiposDePergunta.objects.all()
            for tipo in tipos:
                quantidade = int(request.POST[f'tipo_{tipo.id}'])
                if quantidade and quantidade > 0:
                    quantidades[str(tipo.id)] = quantidade
                    contExtra += f'- {quantidade} QUESTÕES DO TIPO {tipo.descricao}\n'
                    if tipo.textoParaLLM is not None:
                        contExtra += tipo.textoParaLLM + '\n'
            
            if not any(quantidades.values()):
                messages.error(request, 'Selecione pelo menos uma quantidade de perguntas.')
                return render(request, 'mimir/gerarPerguntas.html', {'form': form})
            
            if not fontes_selecionadas:
                messages.error(request, 'Selecione pelo menos uma fonte.')
                return render(request, 'mimir/gerarPerguntas.html', {'form': form})
            
            iaResposta = processarRespostaIA(getQuestionsFromSource(fontesPaths, quantidades, contExtra))
            context = {
                'perguntas': iaResposta['perguntas'] if 'perguntas' in iaResposta else [],
                'assunto': assunto
            }
            return render(request, 'mimir/perguntasGeradas.html', context)
    
    else:
        form = GeracaoPerguntasForm(request.user)
    
    context = {
        'form': form,
        'tipos_pergunta': TiposDePergunta.objects.all(),
        'titulo': 'Gerar Perguntas com IA'
    }
    return render(request, 'mimir/gerarPerguntas.html', context)


@login_required(login_url='/login')
def salvarPerguntasForm(request):
    if request.method == 'POST':
        perguntas_selecionadas_ids = request.POST.getlist('perguntas_selecionadas')
        
        if not perguntas_selecionadas_ids:
            messages.error(request, 'Nenhuma pergunta foi selecionada para salvar.')
            return redirect(request.META.get('HTTP_REFERER', 'minhas_perguntas'))
        
        perguntas_salvas_count = 0
        perguntas_com_erro = []
        
        # Processar cada pergunta selecionada
        for pergunta_id in perguntas_selecionadas_ids:
            try:
                # Extrair dados específicos desta pergunta do POST
                prefixo = f'pergunta_{pergunta_id}'
                
                enunciado = request.POST.get(f'{prefixo}_enunciado', '').strip()
                resposta = request.POST.get(f'{prefixo}_resposta', '').strip()
                assunto_id = request.POST.get(f'{prefixo}_assunto')
                tipo_pergunta_nome = request.POST.get(f'{prefixo}_tipo_pergunta', '')
                
                # Validar campos obrigatórios
                if not all([enunciado, resposta, assunto_id]):
                    perguntas_com_erro.append(f"Pergunta {pergunta_id}: Campos obrigatórios faltando")
                    continue
                
                # Obter objetos relacionados
                assunto = get_object_or_404(Assunto, id=assunto_id, user=request.user)
                tipo_pergunta = get_object_or_404(TiposDePergunta, descricao=tipo_pergunta_nome)
                
                # Extrair alternativas se for múltipla escolha
                pergunta_texto_completo = construirTextoPerguntaCompleto(
                    enunciado, 
                    tipo_pergunta_nome, 
                    pergunta_id, 
                    request.POST
                )
                
                # Criar a pergunta no banco de dados
                pergunta = Pergunta.objects.create(
                    assunto=assunto,
                    pergunta=pergunta_texto_completo,
                    gabarito=resposta,
                    tipoDePergunta=tipo_pergunta
                )
                
                perguntas_salvas_count += 1
                
            except Exception as e:
                perguntas_com_erro.append(f"Pergunta {pergunta_id}: {str(e)}")
                continue
        
        # Feedback para o usuário
        if perguntas_salvas_count > 0:
            messages.success(request, f'✅ {perguntas_salvas_count} pergunta(s) salva(s) com sucesso!')
        
        if perguntas_com_erro:
            messages.warning(request, f'{len(perguntas_com_erro)} pergunta(s) não puderam ser salvas.')
            # Log detalhado dos erros (opcional)
            for erro in perguntas_com_erro[:3]:  # Mostrar apenas os 3 primeiros erros
                messages.info(request, erro)
        
        return redirect('mimir:visualizarPerguntas')

@login_required(login_url='/login')
def visualizarPerguntasFonte(request, pID):
    pergunta = get_object_or_404(Pergunta, id=pID)    

    total_perguntas_assunto = Pergunta.objects.filter(
        assunto=pergunta.assunto,
    ).count()
    
    # Perguntas do mesmo tipo (opcional)
    perguntas_mesmo_tipo = Pergunta.objects.filter(
        tipoDePergunta=pergunta.tipoDePergunta,
        assunto=pergunta.assunto
    ).exclude(id=pergunta.id)[:5]  # Limita a 5 resultados
    return render(request, "mimir/detalhesPergunta.html", {
        "pergunta": pergunta,
        "total_perguntas_assunto" : total_perguntas_assunto,
        "perguntas_mesmo_tipo" : perguntas_mesmo_tipo
    })

@login_required(login_url='/login')
def editarPergunta(request, pID):
    pergunta = get_object_or_404(Pergunta, id=pID)
    
    if request.method == 'POST':
        form = PerguntaForm(request.user, request.POST, request.FILES, instance=pergunta)
        if form.is_valid():
            try:
                pergunta = form.save()
                
                # Processar novas imagens
                novas_imagens = request.FILES.getlist('imagens')
                for imagem in novas_imagens:
                    # Validar o tipo e tamanho da imagem
                    if imagem.content_type not in ['image/jpeg', 'image/png', 'image/gif']:
                        messages.error(request, f'Arquivo {imagem.name} não é uma imagem válida.')
                        continue
                    
                    if imagem.size > 5 * 1024 * 1024:  # 5MB
                        messages.error(request, f'Imagem {imagem.name} é muito grande (máximo 5MB).')
                        continue
                    
                    ImagemPergunta.objects.create(pergunta=pergunta, imagem=imagem)
                
                # DEBUG: Verificar o que está vindo no POST
                print("POST data:", dict(request.POST))
                print("Imagens removidas raw:", request.POST.getlist('imagens_removidas'))
                
                # Processar imagens removidas - CORREÇÃO AQUI
                imagens_removidas_ids = []
                for key, value in request.POST.items():
                    if key == 'imagens_removidas':
                        try:
                            # Tentar converter para inteiro
                            img_id = int(value)
                            imagens_removidas_ids.append(img_id)
                        except (ValueError, TypeError):
                            print(f"Valor inválido para imagem removida: {value}")
                            continue
                
                print("Imagens removidas processadas:", imagens_removidas_ids)
                
                if imagens_removidas_ids:
                    try:
                        # Filtrar apenas imagens que pertencem a esta pergunta
                        imagens_para_remover = ImagemPergunta.objects.filter(
                            id__in=imagens_removidas_ids, 
                            pergunta=pergunta
                        )
                        count_removidas = imagens_para_remover.count()
                        imagens_para_remover.delete()
                        
                        if count_removidas > 0:
                            messages.success(request, f'{count_removidas} imagem(ns) removida(s) com sucesso.')
                            
                    except Exception as e:
                        messages.error(request, f'Erro ao remover imagens: {str(e)}')
                        print(f"Erro ao remover imagens: {e}")
                
                messages.success(request, 'Pergunta atualizada com sucesso!')
                
                # Redirecionamento conforme o botão clicado
                if 'salvar_e_ver' in request.POST:
                    return redirect('mimir:visualizarPergunta', pergunta.id)
                elif 'salvar_e_continuar' in request.POST:
                    return redirect('mimir:editarPergunta', pergunta.id)
                else:
                    return redirect('mimir:visualizarPerguntas')
                    
            except Exception as e:
                messages.error(request, f'Erro ao salvar pergunta: {str(e)}')
                print(f"Erro detalhado: {e}")
        else:
            messages.error(request, 'Por favor, corrija os erros no formulário.')
            print(f"Erros do formulário: {form.errors}")
    else:
        form = PerguntaForm(request.user, instance=pergunta)

    return render(request, 'mimir/editarPergunta.html', {
        'form': form,
        'pergunta': pergunta,
        'titulo': f'Editar Pergunta #{pergunta.id}'
    })

@login_required(login_url='/login')
def deletarPergunta(request, pID):
    """
    View para deletar uma pergunta
    """
    # Obter a pergunta ou retornar 404
    pergunta = get_object_or_404(
        Pergunta, 
        id=pID
    )
    
    if request.method == 'POST':
        try:
            # Salvar informações para a mensagem de confirmação
            assunto_nome = pergunta.assunto.nome
            pergunta_id_backup = pergunta.id
            
            # Deletar a pergunta
            pergunta.delete()
            
            messages.success(request, f'✅ Pergunta #{pergunta_id_backup} do assunto "{assunto_nome}" foi excluída com sucesso!')
            
            # Redirecionar conforme a origem
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': f'Pergunta excluída com sucesso!',
                    'redirect_url': reverse('mimir:visualizarPerguntas')
                })
            else:
                return redirect('mimir:visualizarPerguntas')
                
        except Exception as e:
            error_message = f'❌ Erro ao excluir a pergunta: {str(e)}'
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'message': error_message
                }, status=400)
            else:
                messages.error(request, error_message)
                return redirect('mimir:visualizarPergunta', pID=pergunta.id)    
            
@login_required(login_url='/login')
def criarProva(request):
    if not request.user.isProfessor():
        messages.error(request, "Apenas professores podem criar provas.")
        return redirect('mimir:home')
    
    if request.method == 'POST':
        form = ProvaForm(request.POST)
        if form.is_valid():
            prova = form.save(commit=False)
            prova.user = request.user
            prova.save()
            
            # Se for uma requisição AJAX para criação rápida
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'prova_id': prova.id,
                    'prova_titulo': prova.titulo
                })
            
            messages.success(request, f"Prova '{prova.titulo}' criada com sucesso!")
            return redirect('mimir:editarProva', prova_id=prova.id)
    else:
        form = ProvaForm()
    
    # Filtra assuntos do usuário atual
    form.fields['assunto'].queryset = Assunto.objects.filter(user=request.user)
    
    context = {
        'form': form,
        'tiposPergunta': TiposDePergunta.objects.all()
    }
    return render(request, 'mimir/criarProva.html', context)

@login_required(login_url='/login')
def editarProva(request, prova_id):
    prova = get_object_or_404(Prova, id=prova_id, user=request.user)
    
    if request.method == 'POST':
        # Adicionar nova pergunta
        if 'adicionar_pergunta' in request.POST:
            pergunta_form = PerguntaForm(request.user,request.POST)
            if pergunta_form.is_valid():
                pergunta = pergunta_form.save(commit=False)
                pergunta.assunto = prova.assunto
                pergunta.user = request.user
                pergunta.save()
                prova.perguntas.add(pergunta)
                messages.success(request, "Pergunta adicionada com sucesso!")
                return redirect('editar_prova', prova_id=prova.id)
        
        # Editar dados da prova
        elif 'editar_prova' in request.POST:
            form = ProvaForm(request.POST, instance=prova)
            if form.is_valid():
                form.save()
                messages.success(request, "Prova atualizada com sucesso!")
                return redirect('mimir:editarProva', prova_id=prova.id)
    
    else:
        form = ProvaForm(instance=prova)
        pergunta_form = PerguntaForm(request.user)
    
    # Filtra tipos de pergunta disponíveis
    pergunta_form.fields['tipoDePergunta'].queryset = TiposDePergunta.objects.all()
    
    context = {
        'prova': prova,
        'form': form,
        'pergunta_form': pergunta_form,
        'perguntas_prova': prova.perguntas.all(),
        'perguntas_disponiveis': Pergunta.objects.filter(assunto=prova.assunto).exclude(prova=prova)
    }
    return render(request, 'mimir/editarProva.html', context)

@login_required(login_url='/login')
def adicionarPerguntaExistente(request, prova_id):
    if request.method == 'POST':
        prova = get_object_or_404(Prova, id=prova_id, user=request.user)
        pergunta_id = request.POST.get('pergunta_id')
        
        try:
            pergunta = Pergunta.objects.get(id=pergunta_id, assunto=prova.assunto)
            prova.perguntas.add(pergunta)
            messages.success(request, "Pergunta adicionada à prova!")
        except Pergunta.DoesNotExist:
            messages.error(request, "Pergunta não encontrada.")
    
    return redirect('mimir:editarProva', prova_id=prova_id)

@login_required
def removerPerguntaProva(request, prova_id, pergunta_id):
    prova = get_object_or_404(Prova, id=prova_id, user=request.user)
    pergunta = get_object_or_404(Pergunta, id=pergunta_id)
    
    prova.perguntas.remove(pergunta)
    messages.success(request, "Pergunta removida da prova!")
    
    return redirect('mimir:editarProva', prova_id=prova_id)

@login_required(login_url='/login')
def listarProvas(request):
    provas = Prova.objects.filter(user=request.user).order_by('-dataCriacao')
    return render(request, 'mimir/listarProvas.html', {'provas': provas})

@login_required(login_url='/login')
def imprimirProva(request, prova_id):
    prova = get_object_or_404(Prova, id=prova_id)
    perguntas = prova.perguntas.all().prefetch_related('imagens')
    
    # Calcular totais para o template
    total_imagens = sum(pergunta.imagens.count() for pergunta in perguntas)
    tem_imagens = total_imagens > 0
    
    context = {
        'prova': prova,
        'perguntas': perguntas,
        'total_imagens': total_imagens,
        'tem_imagens': tem_imagens,
    }
    
    return render(request, 'mimir/imprimirProva.html', context)

@login_required(login_url='/login')
def imprimirFolhaResposta(request, prova_id):
    prova = get_object_or_404(Prova, id=prova_id, user=request.user)
    
    context = {
        'prova': prova,
        'perguntas': prova.perguntas.all().order_by('id'),
        'quantidade_linhas': 21  # Número de linhas por resposta
    }
    
    # Verifica se é para gerar PDF
    if request.GET.get('pdf'):
        return gerarPdfProva(request, context, 'folha_resposta')
    
    return render(request, 'mimir/imprimirFolhaResposta.html', context)

@login_required(login_url='/login')
def imprimirGabarito(request, prova_id):
    prova = get_object_or_404(Prova, id=prova_id, user=request.user)
    
    context = {
        'prova': prova,
        'perguntas': prova.perguntas.all().order_by('id')
    }
    
    # Verifica se é para gerar PDF
    if request.GET.get('pdf'):
        return gerarPdfProva(request, context, 'gabarito')
    
    return render(request, 'mimir/imprimirGabarito.html', context)

def gerarPdfProva(request, context, tipo):
    """Gera PDF para prova, folha de resposta ou gabarito"""
    if tipo == 'prova':
        template = 'mimir/imprimirProva.html'
        filename = f'prova_{context["prova"].id}.pdf'
    elif tipo == 'folha_resposta':
        template = 'mimir/imprimirFolhaResposta.html'
        filename = f'folha_resposta_{context["prova"].id}.pdf'
    else:  # gabarito
        template = 'mimir/imprimirGabarito.html'
        filename = f'gabarito_{context["prova"].id}.pdf'
    
    # Renderiza o HTML
    html_string = render_to_string(template, context)
    
    # Configurações para PDF
    html = HTML(string=html_string, base_url=request.build_absolute_uri())
    
    # Gera PDF
    pdf_file = html.write_pdf()
    
    # Cria resposta
    response = HttpResponse(pdf_file, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    
    return response

@login_required(login_url='/login')
def opcoesImpressao(request, prova_id):
    prova = get_object_or_404(Prova, id=prova_id, user=request.user)
    return render(request, 'mimir/opcoesImpressao.html', {'prova': prova})


@login_required
def temaCreate(request):
    if request.method == 'POST':
        form = TemaForm(request.POST)
        if form.is_valid():
            tema = form.save(commit=False)
            # Define o usuário logado como o usuário do tema
            tema.usuario = request.user
            # Agora salva no banco de dados
            tema.save()
            messages.success(request, 'Tema criado com sucesso!')
            return redirect('mimir:listarTemas')
    else:
        form = TemaForm()
    
    return render(request, 'mimir/temaForm.html', {'form': form})

@login_required
def temaUpdate(request, pk):
    tema = get_object_or_404(Tema, pk=pk)
    
    if request.method == 'POST':
        form = TemaForm(request.POST, instance=tema)
        if form.is_valid():
            form.save()
            messages.success(request, 'Tema atualizado com sucesso!')
            return redirect('mimir:listarTemas')
    else:
        form = TemaForm(instance=tema)
    
    return render(request, 'mimir/temaForm.html', {'form': form})

@login_required
def temaDelete(request, pk):
    tema = get_object_or_404(Tema, pk=pk)
    
    if request.method == 'POST':
        tema.delete()
        messages.success(request, 'Tema excluído com sucesso!')
        return redirect('mimir:listarTemas')
    
    return render(request, 'mimir/temaConfirmDelete.html', {'tema': tema})
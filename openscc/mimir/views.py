import os, json, re
from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from .models import *
from .forms import FontesForm, GeracaoPerguntasForm, PerguntaForm, ProvaForm, TemaForm, SolicitarFeedbackForm, ResponderFeedbackForm, AplicacaoProvaForm, VincularMultiplosAlunosForm
from django.contrib import messages
from commons.services import getQuestionsFromSource, processarRespostaIA, construirTextoPerguntaCompleto, fazerCorrecaoComModelo
from django.http import JsonResponse, HttpResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_http_methods
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.template.loader import render_to_string
from weasyprint import HTML
from django.db.models import Count, Avg, Q
from .decorators import acesso_mimir_requerido, grupo_requerido
from django.contrib.auth.models import User

def acessoNegado(request):
    """View para página de acesso negado"""
    return render(request, 'mimir/acessoNegado.html')

@login_required
def redirecionarPorGrupo(request):
    """Redireciona o usuário baseado no seu grupo"""
    if request.user.isProfessor():
        return redirect('mimir:dashboardProfessor')
    elif request.user.isAluno():
        return redirect('mimir:dashboardAluno')
    else:
        return redirect('mimir:acessoNegado')

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
@acesso_mimir_requerido
@grupo_requerido('Professor')
def dashboardProfessor(request):
    # Obter estatísticas do banco de dados
    fontes_ativas = Fontes.objects.filter(user=request.user).count()
    problemas_criados = Problema.objects.filter(assunto__user=request.user).count()
    
    # Contar questões geradas (supondo que Pergunta tenha relação com usuário)
    questoes_geradas = Pergunta.objects.filter(assunto__user=request.user).count()
    
    # Contar provas criadas
    provas_criadas = Prova.objects.filter(assunto__user=request.user).count()
    
    context = {
        'fontes_ativas': fontes_ativas,
        'problemas_criados': problemas_criados,
        'questoes_geradas': questoes_geradas,
        'provas_criadas': provas_criadas
    }
    
    return render(request, "mimir/dashboardProfessor.html", context)

@login_required(login_url='/login')
@acesso_mimir_requerido
@grupo_requerido('Professor')
def visualizarFontes(request):
    sources = Fontes.objects.filter(user=request.user)
    return render(request, "mimir/listarFontes.html", {"sources": sources})

@login_required(login_url='/login')
@acesso_mimir_requerido
@grupo_requerido('Professor')
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
@acesso_mimir_requerido
@grupo_requerido('Professor')
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
@acesso_mimir_requerido
@grupo_requerido('Professor')
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
@acesso_mimir_requerido
@grupo_requerido('Professor')
def listarPerguntas(request):
    perguntas = Pergunta.objects.all()
    return render(request, "mimir/listarPerguntas.html", {"perguntas": perguntas})

@csrf_exempt
@login_required(login_url='/login')
@acesso_mimir_requerido
@grupo_requerido('Professor')
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
@acesso_mimir_requerido
@grupo_requerido('Professor')
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
@acesso_mimir_requerido
@grupo_requerido('Professor')
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
@acesso_mimir_requerido
@grupo_requerido('Professor')
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
@acesso_mimir_requerido
@grupo_requerido('Professor')
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
@acesso_mimir_requerido
@grupo_requerido('Professor')
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
@acesso_mimir_requerido
@grupo_requerido('Professor')
def editarProva(request, prova_id):
    prova = get_object_or_404(Prova, id=prova_id, user=request.user)
    
    # Verificar se o usuário tem permissão para editar
    if request.user != prova.user:
        # Se não é o dono, redireciona para visualização
        return redirect('mimir:visualizarProvaEspecialista', prova_id=prova_id)

    if request.method == 'POST':
        # Adicionar nova pergunta
        if 'adicionar_pergunta' in request.POST:
            pergunta_form = PerguntaForm(request.user, request.POST)
            if pergunta_form.is_valid():
                pergunta = pergunta_form.save(commit=False)
                pergunta.assunto = prova.assunto
                pergunta.user = request.user
                pergunta.save()
                prova.perguntas.add(pergunta)
                messages.success(request, "Pergunta adicionada com sucesso!")
                return redirect('mimir:editarProva', prova_id=prova.id)
        
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
    
    # Obter lista de especialistas para feedback
    
    especialistas = User.objects.filter(
        is_active=True,
        groups__name='Especialista'
    ).exclude(
        id=request.user.id
    ).order_by('first_name', 'last_name')
    
    context = {
        'prova': prova,
        'form': form,
        'pergunta_form': pergunta_form,
        'perguntas_prova': prova.perguntas.all(),
        'perguntas_disponiveis': Pergunta.objects.filter(assunto=prova.assunto).exclude(prova=prova),
        'especialistas': especialistas,  # Adicionando especialistas ao contexto
        'user': request.user,  # Adicionando user ao contexto
    }
    return render(request, 'mimir/editarProva.html', context)

@login_required(login_url='/login')
@acesso_mimir_requerido
@grupo_requerido('Professor')
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
@acesso_mimir_requerido
@grupo_requerido('Professor')
def removerPerguntaProva(request, prova_id, pergunta_id):
    prova = get_object_or_404(Prova, id=prova_id, user=request.user)
    pergunta = get_object_or_404(Pergunta, id=pergunta_id)
    
    prova.perguntas.remove(pergunta)
    messages.success(request, "Pergunta removida da prova!")
    
    return redirect('mimir:editarProva', prova_id=prova_id)

@login_required(login_url='/login')
@acesso_mimir_requerido
@grupo_requerido('Professor')
def listarProvas(request):
    provas = Prova.objects.filter(user=request.user).order_by('-dataCriacao')
    return render(request, 'mimir/listarProvas.html', {'provas': provas})

@login_required(login_url='/login')
@acesso_mimir_requerido
@grupo_requerido('Professor')
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
@acesso_mimir_requerido
@grupo_requerido('Professor')
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
@acesso_mimir_requerido
@grupo_requerido('Professor')
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
@acesso_mimir_requerido
@grupo_requerido('Professor')
def opcoesImpressao(request, prova_id):
    prova = get_object_or_404(Prova, id=prova_id, user=request.user)
    return render(request, 'mimir/opcoesImpressao.html', {'prova': prova})


@login_required
@acesso_mimir_requerido
@grupo_requerido('Professor')
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
@acesso_mimir_requerido
@grupo_requerido('Professor')
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
@acesso_mimir_requerido
@grupo_requerido('Professor')
def temaDelete(request, pk):
    tema = get_object_or_404(Tema, pk=pk)
    
    if request.method == 'POST':
        tema.delete()
        messages.success(request, 'Tema excluído com sucesso!')
        return redirect('mimir:listarTemas')
    
    return render(request, 'mimir/temaConfirmDelete.html', {'tema': tema})

@login_required
@acesso_mimir_requerido
@grupo_requerido('Professor')
def solicitarFeedback(request, problema_id, parte_ordem):
    """
    View para solicitar feedback de um especialista para uma parte específica
    """
    problema = get_object_or_404(Problema, id=problema_id)
    parte = get_object_or_404(Parte, problema=problema, ordem=parte_ordem)
    
    # Obter lista de especialistas (usuários com permissão específica ou todos os usuários ativos)
    # Aqui você pode ajustar a lógica para selecionar especialistas específicos
    especialistas = User.objects.filter(
        is_active=True,
        groups__name='Especialista'
    ).exclude(
        id=request.user.id
    ).order_by('first_name', 'last_name')
    
    if request.method == 'POST':
        form = SolicitarFeedbackForm(request.POST)
        if form.is_valid():
            especialista_id = form.cleaned_data['especialista_id']
            mensagem = form.cleaned_data['mensagem']
            
            especialista = get_object_or_404(User, id=especialista_id)
            
            # Criar o feedback
            feedback = FeedbackEspecialista.objects.create(
                parte=parte,
                especialista=especialista,
                solicitante=request.user,
                mensagem_solicitacao=mensagem,
                comentarios='',  # Será preenchido pelo especialista
                status='pendente'
            )
            
            # Aqui você pode adicionar notificação por email
            # enviar_notificacao_feedback(feedback)
            
            messages.success(
                request, 
                f'Feedback solicitado com sucesso para {especialista.get_full_name()}.'
            )
            
            return redirect('mimir:problemaDetail', pk=problema.id)
    
    else:
        form = SolicitarFeedbackForm()
    
    context = {
        'problema': problema,
        'parte': parte,
        'especialistas': especialistas,
        'form': form,
    }
    
    return render(request, 'mimir/solicitarFeedback.html', context)

@login_required
@acesso_mimir_requerido
@grupo_requerido('Professor')
def visualizarFeedbacksParte(request, problema_id, parte_ordem):
    """
    View para visualizar todos os feedbacks de uma parte específica
    """
    problema = get_object_or_404(Problema, id=problema_id)
    parte = get_object_or_404(Parte, problema=problema, ordem=parte_ordem)
    
    # Verificar permissão - autor do problema ou especialista que deu feedback
    if not (request.user == problema.autor or 
            parte.feedbacks.filter(especialista=request.user).exists()):
        return HttpResponseForbidden("Você não tem permissão para visualizar estes feedbacks.")
    
    feedbacks = parte.feedbacks.all().order_by('-criado_em')
    
    context = {
        'problema': problema,
        'parte': parte,
        'feedbacks': feedbacks,
    }
    
    return render(request, 'mimir/visualizarFeedbacks.html', context)

@login_required
@acesso_mimir_requerido
@grupo_requerido('Professor')
def marcarFeedbackUtilizado(request, feedback_id):
    """
    View para marcar um feedback como utilizado (tanto problemas quanto perguntas)
    """
    # Pré-carrega os relacionamentos baseado no tipo
    feedback = get_object_or_404(
        FeedbackEspecialista.objects.select_related(
            'parte__problema__tema',
            'pergunta'
        ),
        id=feedback_id
    )
    
    # Verificar se o usuário tem permissão para marcar como utilizado
    if feedback.tipo == 'problema':
        # Para problemas: verifica se é o autor do problema
        if not request.user == feedback.parte.problema.tema.usuario:
            return HttpResponseForbidden("Você não tem permissão para marcar este feedback como utilizado.")
    else:
        # Para perguntas: verifica se é o user da prova
        # Precisamos obter a prova que contém esta pergunta
        prova = Prova.objects.filter(perguntas=feedback.pergunta, user=request.user).first()
        if not prova:
            return HttpResponseForbidden("Você não tem permissão para marcar este feedback como utilizado.")
    
    # Só pode marcar como utilizado se já tiver comentários
    if not feedback.comentarios:
        messages.error(request, 'Não é possível marcar como utilizado um feedback que ainda não foi respondido.')
    else:
        feedback.marcar_como_utilizado()
        messages.success(request, 'Feedback marcado como utilizado.')
    
    # Redireciona para a página apropriada baseada no tipo
    if feedback.tipo == 'problema':
        return redirect('mimir:problemaDetail', pk=feedback.parte.problema.id)
    else:
        # Tenta encontrar a prova do usuário que contém esta pergunta
        prova = Prova.objects.filter(perguntas=feedback.pergunta, user=request.user).first()
        if prova:
            return redirect('mimir:editarProva', prova_id=prova.id)
        else:
            # Fallback: redireciona para meus feedbacks
            return redirect('mimir:meusFeedbacks')

@login_required
@acesso_mimir_requerido
@grupo_requerido('Professor')
def responderFeedback(request, feedback_id):
    """
    View para responder a um feedback recebido (tanto problemas quanto perguntas)
    """
    feedback = get_object_or_404(FeedbackEspecialista, id=feedback_id)
    
    # Verificar se o usuário tem permissão para responder
    # Para problemas: verifica se é o autor do problema
    # Para perguntas: verifica se é o user da prova
    if feedback.tipo == 'problema':
        if not request.user == feedback.parte.problema.tema.usuario:
            return HttpResponseForbidden("Você não tem permissão para responder este feedback.")
    else:
        # Para perguntas, verifica se é o user da primeira prova que contém a pergunta
        prova = feedback.pergunta.prova_set.first()
        if not prova or not request.user == prova.user:
            return HttpResponseForbidden("Você não tem permissão para responder este feedback.")
    
    if request.method == 'POST':
        form = ResponderFeedbackForm(request.POST, instance=feedback)
        if form.is_valid():
            form.save()
            feedback.responder(form.cleaned_data['resposta_autor'])
            
            messages.success(request, 'Resposta enviada com sucesso.')
            
            # Redireciona para a página apropriada baseada no tipo
            if feedback.tipo == 'problema':
                return redirect('mimir:problemaDetail', pk=feedback.parte.problema.id)
            else:
                prova = feedback.pergunta.prova_set.first()
                if prova:
                    return redirect('mimir:editarProva', prova_id=prova.id)
                else:
                    return redirect('mimir:meusFeedbacks')
    else:
        form = ResponderFeedbackForm(instance=feedback)
    
    context = {
        'feedback': feedback,
        'form': form,
    }    
    return render(request, 'mimir/responderFeedback.html', context)

@login_required
@acesso_mimir_requerido
@grupo_requerido('Professor')
def meusFeedbacks(request):
    """
    View para listar todos os feedbacks do usuário
    """
    # Feedbacks que o usuário solicitou
    feedbacks_solicitados = FeedbackEspecialista.objects.filter(
        solicitante=request.user
    ).select_related('parte', 'parte__problema', 'pergunta', 'especialista').prefetch_related('pergunta__prova_set').order_by('-criado_em')
    
    # Feedbacks onde o usuário é especialista
    feedbacks_como_especialista = FeedbackEspecialista.objects.filter(
        especialista=request.user
    ).select_related('parte', 'parte__problema', 'pergunta', 'solicitante').prefetch_related('pergunta__prova_set').order_by('-criado_em')

    # Estatísticas
    total_solicitados = feedbacks_solicitados.count()
    pendentes = feedbacks_solicitados.filter(comentarios='').count()
    para_responder = feedbacks_como_especialista.filter(comentarios='').count()
    utilizados = feedbacks_solicitados.filter(status='utilizado').count()
    
    # Contagem por tipo
    problemas_count = feedbacks_solicitados.filter(tipo='problema').count()
    perguntas_count = feedbacks_solicitados.filter(tipo='pergunta').count()

    context = {
        'feedbacks_solicitados': feedbacks_solicitados,
        'feedbacks_como_especialista': feedbacks_como_especialista,
        'total_solicitados': total_solicitados,
        'pendentes': pendentes,
        'para_responder': para_responder,
        'utilizados': utilizados,
        'problemas_count': problemas_count,
        'perguntas_count': perguntas_count,
    }
    
    return render(request, 'mimir/meusFeedbacks.html', context)

@login_required
@acesso_mimir_requerido
@grupo_requerido('Professor')
def fornecerFeedback(request, feedback_id):
    """
    View para especialista fornecer feedback para problemas ou perguntas
    """
    # Pré-carrega os relacionamentos baseado no tipo
    if request.method == 'GET':
        feedback = get_object_or_404(
            FeedbackEspecialista.objects.select_related(
                'solicitante',
                'parte__problema__tema',
                'parte__problema__assunto',
                'pergunta__assunto',
                'pergunta__tipoDePergunta'
            ),
            id=feedback_id
        )
    else:
        feedback = get_object_or_404(FeedbackEspecialista, id=feedback_id)
    
    # Verificar se o usuário é o especialista designado
    if not request.user == feedback.especialista:
        return HttpResponseForbidden("Você não tem permissão para fornecer feedback para esta solicitação.")
    
    if request.method == 'POST':
        if feedback.tipo == 'pergunta':
            # Para perguntas, os campos vêm separados
            pergunta_revisada = request.POST.get('pergunta_revisada', '').strip()
            gabarito_revisado = request.POST.get('gabarito_revisado', '').strip()
            
            if not pergunta_revisada or not gabarito_revisado:
                messages.error(request, 'Por favor, forneça tanto a pergunta revisada quanto o gabarito revisado.')
            else:
                # Concatenar com o separador
                comentarios = f"{pergunta_revisada}\n\n---GABARITO---\n\n{gabarito_revisado}"
                feedback.comentarios = comentarios
                feedback.status = 'respondido'
                feedback.respondido_em = timezone.now()
                feedback.save()
                
                messages.success(request, 'Feedback enviado com sucesso!')
                return redirect('mimir:meusFeedbacks')
                
        else:
            # Para problemas, usa o campo comentários diretamente
            comentarios = request.POST.get('comentarios', '').strip()
            
            if not comentarios:
                messages.error(request, 'Por favor, forneça seus comentários.')
            else:
                feedback.comentarios = comentarios
                feedback.status = 'respondido'
                feedback.respondido_em = timezone.now()
                feedback.save()
                
                messages.success(request, 'Feedback enviado com sucesso!')
                return redirect('mimir:meusFeedbacks')
    
    # Preparar contexto para o template
    context = {
        'feedback': feedback,
    }
    
    # Se já existe feedback e é do tipo pergunta, separar os campos
    if feedback.tipo == 'pergunta' and feedback.comentarios:
        if '---GABARITO---' in feedback.comentarios:
            partes = feedback.comentarios.split('---GABARITO---')
            context['pergunta_revisada'] = partes[0].strip()
            context['gabarito_revisado'] = partes[1].strip() if len(partes) > 1 else ''
        else:
            # Se não tem separador, colocar tudo na pergunta
            context['pergunta_revisada'] = feedback.comentarios
            context['gabarito_revisado'] = feedback.pergunta.gabarito if feedback.pergunta else ''
    elif feedback.tipo == 'pergunta':
        # Se não tem comentários ainda, preencher com os originais
        context['pergunta_revisada'] = feedback.pergunta.pergunta if feedback.pergunta else ''
        context['gabarito_revisado'] = feedback.pergunta.gabarito if feedback.pergunta else ''
    
    return render(request, 'mimir/fornecerFeedback.html', context)

@login_required
@acesso_mimir_requerido
@grupo_requerido('Professor')
def excluirFeedback(request, feedback_id):
    """
    View para excluir um feedback (apenas autor ou admin)
    """
    feedback = get_object_or_404(FeedbackEspecialista, id=feedback_id)
    
    # Verificar permissão - apenas autor do problema ou admin
    if not (request.user == feedback.solicitante or request.user.is_staff):
        return HttpResponseForbidden("Você não tem permissão para excluir este feedback.")
    
    problema_id = feedback.parte.problema.id
    
    if request.method == 'POST':
        feedback.delete()
        messages.success(request, 'Feedback excluído com sucesso.')
        return redirect('mimir:problemaDetail', pk=problema_id)
    
    context = {
        'feedback': feedback,
    }
    
    return render(request, 'mimir/excluirFeedback.html', context)

@login_required
@acesso_mimir_requerido
@grupo_requerido('Professor')
def solicitarFeedbackPergunta(request, prova_id, pergunta_id):
    """
    View para solicitar feedback de um especialista para uma pergunta específica
    """
    prova = get_object_or_404(Prova, id=prova_id)
    pergunta = get_object_or_404(Pergunta, id=pergunta_id)
    
    # Verificar se o usuário tem permissão para solicitar feedback
    if not request.user == prova.user:
        return HttpResponseForbidden("Você não tem permissão para solicitar feedback para esta prova.")
    
    # Obter lista de especialistas
    especialistas = User.objects.filter(
        is_active=True,
        groups__name='Especialista'
    ).exclude(
        id=request.user.id
    ).order_by('first_name', 'last_name')
    
    if request.method == 'POST':
        form = SolicitarFeedbackForm(request.POST)
        if form.is_valid():
            especialista_id = form.cleaned_data['especialista_id']
            mensagem = form.cleaned_data['mensagem']
            
            try:
                especialista = User.objects.get(id=especialista_id)
                
                # Verificar se já existe um feedback pendente para este especialista nesta pergunta
                feedback_existente = FeedbackEspecialista.objects.filter(
                    pergunta=pergunta,
                    especialista=especialista,
                    status='pendente'
                ).exists()
                
                if feedback_existente:
                    messages.warning(
                        request, 
                        f'Já existe uma solicitação de feedback pendente para {especialista.get_full_name()} nesta pergunta.'
                    )
                else:
                    # Criar o feedback
                    feedback = FeedbackEspecialista.objects.create(
                        pergunta=pergunta,
                        tipo='pergunta',
                        especialista=especialista,
                        solicitante=request.user,
                        mensagem_solicitacao=mensagem,
                        comentarios='',
                        status='pendente'
                    )
                    
                    messages.success(
                        request, 
                        f'Feedback solicitado com sucesso para {especialista.get_full_name()}.'
                    )
                
                return redirect('mimir:editarProva', prova_id=prova.id)
                
            except User.DoesNotExist:
                messages.error(request, 'Especialista não encontrado.')
    
    else:
        form = SolicitarFeedbackForm()
    
    context = {
        'prova': prova,
        'pergunta': pergunta,
        'especialistas': especialistas,
        'form': form,
    }
    
    return render(request, 'mimir/solicitarFeedbackPergunta.html', context)

@login_required
@acesso_mimir_requerido
@grupo_requerido('Professor')
def visualizarFeedbacksPergunta(request, prova_id, pergunta_id):
    """
    View para visualizar todos os feedbacks de uma pergunta específica
    """
    prova = get_object_or_404(Prova, id=prova_id)
    pergunta = get_object_or_404(Pergunta, id=pergunta_id)
    
    # Verificar permissão
    if not (request.user == prova.user or 
            pergunta.feedbacks.filter(especialista=request.user).exists()):
        return HttpResponseForbidden("Você não tem permissão para visualizar estes feedbacks.")
    
    feedbacks = pergunta.feedbacks.all().order_by('-criado_em')
    
    context = {
        'prova': prova,
        'pergunta': pergunta,
        'feedbacks': feedbacks,
    }
    
    return render(request, 'mimir/visualizarFeedbacksPergunta.html', context)

@login_required
@require_POST
@acesso_mimir_requerido
@grupo_requerido('Professor')
def aceitarFeedback(request, feedback_id):
    """
    View para aceitar e aplicar o feedback do especialista
    """
    feedback = get_object_or_404(FeedbackEspecialista, id=feedback_id, solicitante=request.user)
    
    try:
        feedback.aceitar_feedback()
        messages.success(request, 'Feedback aceito e aplicado com sucesso!')
    except Exception as e:
        messages.error(request, f'Erro ao aplicar feedback: {str(e)}')
    
    return redirect('mimir:meusFeedbacks')

@login_required
@require_POST
@acesso_mimir_requerido
@grupo_requerido('Professor')
def rejeitarFeedback(request, feedback_id):
    """
    View para rejeitar o feedback do especialista
    """
    feedback = get_object_or_404(FeedbackEspecialista, id=feedback_id, solicitante=request.user)
    resposta_autor = request.POST.get('resposta_autor', '')
    
    try:
        feedback.rejeitar_feedback(resposta_autor)
        messages.success(request, 'Feedback rejeitado com sucesso!')
    except Exception as e:
        messages.error(request, f'Erro ao rejeitar feedback: {str(e)}')
    
    return redirect('mimir:meusFeedbacks')

@login_required
@acesso_mimir_requerido
@grupo_requerido('Professor')
def visualizarProvaEspecialista(request, prova_id, feedback_id=None):
    """
    View para especialista visualizar prova (somente leitura) relacionada a um feedback
    """
    prova = get_object_or_404(Prova, id=prova_id)
    
    # Verificar se o usuário tem permissão para visualizar esta prova
    # Permite se: é o dono OU é especialista com feedback relacionado a alguma pergunta desta prova
    pode_visualizar = False
    
    if request.user == prova.user:
        pode_visualizar = True
    else:
        # Verificar se é especialista com feedback para alguma pergunta desta prova
        feedbacks_especialista = FeedbackEspecialista.objects.filter(
            especialista=request.user,
            tipo='pergunta',
            pergunta__prova=prova
        )
        if feedbacks_especialista.exists():
            pode_visualizar = True
        # Ou se foi passado um feedback_id específico
        elif feedback_id:
            feedback = get_object_or_404(FeedbackEspecialista, id=feedback_id)
            if feedback.especialista == request.user and feedback.pergunta and feedback.pergunta.prova_set.filter(id=prova_id).exists():
                pode_visualizar = True
    
    if not pode_visualizar:
        return HttpResponseForbidden("Você não tem permissão para visualizar esta prova.")
    
    # Obter a pergunta específica se houver feedback_id
    pergunta_especifica = None
    if feedback_id:
        feedback = get_object_or_404(FeedbackEspecialista, id=feedback_id)
        pergunta_especifica = feedback.pergunta
    
    context = {
        'prova': prova,
        'perguntas_prova': prova.perguntas.all(),
        'modo_visualizacao': True,
        'pergunta_especifica': pergunta_especifica,
        'feedback_id': feedback_id,
    }
    
    return render(request, 'mimir/visualizarProvaEspecialista.html', context)

@login_required
@acesso_mimir_requerido
@grupo_requerido('Aluno')
def dashboardAluno(request):
   
    # Buscar provas do aluno através do modelo ProvaAluno
    provas_aluno = ProvaAluno.objects.filter(aluno=request.user).select_related(
        'aplicacao_prova__prova__assunto'
    )
    
    context = {
        'provas_pendentes': provas_aluno.filter(status='pendente'),
        'provas_andamento': provas_aluno.filter(status='em_andamento'),
        'provas_concluidas': provas_aluno.filter(status='concluida'),
        'provas_corrigidas': provas_aluno.filter(status='corrigida'),
    }
    
    return render(request, 'mimir/dashboardAluno.html', context)

@login_required
@acesso_mimir_requerido
@grupo_requerido('Aluno')
def listarProvasDisponiveis(request):
    """Lista provas disponíveis para o aluno"""
    
    # Buscar aplicações de prova onde o aluno está incluído
    aplicacoes_disponiveis = AplicacaoProva.objects.filter(
        alunos=request.user,
        disponivel=True,
        data_disponivel__lte=timezone.now(),
        data_limite__gte=timezone.now()
    ).select_related('prova__assunto').prefetch_related('prova__perguntas')
    
    # Para cada aplicação, verificar se já existe um ProvaAluno
    aplicacoes_com_status = []
    for aplicacao in aplicacoes_disponiveis:
        prova_aluno = ProvaAluno.objects.filter(
            aplicacao_prova=aplicacao,
            aluno=request.user
        ).first()
        
        aplicacoes_com_status.append({
            'aplicacao': aplicacao,
            'prova_aluno': prova_aluno,
            'status': prova_aluno.status if prova_aluno else 'pendente'
        })
    
    context = {
        'aplicacoes_com_status': aplicacoes_com_status,
    }
    
    return render(request, 'mimir/listarProvasDisponiveis.html', context)

@login_required
@acesso_mimir_requerido
@grupo_requerido('Aluno')
def iniciarProva(request, prova_aluno_id):
    """Inicia uma prova para o aluno"""
    prova_aluno = get_object_or_404(ProvaAluno, id=prova_aluno_id, aluno=request.user)
    
    if prova_aluno.status not in ['pendente', 'em_andamento']:
        return render(request, 'mimir/erroProva.html', {
            'mensagem': 'Esta prova já foi concluída.'
        })
    
    # Verifica se a prova ainda está disponível através da aplicação
    aplicacao = prova_aluno.aplicacao_prova
    
    if not aplicacao.esta_disponivel():
        return render(request, 'mimir/erroProva.html', {
            'mensagem': 'O prazo para realização desta prova expirou.'
        })
    
    # Inicia a prova se ainda não foi iniciada
    if prova_aluno.status == 'pendente':
        prova_aluno.iniciar_prova()
    
    # Carrega as perguntas da prova através da aplicação
    perguntas = aplicacao.prova.perguntas.all().prefetch_related('imagens')
    
    # Carrega respostas existentes
    respostas_existentes = {
        resposta.pergunta_id: resposta 
        for resposta in RespostaAluno.objects.filter(
            aluno=request.user, 
            prova_aluno=prova_aluno
        )
    }
    
    context = {
        'prova_aluno': prova_aluno,
        'perguntas': perguntas,
        'respostas_existentes': respostas_existentes,
        'aplicacao': aplicacao,
    }
    
    return render(request, 'mimir/resolverProva.html', context)

@login_required
@require_http_methods(["POST"])
@acesso_mimir_requerido
@grupo_requerido('Aluno')
def salvarResposta(request, prova_aluno_id):
    """Salva uma resposta do aluno (AJAX)"""
    if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        try:
            prova_aluno = get_object_or_404(ProvaAluno, id=prova_aluno_id, aluno=request.user)
            
            # Verifica se a prova ainda está em andamento
            if prova_aluno.status != 'em_andamento':
                return JsonResponse({'status': 'error', 'message': 'Prova não está em andamento'}, status=400)
            
            data = json.loads(request.body)
            pergunta_id = data.get('pergunta_id')
            resposta_texto = data.get('resposta_texto', '')
            
            pergunta = get_object_or_404(Pergunta, id=pergunta_id)
            
            # Verifica se a pergunta pertence à prova
            if not prova_aluno.aplicacao_prova.prova.perguntas.filter(id=pergunta_id).exists():
                return JsonResponse({'status': 'error', 'message': 'Pergunta não pertence a esta prova'}, status=400)
            
            # Salva ou atualiza a resposta
            resposta, created = RespostaAluno.objects.get_or_create(
                aluno=request.user,
                pergunta=pergunta,
                prova_aluno=prova_aluno,
                defaults={'resposta_texto': resposta_texto}
            )
            
            if not created:
                resposta.resposta_texto = resposta_texto
                resposta.save()
            
            return JsonResponse({
                'status': 'success', 
                'salvo_em': resposta.atualizado_em.isoformat(),
                'created': created,
                'pergunta_id': pergunta_id
            })
        
        except json.JSONDecodeError:
            return JsonResponse({'status': 'error', 'message': 'Dados JSON inválidos'}, status=400)
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': f'Erro interno: {str(e)}'}, status=500)
    
    return JsonResponse({'status': 'error', 'message': 'Requisição inválida'}, status=400)

@login_required
@acesso_mimir_requerido
@grupo_requerido('Aluno')
def finalizarProva(request, prova_aluno_id):
    """Finaliza a prova e calcula a nota"""
    prova_aluno = get_object_or_404(ProvaAluno, id=prova_aluno_id, aluno=request.user)
    
    if prova_aluno.status == 'em_andamento':
        prova_aluno.finalizar_prova()
        # Calcula nota automaticamente (para questões objetivas)
        prova_aluno.calcular_nota()
    
    return redirect('mimir:verResultadoProva', prova_aluno_id=prova_aluno.id)

@login_required
@acesso_mimir_requerido
@grupo_requerido('Aluno')
def verResultadoProva(request, prova_aluno_id):
    prova_aluno = get_object_or_404(ProvaAluno, id=prova_aluno_id, aluno=request.user)
    
    # Calcular questões respondidas
    questoes_respondidas = RespostaAluno.objects.filter(
        prova_aluno=prova_aluno
    ).exclude(resposta_texto='').count()
    
    context = {
        'prova_aluno': prova_aluno,
        'perguntas': prova_aluno.aplicacao_prova.prova.perguntas.all(),
        'respostas': {r.pergunta_id: r for r in RespostaAluno.objects.filter(prova_aluno=prova_aluno)},
        'questoes_respondidas': questoes_respondidas,
    }
    return render(request, 'mimir/resultadoProva.html', context)

@login_required
def criarProvaAluno(request, aplicacao_id):
    """Cria um registro ProvaAluno para um aluno iniciar uma prova"""
    if not request.user.isAluno():
        return redirect('mimir:dashboardProfessor')
    
    aplicacao = get_object_or_404(AplicacaoProva, id=aplicacao_id, alunos=request.user)
    
    # Verifica se já existe um ProvaAluno
    prova_aluno, created = ProvaAluno.objects.get_or_create(
        aplicacao_prova=aplicacao,
        aluno=request.user,
        defaults={'status': 'pendente'}
    )
    
    return redirect('mimir:iniciarProva', prova_aluno_id=prova_aluno.id)

@login_required
@acesso_mimir_requerido
@grupo_requerido('Professor')
def listarAplicacoesProva(request):
    """Lista todas as aplicações de prova do professor"""
    
    aplicacoes = AplicacaoProva.objects.filter(
        prova__user=request.user
    ).select_related('prova', 'prova__assunto').prefetch_related(
        'alunos', 'provas_alunos'
    ).annotate(
        total_alunos=Count('alunos', distinct=True),
        alunos_concluidos=Count('provas_alunos', filter=Q(provas_alunos__status='concluida') | Q(provas_alunos__status='corrigida'), distinct=True)
    ).order_by('-criado_em')
    
    # Verificar se o professor tem provas criadas
    tem_provas = Prova.objects.filter(user=request.user).exists()
    
    # Calcular estatísticas para os cards (apenas se houver aplicações)
    aplicacoes_ativas = aplicacoes.filter(disponivel=True).count() if aplicacoes else 0
    
    total_alunos_geral = 0
    total_concluidas_geral = 0
    
    for aplicacao in aplicacoes:
        total_alunos_geral += aplicacao.total_alunos or 0
        total_concluidas_geral += aplicacao.alunos_concluidos or 0
    
    context = {
        'aplicacoes': aplicacoes,
        'aplicacoes_ativas': aplicacoes_ativas,
        'total_alunos_geral': total_alunos_geral,
        'total_concluidas_geral': total_concluidas_geral,
        'tem_provas': tem_provas,
    }
    
    return render(request, 'mimir/listarAplicacoesProva.html', context)

@login_required
@acesso_mimir_requerido
@grupo_requerido('Professor')
def selecionarProvaParaAplicacao(request):
    """Lista provas disponíveis para criar uma aplicação"""
    
    provas = Prova.objects.filter(user=request.user).select_related('assunto')
    
    context = {
        'provas': provas,
    }
    
    return render(request, 'mimir/selecionarProvaAplicacao.html', context)

@login_required
@acesso_mimir_requerido
@grupo_requerido('Professor')
def criarAplicacaoProva(request, prova_id):
    """Cria uma nova aplicação de prova"""
    
    # Garantir que a prova pertence ao professor
    prova = get_object_or_404(Prova, id=prova_id, user=request.user)
    
    # Buscar assuntos do professor com contagem de alunos vinculados
    assuntos_professor = Assunto.objects.filter(user=request.user)
    
    # Preparar os assuntos com a contagem de alunos
    assuntos_com_contagem = []
    for assunto in assuntos_professor:
        contagem_alunos = assunto.get_alunos_vinculados_ativos().count()
        assuntos_com_contagem.append({
            'assunto': assunto,
            'contagem_alunos': contagem_alunos
        })
    
    # Anos disponíveis para filtro
    from datetime import datetime
    anos_disponiveis = [(year, str(year)) for year in range(2020, datetime.now().year + 2)]
    
    if request.method == 'POST':
        form = AplicacaoProvaForm(request.POST)
        if form.is_valid():
            aplicacao = form.save(commit=False)
            aplicacao.prova = prova
            aplicacao.save()
            
            # Processar alunos - por assunto ou seleção manual
            assunto_id = request.POST.get('assunto')
            ano = request.POST.get('ano')
            semestre = request.POST.get('semestre')
            alunos_selecionados_manual = form.cleaned_data['alunos']
            
            alunos_para_vincular = set()
            
            # Se foi selecionado um assunto, buscar todos os alunos vinculados
            if assunto_id:
                assunto = get_object_or_404(Assunto, id=assunto_id, user=request.user)
                vinculos = assunto.alunos_vinculados.filter(ativo=True)
                
                # Aplicar filtros de período se fornecidos
                if ano:
                    vinculos = vinculos.filter(ano=int(ano))
                if semestre:
                    vinculos = vinculos.filter(semestre=int(semestre))
                
                # Adicionar alunos do assunto
                for vinculo in vinculos:
                    alunos_para_vincular.add(vinculo.aluno)
            
            # Adicionar alunos selecionados manualmente (se houver)
            for aluno in alunos_selecionados_manual:
                alunos_para_vincular.add(aluno)
            
            # Vincular todos os alunos selecionados
            for aluno in alunos_para_vincular:
                aplicacao.adicionar_aluno(aluno)
            
            messages.success(request, f'Aplicação de prova criada com sucesso! {len(alunos_para_vincular)} aluno(s) vinculado(s).')
            return redirect('mimir:detalhesAplicacaoProva', aplicacao_id=aplicacao.id)
    else:
        form = AplicacaoProvaForm()
    
    context = {
        'prova': prova,
        'form': form,
        'assuntos_professor': assuntos_com_contagem,  # Usar a lista com contagem
        'anos_disponiveis': anos_disponiveis,
    }
    
    return render(request, 'mimir/criarAplicacaoProva.html', context)

@login_required
@acesso_mimir_requerido
@grupo_requerido('Professor')
def detalhesAplicacaoProva(request, aplicacao_id):
    """Detalhes de uma aplicação de prova com estatísticas"""
    
    aplicacao = get_object_or_404(
        AplicacaoProva, 
        id=aplicacao_id, 
        prova__user=request.user
    )
    
    # Estatísticas dos alunos
    provas_alunos = ProvaAluno.objects.filter(
        aplicacao_prova=aplicacao
    ).select_related('aluno').annotate(
        total_respostas=Count('respostas')
    )
    
    # Calcular médias
    if provas_alunos.filter(nota_final__isnull=False).exists():
        media_geral = provas_alunos.filter(nota_final__isnull=False).aggregate(
            media=Avg('nota_final')
        )['media']
    else:
        media_geral = None
    
    context = {
        'aplicacao': aplicacao,
        'provas_alunos': provas_alunos,
        'media_geral': media_geral,
        'total_alunos': provas_alunos.count(),
        'alunos_concluidos': provas_alunos.filter(status='concluida').count(),
        'alunos_corrigidos': provas_alunos.filter(status='corrigida').count(),
    }
    
    return render(request, 'mimir/detalhesAplicacaoProva.html', context)

@login_required
@acesso_mimir_requerido
@grupo_requerido('Professor')
def editarAplicacaoProva(request, aplicacao_id):
    """Edita uma aplicação de prova existente"""
    
    aplicacao = get_object_or_404(
        AplicacaoProva, 
        id=aplicacao_id, 
        prova__user=request.user
    )
    
    if request.method == 'POST':
        form = AplicacaoProvaForm(request.POST, instance=aplicacao)
        if form.is_valid():
            aplicacao = form.save()
            
            # Atualizar alunos
            alunos_selecionados = form.cleaned_data['alunos']
            alunos_atuais = set(aplicacao.alunos.all())
            alunos_novos = set(alunos_selecionados)
            
            # Remover alunos que foram desmarcados
            for aluno in alunos_atuais - alunos_novos:
                aplicacao.remover_aluno(aluno)
            
            # Adicionar novos alunos
            for aluno in alunos_novos - alunos_atuais:
                aplicacao.adicionar_aluno(aluno)
            
            messages.success(request, 'Aplicação de prova atualizada com sucesso!')
            return redirect('mimir:listarAplicacoesProva')
    else:
        form = AplicacaoProvaForm(instance=aplicacao, initial={'alunos': aplicacao.alunos.all()})
    
    context = {
        'aplicacao': aplicacao,
        'form': form,
    }
    
    return render(request, 'mimir/editarAplicacaoProva.html', context)

@login_required
@acesso_mimir_requerido
@grupo_requerido('Professor')
def excluirAplicacaoProva(request, aplicacao_id):
    """Exclui uma aplicação de prova"""
    
    aplicacao = get_object_or_404(
        AplicacaoProva, 
        id=aplicacao_id, 
        prova__user=request.user
    )
    
    if request.method == 'POST':
        aplicacao.delete()
        messages.success(request, 'Aplicação de prova excluída com sucesso!')
        return redirect('mimir:listarAplicacoesProva')
    
    context = {
        'aplicacao': aplicacao,
    }
    
    return render(request, 'mimir/excluirAplicacaoProva.html', context)

@login_required
@acesso_mimir_requerido
@grupo_requerido('Professor')
def corrigirProvaAluno(request, prova_aluno_id):
    prova_aluno = get_object_or_404(
        ProvaAluno, 
        id=prova_aluno_id,
        aplicacao_prova__prova__user=request.user
    )
    
    # Preparar perguntas com suas respostas e correção automática
    perguntas_com_respostas = []
    for pergunta in prova_aluno.aplicacao_prova.prova.perguntas.all():
        resposta = RespostaAluno.objects.filter(
            pergunta=pergunta,
            prova_aluno=prova_aluno
        ).first()
        
        # Verificar se é múltipla escolha e calcular correção automática
        tipo_pergunta = pergunta.tipoDePergunta.descricao.lower()
        is_multipla_escolha = any(termo in tipo_pergunta for termo in ["múltipla escolha", "multipla escolha", "multiple choice"])
        
        correta = False
        if is_multipla_escolha and resposta and resposta.resposta_texto:
            # Comparar resposta do aluno com gabarito (apenas a letra)
            resposta_aluno = resposta.resposta_texto.strip().upper()
            gabarito_correto = pergunta.gabarito.strip().upper()
            # Considerar apenas a primeira letra para comparação
            correta = resposta_aluno and gabarito_correto and resposta_aluno[0] == gabarito_correto[0]
        
        perguntas_com_respostas.append({
            'pergunta': pergunta,
            'resposta': resposta,
            'correta': correta,
            'is_multipla_escolha': is_multipla_escolha
        })
    
    if request.method == 'POST':
        total_notas = 0
        total_pesos = 0
        
        for pergunta in prova_aluno.aplicacao_prova.prova.perguntas.all():
            nota_pergunta = request.POST.get(f'nota_{pergunta.id}')
            feedback_pergunta = request.POST.get(f'feedback_{pergunta.id}')
            peso_pergunta = request.POST.get(f'peso_{pergunta.id}', 1)
            
            if nota_pergunta is not None:
                resposta, created = RespostaAluno.objects.get_or_create(
                    aluno=prova_aluno.aluno,
                    pergunta=pergunta,
                    prova_aluno=prova_aluno,
                    defaults={'resposta_texto': ''}
                )
                
                # Para questões de múltipla escolha, usar a nota automática
                tipo_pergunta = pergunta.tipoDePergunta.descricao.lower()
                is_multipla_escolha = any(termo in tipo_pergunta for termo in ["múltipla escolha", "multipla escolha", "multiple choice"])
                
                if is_multipla_escolha:
                    # Recalcular se a resposta está correta
                    resposta_aluno = resposta.resposta_texto.strip().upper() if resposta.resposta_texto else ""
                    gabarito_correto = pergunta.gabarito.strip().upper()
                    correta = resposta_aluno and gabarito_correto and resposta_aluno[0] == gabarito_correto[0]
                    nota_final = 10.0 if correta else 0.0
                else:
                    nota_final = float(nota_pergunta) if nota_pergunta else 0
                
                # Atualizar campos de correção
                resposta.nota = nota_final
                resposta.feedback_professor = feedback_pergunta
                resposta.peso = int(peso_pergunta)
                resposta.save()
                
                # Calcular contribuição para nota final
                if resposta.nota is not None:
                    total_notas += resposta.nota * resposta.peso
                    total_pesos += resposta.peso
        
        # Calcular nota final
        if total_pesos > 0:
            prova_aluno.nota_final = total_notas / total_pesos
        
        # Marcar como corrigida
        prova_aluno.status = 'corrigida'
        prova_aluno.save()
        
        messages.success(request, f'Prova de {prova_aluno.aluno.get_full_name()} corrigida com sucesso!')
        return redirect('mimir:detalhesAplicacaoProva', aplicacao_id=prova_aluno.aplicacao_prova.id)
    
    # GET request - mostrar template de correção
    context = {
        'prova_aluno': prova_aluno,
        'perguntas_com_respostas': perguntas_com_respostas,
    }
    return render(request, 'mimir/corrigirProva.html', context)

@login_required
@require_POST
@acesso_mimir_requerido
@grupo_requerido('Professor')
def editarParte(request, parte_id):
    """Edita manualmente uma parte do problema via AJAX"""
    try:
        parte = get_object_or_404(Parte, id=parte_id)
        
        # Verificar se o usuário é o autor do problema
        if parte.problema.assunto.user != request.user:
            return JsonResponse({
                'status': 'error', 
                'message': 'Você não tem permissão para editar esta parte.'
            }, status=403)
        
        novo_enunciado = request.POST.get('enunciado', '').strip()
        
        if not novo_enunciado:
            return JsonResponse({
                'status': 'error', 
                'message': 'O enunciado não pode estar vazio.'
            })
        
        # Salvar as alterações
        parte.enunciado = novo_enunciado
        parte.save()
        
        return JsonResponse({
            'status': 'success',
            'message': 'Parte atualizada com sucesso!',
            'novo_enunciado': novo_enunciado
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error', 
            'message': f'Erro ao salvar: {str(e)}'
        }, status=500)
    
@login_required
@require_POST
@acesso_mimir_requerido
@grupo_requerido('Professor')
def adicionarMidiaParte(request, parte_id):
    """Adiciona uma mídia a uma parte do problema"""
    try:
        parte = get_object_or_404(Parte, id=parte_id)
        
        # Verificar se o usuário é o autor do problema
        if parte.problema.tema.usuario != request.user:
            return JsonResponse({
                'status': 'error', 
                'message': 'Você não tem permissão para adicionar mídias a esta parte.'
            }, status=403)
        
        arquivo = request.FILES.get('arquivo')
        tipo = request.POST.get('tipo', 'imagem')
        descricao = request.POST.get('descricao', '').strip()
        ordem = int(request.POST.get('ordem', parte.midias.count() + 1))
        
        if not arquivo:
            return JsonResponse({
                'status': 'error', 
                'message': 'Nenhum arquivo foi enviado.'
            })
        
        # Validar tipo de arquivo
        extensoes_permitidas = {
            'imagem': ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'],
            'audio': ['.mp3', '.wav', '.ogg', '.m4a'],
            'pdf': ['.pdf'],
            'video': ['.mp4', '.avi', '.mov', '.wmv'],
            'documento': ['.doc', '.docx', '.txt', '.rtf']
        }
        
        extensao = os.path.splitext(arquivo.name)[1].lower()
        if extensao not in extensoes_permitidas.get(tipo, []):
            return JsonResponse({
                'status': 'error', 
                'message': f'Tipo de arquivo não permitido para {tipo}.'
            })
        
        # Criar a mídia
        midia = MidiaParte.objects.create(
            parte=parte,
            arquivo=arquivo,
            tipo=tipo,
            descricao=descricao,
            ordem=ordem
        )
        
        return JsonResponse({
            'status': 'success',
            'message': 'Mídia adicionada com sucesso!',
            'midia_id': midia.id
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error', 
            'message': f'Erro ao adicionar mídia: {str(e)}'
        }, status=500)

@login_required
@require_POST
@acesso_mimir_requerido
@grupo_requerido('Professor')
def excluirMidiaParte(request, midia_id):
    """Exclui uma mídia de uma parte"""
    try:
        midia = get_object_or_404(MidiaParte, id=midia_id)
        
        # Verificar se o usuário é o autor do problema
        if midia.parte.problema.tema.usuario != request.user:
            return JsonResponse({
                'status': 'error', 
                'message': 'Você não tem permissão para excluir esta mídia.'
            }, status=403)
        
        midia.delete()
        
        return JsonResponse({
            'status': 'success',
            'message': 'Mídia excluída com sucesso!'
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error', 
            'message': f'Erro ao excluir mídia: {str(e)}'
        }, status=500)
    
@require_POST
@csrf_exempt
def corrigirComIA(request):
    try:
        data = json.loads(request.body)
        pergunta_id = data.get('pergunta_id')
        enunciado = data.get('enunciado')
        gabarito = data.get('gabarito')
        resposta_aluno = data.get('resposta_aluno')
        
        # Aqui você integra com seu modelo de IA
        # Esta é uma implementação de exemplo - substitua pela sua lógica real
        
        # Simulação de processamento com IA
        retornoModelo = fazerCorrecaoComModelo(enunciado, gabarito, resposta_aluno)

        json_match = re.search(r'\{.*\}', retornoModelo, re.DOTALL)
        if json_match:
            json_match = json.loads(json_match.group())
        else:
            json_match = None
            
        return JsonResponse({
            'success': True,
            'nota': json_match.get('nota', 0) if json_match else 0,
            'feedback': json_match.get('justificativa', "") if json_match else "",
            'pergunta_id': pergunta_id
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Erro na correção automática: {str(e)}'
        })
    
@login_required
@acesso_mimir_requerido
@grupo_requerido('Professor')
def gerenciarVinculosAssunto(request, assunto_id):
    """
    View para gerenciar alunos vinculados a um assunto
    """
    assunto = get_object_or_404(Assunto, id=assunto_id, user=request.user)
    
    vinculos_ativos = assunto.get_vinculos_ativos().select_related('aluno')
    
    # Calcular estatísticas
    total_por_ano = {}
    total_por_semestre = {}
    
    for vinculo in vinculos_ativos:
        total_por_ano[vinculo.ano] = total_por_ano.get(vinculo.ano, 0) + 1
        total_por_semestre[vinculo.semestre] = total_por_semestre.get(vinculo.semestre, 0) + 1
    
    # Anos disponíveis para filtro
    anos_disponiveis = VinculoAlunoAssunto.ANO_CHOICES
    
    if request.method == 'POST':
        form = VincularMultiplosAlunosForm(request.POST, user=request.user)
        if form.is_valid():
            alunos = form.cleaned_data['alunos']
            ano = int(form.cleaned_data['ano'])
            semestre = int(form.cleaned_data['semestre'])
            
            count = 0
            for aluno in alunos:
                try:
                    assunto.vincular_aluno(aluno, ano, semestre)
                    count += 1
                except ValidationError as e:
                    messages.error(request, f"Erro ao vincular {aluno.get_full_name()}: {e}")
            
            if count > 0:
                messages.success(request, f'{count} aluno(s) vinculado(s) com sucesso!')
                return redirect('mimir:gerenciarVinculosAssunto', assunto_id=assunto_id)
    else:
        # Inicializar o formulário com o assunto atual
        form = VincularMultiplosAlunosForm(user=request.user, initial={'assunto': assunto})
    
    context = {
        'assunto': assunto,
        'vinculos_ativos': vinculos_ativos,
        'form': form,
        'total_por_ano': total_por_ano,
        'total_por_semestre': total_por_semestre,
        'anos_disponiveis': anos_disponiveis,
    }
    return render(request, 'mimir/gerenciarVinculosAssunto.html', context)

@login_required
@require_POST
@acesso_mimir_requerido
@grupo_requerido('Professor')
def removerVinculo(request, vinculo_id):
    """
    View para remover um vínculo via AJAX
    """
    vinculo = get_object_or_404(
        VinculoAlunoAssunto, 
        id=vinculo_id, 
        assunto__user=request.user
    )
    
    try:
        vinculo.ativo = False
        vinculo.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Vínculo removido com sucesso!'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Erro ao remover vínculo: {str(e)}'
        })
    
@login_required
@acesso_mimir_requerido
@grupo_requerido('Professor')
def listarAssuntosVinculos(request):
    """
    View para listar todos os assuntos do professor com estatísticas de vínculos
    """
    # Buscar assuntos do usuário atual (professor)
    assuntos = Assunto.objects.filter(user=request.user).annotate(
        total_alunos=Count('alunos_vinculados', filter=models.Q(alunos_vinculados__ativo=True)),
        total_vinculos=Count('alunos_vinculados', filter=models.Q(alunos_vinculados__ativo=True))
    ).order_by('nome')
    
    # Calcular estatísticas gerais
    total_alunos_vinculados = User.objects.filter(
        vinculos_assuntos__assunto__user=request.user,
        vinculos_assuntos__ativo=True
    ).distinct().count()
    
    total_vinculos_ativos = VinculoAlunoAssunto.objects.filter(
        assunto__user=request.user,
        ativo=True
    ).count()
    
    # Ano atual para referência
    ano_atual = timezone.now().year
    
    context = {
        'assuntos': assuntos,
        'total_alunos_vinculados': total_alunos_vinculados,
        'total_vinculos_ativos': total_vinculos_ativos,
        'ano_atual': ano_atual,
    }
    
    return render(request, 'mimir/listarAssuntosVinculos.html', context)
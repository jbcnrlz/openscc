import os, json, re, bibtexparser
from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from .models import *
from .forms import *
from django.contrib import messages
from commons.services import getQuestionsFromSource, processarRespostaIA, construirTextoPerguntaCompleto, fazerCorrecaoComModelo, corrigirRespostaMultimodal
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
from django.utils.text import slugify
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from django.utils.html import strip_tags
from commons.services import get_llm


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
            print(qtd_perguntas)
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
'''
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
'''
@login_required(login_url='/login')
@acesso_mimir_requerido
@grupo_requerido('Professor')
def visualizarFontes(request):
    # Recupera as fontes do usuário ordenadas da mais recente para a mais antiga
    sources_list = Fontes.objects.filter(user=request.user).order_by('-dataCriacao')
    
    # Captura o termo de busca (se houver)
    query = request.GET.get('q')
    if query:
        # Filtra pelo nome usando case-insensitive (icontains)
        sources_list = sources_list.filter(nome__icontains=query)
        
    # Paginação: 10 fontes por página
    paginator = Paginator(sources_list, 10)
    page = request.GET.get('page')
    
    try:
        sources = paginator.page(page)
    except PageNotAnInteger:
        # Se a página não for um inteiro, entrega a primeira página.
        sources = paginator.page(1)
    except EmptyPage:
        # Se a página estiver fora do limite, entrega a última página de resultados.
        sources = paginator.page(paginator.num_pages)
        
    context = {
        'sources': sources,
        'query': query or '',
        'total_fontes': paginator.count
    }
    return render(request, "mimir/listarFontes.html", context)

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
                    quantidades[tipo.descricao] = quantidade
                    contExtra += f'- {quantidade} QUESTÕES DO TIPO {tipo.descricao}\n'
                    if tipo.textoParaLLM is not None:
                        contExtra += tipo.textoParaLLM + '\n'
            
            if not any(quantidades.values()):
                messages.error(request, 'Selecione pelo menos uma quantidade de perguntas.')
                return render(request, 'mimir/gerarPerguntas.html', {'form': form})
            
            if not fontes_selecionadas:
                messages.error(request, 'Selecione pelo menos uma fonte.')
                return render(request, 'mimir/gerarPerguntas.html', {'form': form})
            print(f"Quantidades: {quantidades}")
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
def solicitarFeedback(request, problema_id):
    """
    View para solicitar feedback de um especialista para um problema inteiro
    """
    problema = get_object_or_404(Problema, id=problema_id)
    
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
            
            feedback = FeedbackEspecialista.objects.create(
                problema=problema,
                tipo='problema',
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
            return redirect('mimir:problemaDetail', pk=problema.id)
    else:
        form = SolicitarFeedbackForm()
    
    context = {
        'problema': problema,
        'especialistas': especialistas,
        'form': form,
    }
    return render(request, 'mimir/solicitarFeedback.html', context)

@login_required
@acesso_mimir_requerido
@grupo_requerido('Professor')
def visualizarFeedbacksProblema(request, problema_id):
    """
    View para visualizar todos os feedbacks de um problema específico
    """
    problema = get_object_or_404(Problema, id=problema_id)
    
    if not (request.user == problema.tema.usuario or 
            problema.feedbacks.filter(especialista=request.user).exists()):
        return HttpResponseForbidden("Você não tem permissão para visualizar estes feedbacks.")
    
    feedbacks = problema.feedbacks.all().order_by('-criado_em')
    
    context = {
        'problema': problema,
        'feedbacks': feedbacks,
    }
    return render(request, 'mimir/visualizarFeedbacks.html', context)


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
    feedback = get_object_or_404(
        FeedbackEspecialista.objects.select_related(
            'problema__tema',
            'pergunta'
        ),
        id=feedback_id
    )
    
    if feedback.tipo == 'problema':
        if not request.user == feedback.problema.tema.usuario:
            return HttpResponseForbidden("Você não tem permissão para marcar este feedback como utilizado.")
    else:
        prova = Prova.objects.filter(perguntas=feedback.pergunta, user=request.user).first()
        if not prova:
            return HttpResponseForbidden("Você não tem permissão para marcar este feedback como utilizado.")
    
    if not feedback.comentarios:
        messages.error(request, 'Não é possível marcar como utilizado um feedback que ainda não foi respondido.')
    else:
        feedback.marcar_como_utilizado()
        messages.success(request, 'Feedback marcado como utilizado.')
    
    if feedback.tipo == 'problema':
        return redirect('mimir:problemaDetail', pk=feedback.problema.id)
    else:
        prova = Prova.objects.filter(perguntas=feedback.pergunta, user=request.user).first()
        if prova:
            return redirect('mimir:editarProva', prova_id=prova.id)
        else:
            return redirect('mimir:meusFeedbacks')

@login_required
@acesso_mimir_requerido
@grupo_requerido('Professor')
def responderFeedback(request, feedback_id):
    feedback = get_object_or_404(FeedbackEspecialista, id=feedback_id)
    
    if feedback.tipo == 'problema':
        if not request.user == feedback.problema.tema.usuario:
            return HttpResponseForbidden("Você não tem permissão para responder este feedback.")
    else:
        prova = feedback.pergunta.prova_set.first()
        if not prova or not request.user == prova.user:
            return HttpResponseForbidden("Você não tem permissão para responder este feedback.")
    
    if request.method == 'POST':
        form = ResponderFeedbackForm(request.POST, instance=feedback)
        if form.is_valid():
            form.save()
            feedback.responder(form.cleaned_data['resposta_autor'])
            messages.success(request, 'Resposta enviada com sucesso.')
            
            if feedback.tipo == 'problema':
                return redirect('mimir:problemaDetail', pk=feedback.problema.id)
            else:
                prova = feedback.pergunta.prova_set.first()
                if prova:
                    return redirect('mimir:editarProva', prova_id=prova.id)
                else:
                    return redirect('mimir:meusFeedbacks')
    else:
        form = ResponderFeedbackForm(instance=feedback)
    
    return render(request, 'mimir/responderFeedback.html', {'feedback': feedback, 'form': form})

@login_required
@acesso_mimir_requerido
@grupo_requerido('Professor')
def meusFeedbacks(request):
    feedbacks_solicitados = FeedbackEspecialista.objects.filter(
        solicitante=request.user
    ).select_related('problema', 'pergunta', 'especialista').prefetch_related('pergunta__prova_set').order_by('-criado_em')
    
    feedbacks_como_especialista = FeedbackEspecialista.objects.filter(
        especialista=request.user
    ).select_related('problema', 'pergunta', 'solicitante').prefetch_related('pergunta__prova_set').order_by('-criado_em')

    context = {
        'feedbacks_solicitados': feedbacks_solicitados,
        'feedbacks_como_especialista': feedbacks_como_especialista,
        'total_solicitados': feedbacks_solicitados.count(),
        'pendentes': feedbacks_solicitados.filter(comentarios='').count(),
        'para_responder': feedbacks_como_especialista.filter(comentarios='').count(),
        'utilizados': feedbacks_solicitados.filter(status='utilizado').count(),
        'problemas_count': feedbacks_solicitados.filter(tipo='problema').count(),
        'perguntas_count': feedbacks_solicitados.filter(tipo='pergunta').count(),
    }
    return render(request, 'mimir/meusFeedbacks.html', context)

@login_required
@acesso_mimir_requerido
@grupo_requerido('Especialista')
def fornecerFeedback(request, feedback_id):
    if request.method == 'GET':
        feedback = get_object_or_404(
            FeedbackEspecialista.objects.select_related(
                'solicitante',
                'problema__tema',
                'problema__assunto',
                'pergunta__assunto',
                'pergunta__tipoDePergunta'
            ),
            id=feedback_id
        )
    else:
        feedback = get_object_or_404(FeedbackEspecialista, id=feedback_id)
    
    # Trava de segurança
    if not request.user == feedback.especialista:
        return HttpResponseForbidden("Você não tem permissão para fornecer feedback para esta solicitação.")
    
    # Processamento do POST unificado
    if request.method == 'POST':
        # O template moderno envia tudo (Problema ou Pergunta) unificado no campo 'comentarios'
        comentarios = request.POST.get('comentarios', '').strip()
        
        if not comentarios:
            messages.error(request, 'Por favor, forneça suas edições ou comentários no editor.')
        else:
            feedback.comentarios = comentarios
            feedback.status = 'respondido'
            feedback.respondido_em = timezone.now()
            feedback.save()
            messages.success(request, 'Parecer técnico enviado com sucesso!')
            return redirect('mimir:meusFeedbacks')
    
    # Contexto para o GET
    context = { 'feedback': feedback }
    
    # Se o tipo for problema, mandamos as partes para o JS montar o texto original
    if feedback.tipo == 'problema' and feedback.problema:
        context['partes'] = feedback.problema.partes.all().order_by('ordem')
    
    # Nota: Removemos o antigo processamento de GET que quebrava strings e injetava 
    # as variáveis 'pergunta_revisada' no contexto, pois o novo JavaScript 
    # lê diretamente de 'feedback.pergunta.pergunta' no Front-End.

    return render(request, 'mimir/fornecerFeedback.html', context)

@login_required
@acesso_mimir_requerido
@grupo_requerido('Professor')
def excluirFeedback(request, feedback_id):
    feedback = get_object_or_404(FeedbackEspecialista, id=feedback_id)
    if not (request.user == feedback.solicitante or request.user.is_staff):
        return HttpResponseForbidden("Você não tem permissão para excluir este feedback.")
    
    problema_id = feedback.problema.id
    if request.method == 'POST':
        feedback.delete()
        messages.success(request, 'Feedback excluído com sucesso.')
        return redirect('mimir:problemaDetail', pk=problema_id)
    
    return render(request, 'mimir/excluirFeedback.html', {'feedback': feedback})

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
'''
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
'''
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
    """Salva uma resposta do aluno (AJAX) - Suporta texto e upload de arquivo"""
    try:
        prova_aluno = get_object_or_404(ProvaAluno, id=prova_aluno_id, aluno=request.user)
        
        # ===== VALIDAÇÕES INICIAIS =====
        # Verifica se a prova ainda está em andamento
        if prova_aluno.status != 'em_andamento':
            return JsonResponse({
                'status': 'error', 
                'message': 'Prova não está em andamento'
            }, status=400)
        
        # ===== DETECTAR TIPO DE REQUISIÇÃO =====
        if 'multipart/form-data' in request.content_type:
            return _processar_upload_arquivo(request, prova_aluno)
        else:
            return _processar_resposta_texto(request, prova_aluno)
    
    except json.JSONDecodeError:
        return JsonResponse({
            'status': 'error', 
            'message': 'Dados JSON inválidos'
        }, status=400)
    
    except Exception as e:        
        return JsonResponse({
            'status': 'error', 
            'message': f'Erro interno do servidor: {str(e)}'
        }, status=500)

def _processar_upload_arquivo(request, prova_aluno):
    """Processa upload de arquivo de resposta"""
    pergunta_id = request.POST.get('pergunta_id')
    arquivo_resposta = request.FILES.get('arquivo_resposta')
    
    if not pergunta_id or not arquivo_resposta:
        return JsonResponse({
            'status': 'error', 
            'message': 'Dados incompletos para upload de arquivo'
        }, status=400)
    
    pergunta = get_object_or_404(Pergunta, id=pergunta_id)
    
    # Verifica se a pergunta pertence à prova
    if not prova_aluno.aplicacao_prova.prova.perguntas.filter(id=pergunta_id).exists():
        return JsonResponse({
            'status': 'error', 
            'message': 'Pergunta não pertence a esta prova'
        }, status=400)
    
    # Verifica se a pergunta aceita upload de arquivo
    if not pergunta.aceita_upload_resposta:
        return JsonResponse({
            'status': 'error', 
            'message': 'Esta pergunta não aceita upload de arquivo'
        }, status=400)
    
    # Validar tamanho do arquivo (10MB)
    if arquivo_resposta.size > 10 * 1024 * 1024:
        return JsonResponse({
            'status': 'error', 
            'message': 'Arquivo muito grande. Tamanho máximo: 10MB'
        }, status=400)
    
    # Validar tipo de arquivo
    tipos_permitidos = [
        'application/pdf',
        'application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'image/jpeg',
        'image/jpg', 
        'image/png',
        'text/plain'
    ]
    
    if arquivo_resposta.content_type not in tipos_permitidos:
        return JsonResponse({
            'status': 'error', 
            'message': 'Tipo de arquivo não permitido. Use PDF, Word, imagem ou texto.'
        }, status=400)
    
    # Validar nome do arquivo (evitar caracteres especiais)
    import re
    nome_valido = re.match(r'^[\w\-. ]+$', arquivo_resposta.name)
    if not nome_valido:
        return JsonResponse({
            'status': 'error', 
            'message': 'Nome do arquivo contém caracteres inválidos'
        }, status=400)
    
    # Buscar ou criar resposta
    resposta, created = RespostaAluno.objects.get_or_create(
        aluno=request.user,
        pergunta=pergunta,
        prova_aluno=prova_aluno
    )
    
    # Remove arquivo anterior se existir
    if resposta.arquivo_resposta:
        resposta.arquivo_resposta.delete(save=False)
    
    # Remove texto se existir e salva o arquivo
    resposta.resposta_texto = ''
    resposta.arquivo_resposta = arquivo_resposta
    resposta.save()
       
    return JsonResponse({
        'status': 'success', 
        'salvo_em': resposta.atualizado_em.isoformat(),
        'created': created,
        'pergunta_id': pergunta_id,
        'nome_arquivo': arquivo_resposta.name,
        'tamanho_arquivo': arquivo_resposta.size,
        'tipo_resposta': 'arquivo'
    })

def _processar_resposta_texto(request, prova_aluno):
    """Processa resposta em texto"""
    data = json.loads(request.body)
    pergunta_id = data.get('pergunta_id')
    resposta_texto = data.get('resposta_texto', '')
    
    if not pergunta_id:
        return JsonResponse({
            'status': 'error', 
            'message': 'ID da pergunta é obrigatório'
        }, status=400)
    
    pergunta = get_object_or_404(Pergunta, id=pergunta_id)
    
    # Verifica se a pergunta pertence à prova
    if not prova_aluno.aplicacao_prova.prova.perguntas.filter(id=pergunta_id).exists():
        return JsonResponse({
            'status': 'error', 
            'message': 'Pergunta não pertence a esta prova'
        }, status=400)
    
    # Para perguntas de múltipla escolha, validar se a resposta é uma das alternativas
    if pergunta.tipoDePergunta.descricao.lower() in ['múltipla escolha', 'multipla escolha', 'multiple choice']:
        alternativas = pergunta.pergunta  # Aqui você precisaria extrair as alternativas
        # Adicione validação específica para múltipla escolha se necessário
    
    # Buscar ou criar resposta
    resposta, created = RespostaAluno.objects.get_or_create(
        aluno=request.user,
        pergunta=pergunta,
        prova_aluno=prova_aluno
    )
    
    if not created:
        # Se está salvando texto, remove o arquivo se existir
        if resposta.arquivo_resposta:
            resposta.arquivo_resposta.delete(save=False)
            resposta.arquivo_resposta = None
    
    # Salva o texto da resposta
    resposta.resposta_texto = resposta_texto
    resposta.save()
   
    return JsonResponse({
        'status': 'success', 
        'salvo_em': resposta.atualizado_em.isoformat(),
        'created': created,
        'pergunta_id': pergunta_id,
        'tipo_resposta': 'texto',
        'tamanho_texto': len(resposta_texto)
    })

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
    
    # Buscar todas as perguntas da prova
    perguntas = prova_aluno.aplicacao_prova.prova.perguntas.all()
    
    # Buscar todas as respostas do aluno para esta prova
    respostas = RespostaAluno.objects.filter(prova_aluno=prova_aluno)
    respostas_dict = {resposta.pergunta_id: resposta for resposta in respostas}
    
    # Calcular estatísticas
    questoes_respondidas = 0
    questoes_com_arquivo = 0
    respostas_texto = 0
    respostas_arquivo = 0
    
    for resposta in respostas_dict.values():
        # Considera respondida se tem texto OU arquivo
        if resposta.resposta_texto or resposta.arquivo_resposta:
            questoes_respondidas += 1
            
            # Contagem por tipo de resposta
            if resposta.arquivo_resposta:
                questoes_com_arquivo += 1
                respostas_arquivo += 1
            elif resposta.resposta_texto.strip():  # Só conta se não for texto vazio
                respostas_texto += 1
    
    # Estatísticas de notas (apenas se a prova foi corrigida)
    notas_acima_7 = 0
    notas_entre_5_7 = 0
    notas_abaixo_5 = 0
    
    if prova_aluno.status == 'corrigida':
        for resposta in respostas_dict.values():
            if resposta.nota is not None:
                if resposta.nota >= 7:
                    notas_acima_7 += 1
                elif resposta.nota >= 5:
                    notas_entre_5_7 += 1
                else:
                    notas_abaixo_5 += 1
    
    context = {
        'prova_aluno': prova_aluno,
        'perguntas': perguntas,
        'respostas': respostas_dict,
        'questoes_respondidas': questoes_respondidas,
        'questoes_com_arquivo': questoes_com_arquivo,
        'respostas_texto': respostas_texto,
        'respostas_arquivo': respostas_arquivo,
        'notas_acima_7': notas_acima_7,
        'notas_entre_5_7': notas_entre_5_7,
        'notas_abaixo_5': notas_abaixo_5,
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
        tipo_resposta = data.get('tipo_resposta', 'texto')  # 'texto' ou 'arquivo'
        
        # Buscar a pergunta para obter informações das imagens
        pergunta = Pergunta.objects.get(id=pergunta_id)
        
        # Preparar informações sobre imagens da pergunta
        imagens_pergunta = []
        for imagem in pergunta.imagens.all():
            imagens_pergunta.append({
                'url': imagem.imagem.url,
                'nome': imagem.imagem.name,
                'caminho_absoluto': imagem.imagem.path
            })
        
        # Buscar a resposta do aluno para verificar se tem arquivo
        resposta = RespostaAluno.objects.filter(pergunta_id=pergunta_id).first()
        arquivo_resposta = None
        
        if resposta and resposta.arquivo_resposta:
            arquivo_resposta = {
                'url': resposta.arquivo_resposta.url,
                'nome': resposta.arquivo_resposta.name,
                'caminho_absoluto': resposta.arquivo_resposta.path,
                'tipo': resposta.arquivo_resposta.name.split('.')[-1].lower()
            }
            tipo_resposta = 'arquivo'
        
        # Se a resposta for um arquivo de imagem, processar com a função multimodal
        if tipo_resposta == 'arquivo' and arquivo_resposta and arquivo_resposta['tipo'] in ['jpg', 'jpeg', 'png', 'gif', 'bmp']:
            resultado = corrigirRespostaMultimodal(
                enunciado=enunciado,
                gabarito=gabarito,
                resposta_aluno=arquivo_resposta['caminho_absoluto'],  # Caminho do arquivo
                imagens_pergunta=imagens_pergunta
            )
        else:
            # Para respostas em texto ou outros tipos de arquivo
            resultado = fazerCorrecaoComModelo(
                enunciado=enunciado,
                gabarito=gabarito,
                resposta_aluno=resposta_aluno
            )
        
        # Processar o retorno do modelo
        print(resultado)
        nota, feedback = parse_gemini_response(resultado)
            
        return JsonResponse({
            'success': True,
            'nota': nota,
            'feedback': feedback,
            'pergunta_id': pergunta_id,
            'tipo_processamento': 'multimodal' if tipo_resposta == 'arquivo' else 'textual'
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

def parse_gemini_response(resultado):
    """
    Tenta parsear a resposta do Gemini de forma robusta
    """
    # Primeira tentativa: buscar JSON com regex
    json_match = re.search(r'\{.*\}', resultado, re.DOTALL)
    if not json_match:
        return 0, "Não foi possível extrair JSON da resposta."
    
    json_str = json_match.group()
    
    # Tentativas de parse em sequência
    attempts = [
        # Tentativa 1: Parse direto
        lambda: json.loads(json_str),
        
        # Tentativa 2: Sanitizar caracteres de controle
        lambda: json.loads(re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', json_str)),
        
        # Tentativa 3: Corrigir problemas de escape
        lambda: json.loads(json_str.replace('\\n', '\\\\n').replace('\\t', '\\\\t')),
        
        # Tentativa 4: Remover BOM e caracteres problemáticos
        lambda: json.loads(json_str.replace('\ufeff', '').replace('\u2028', '').replace('\u2029', '')),
    ]
    
    for i, attempt in enumerate(attempts):
        try:
            resultado_json = attempt()
            nota = resultado_json.get('nota', 0)
            feedback = resultado_json.get('justificativa', "")
            return nota, feedback
        except json.JSONDecodeError as e:
            continue
    
    # Última tentativa: parsing manual
    try:
        # Extrair nota manualmente
        nota_match = re.search(r'"nota"\s*:\s*(\d+(?:\.\d+)?)', json_str)
        nota = float(nota_match.group(1)) if nota_match else 0
        
        # Extrair justificativa manualmente
        just_match = re.search(r'"justificativa"\s*:\s*"([^"]*)"', json_str, re.DOTALL)
        if not just_match:
            just_match = re.search(r'"justificativa"\s*:\s*"([^"]*(?:"[^"]*)*)"', json_str)
        
        feedback = just_match.group(1) if just_match else "Justificativa não encontrada."
        
        return nota, feedback
    except Exception as e:
        return 0, "Erro crítico no processamento da resposta."

@login_required(login_url='/login')
@acesso_mimir_requerido
@grupo_requerido('Professor')
def criarPergunta(request):
    if request.method == 'POST':
        # Instancia o form vazio com os dados do POST (supondo que o PerguntaForm exija request.user)
        form = PerguntaForm(request.user, request.POST, request.FILES)
        
        if form.is_valid():
            try:
                pergunta = form.save()
                
                # Processar upload de imagens
                novas_imagens = request.FILES.getlist('imagens')
                for imagem in novas_imagens:
                    if imagem.content_type not in ['image/jpeg', 'image/png', 'image/gif']:
                        messages.error(request, f'Arquivo {imagem.name} não é uma imagem válida.')
                        continue
                    
                    if imagem.size > 5 * 1024 * 1024:  # 5MB
                        messages.error(request, f'Imagem {imagem.name} é muito grande (máximo 5MB).')
                        continue
                    
                    ImagemPergunta.objects.create(pergunta=pergunta, imagem=imagem)
                
                messages.success(request, 'Pergunta criada com sucesso!')
                
                # Redirecionamento conforme o botão clicado
                if 'salvar_e_ver' in request.POST:
                    return redirect('mimir:visualizarPergunta', pergunta.id)
                elif 'salvar_e_adicionar_outra' in request.POST:
                    return redirect('mimir:criarPergunta')
                else:
                    return redirect('mimir:visualizarPerguntas')
                    
            except Exception as e:
                messages.error(request, f'Erro ao criar pergunta: {str(e)}')
                print(f"Erro detalhado: {e}")
        else:
            messages.error(request, 'Por favor, corrija os erros no formulário.')
            print(f"Erros do formulário: {form.errors}")
    else:
        # Requer instanciar o form apenas com o user
        form = PerguntaForm(request.user)

    return render(request, 'mimir/criarPergunta.html', {
        'form': form,
        'titulo': 'Criar Nova Pergunta'
    })

@login_required
@acesso_mimir_requerido
@grupo_requerido('Professor')
def listarTemplatesContexto(request):
    templates = TemplateContexto.objects.filter(usuario=request.user)
    return render(request, 'mimir/listarTemplatesContexto.html', {'templates': templates})

@login_required
@acesso_mimir_requerido
@grupo_requerido('Professor')
def criarTemplateContexto(request):
    if request.method == 'POST':
        form = TemplateContextoForm(request.POST)
        if form.is_valid():
            template = form.save(commit=False)
            template.usuario = request.user
            template.save()
            messages.success(request, 'Template cadastrado com sucesso!')
            return redirect('mimir:listarTemplatesContexto')
    else:
        form = TemplateContextoForm()
    return render(request, 'mimir/templateContextoForm.html', {'form': form, 'titulo': 'Cadastrar Template'})

@login_required
@acesso_mimir_requerido
@grupo_requerido('Professor')
def atualizarTemplateContexto(request, pk):
    template = get_object_or_404(TemplateContexto, pk=pk, usuario=request.user)
    if request.method == 'POST':
        form = TemplateContextoForm(request.POST, instance=template)
        if form.is_valid():
            form.save()
            messages.success(request, 'Template atualizado com sucesso!')
            return redirect('mimir:listarTemplatesContexto')
    else:
        form = TemplateContextoForm(instance=template)
    return render(request, 'mimir/templateContextoForm.html', {'form': form, 'titulo': 'Editar Template', 'template': template})

@login_required
@acesso_mimir_requerido
@grupo_requerido('Professor')
def deletarTemplateContexto(request, pk):
    template = get_object_or_404(TemplateContexto, pk=pk, usuario=request.user)
    if request.method == 'POST':
        template.delete()
        messages.success(request, 'Template excluído com sucesso!')
        return redirect('mimir:listarTemplatesContexto')
    return render(request, 'mimir/deletarTemplateContexto.html', {'template': template})

@login_required
@acesso_mimir_requerido
@grupo_requerido('Professor')
def listarObjetivos(request):
    objetivos = ObjetivosAprendizagem.objects.all().order_by('descricao')
    return render(request, 'mimir/listarObjetivos.html', {'objetivos': objetivos})

@login_required
@acesso_mimir_requerido
@grupo_requerido('Professor')
def criarObjetivo(request):
    if request.method == 'POST':
        form = ObjetivosAprendizagemForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Objetivo de aprendizagem cadastrado com sucesso!')
            return redirect('mimir:listarObjetivos')
    else:
        form = ObjetivosAprendizagemForm()
    return render(request, 'mimir/objetivoForm.html', {'form': form, 'titulo': 'Cadastrar Objetivo de Aprendizagem'})

@login_required
@acesso_mimir_requerido
@grupo_requerido('Professor')
def atualizarObjetivo(request, pk):
    objetivo = get_object_or_404(ObjetivosAprendizagem, pk=pk)
    if request.method == 'POST':
        form = ObjetivosAprendizagemForm(request.POST, instance=objetivo)
        if form.is_valid():
            form.save()
            messages.success(request, 'Objetivo de aprendizagem atualizado com sucesso!')
            return redirect('mimir:listarObjetivos')
    else:
        form = ObjetivosAprendizagemForm(instance=objetivo)
    return render(request, 'mimir/objetivoForm.html', {'form': form, 'titulo': 'Editar Objetivo de Aprendizagem', 'objetivo': objetivo})

@login_required
@acesso_mimir_requerido
@grupo_requerido('Professor')
def deletarObjetivo(request, pk):
    objetivo = get_object_or_404(ObjetivosAprendizagem, pk=pk)
    if request.method == 'POST':
        objetivo.delete()
        messages.success(request, 'Objetivo de aprendizagem excluído com sucesso!')
        return redirect('mimir:listarObjetivos')
    return render(request, 'mimir/deletarObjetivo.html', {'objective': objetivo})

@login_required
@require_POST
@acesso_mimir_requerido
@grupo_requerido('Professor')
def exportarProblemaComoFonte(request, problema_id):
    problema = get_object_or_404(Problema, id=problema_id)
    
    # Validação de segurança
    if problema.assunto.user != request.user:
        messages.error(request, "Você não tem permissão para exportar este problema.")
        return redirect('mimir:problemaDetail', pk=problema.id)
        
    # Construção do texto estruturado
    linhas = []
    linhas.append(f"TÍTULO DO PROBLEMA: {problema.titulo}")
    linhas.append(f"TEMA: {problema.tema.nome}")
    linhas.append(f"ASSUNTO: {problema.assunto.nome}")
    linhas.append("\nOBJETIVOS DE APRENDIZAGEM:")
    
    for obj in problema.objetivos.all():
        linhas.append(f"- {obj.descricao}")
        
    linhas.append("\nESTRUTURA DO CASO CLÍNICO:")
    for parte in problema.partes.all().order_by('ordem'):
        linhas.append(f"\n--- PARTE {parte.ordem} ---")
        linhas.append(parte.enunciado)
        
    # Inclui o Guia do Tutor se existir para dar mais contexto à IA
    if hasattr(problema, 'guia_tutor') and problema.guia_tutor:
        linhas.append("\n--- GUIA DO TUTOR ---")
        linhas.append(problema.guia_tutor.conteudo)
        
    conteudo_final = "\n".join(linhas)
    nome_arquivo = f"export_{slugify(problema.titulo)}.txt"
    
    # Cria a nova fonte e salva o arquivo em txt
    nova_fonte = Fontes(
        nome=f"[Problema] {problema.titulo}",
        descricao=f"Problema exportado em {timezone.now().strftime('%d/%m/%Y')} para retroalimentação da IA.",
        user=request.user
    )
    
    # A MÁGICA ACONTECE AQUI: 'utf-8-sig' força o BOM no início do arquivo
    nova_fonte.fonte.save(nome_arquivo, ContentFile(conteudo_final.encode('utf-8-sig')))
    nova_fonte.save()
    
    messages.success(request, f"Sucesso! O problema foi convertido na fonte '{nova_fonte.nome}' e já está disponível para uso.")
    return redirect('mimir:visualizarFontes')

# ==========================================
# VIEWS DO TUTOR / PROFESSOR
# ==========================================

@login_required
def painelTutorGrupo(request, grupo_id):
    """Painel onde o Tutor gerencia o grupo e os problemas."""
    grupo = get_object_or_404(PequenoGrupo, id=grupo_id)
    
    # Validação: Só o tutor do grupo ou professor do assunto podem acessar
    if not (request.user == grupo.tutor or request.user == grupo.assunto.user or request.user.is_superuser):
        return redirect('mimir:acessoNegado')
        
    problemas = Problema.objects.filter(assunto=grupo.assunto).order_by('-criado_em')
    
    context = {
        'grupo': grupo,
        'problemas': problemas,
        'partes_liberadas': LiberacaoParte.objects.filter(grupo=grupo).values_list('parte_id', flat=True)
    }
    return render(request, 'mimir/pbl/painelTutor.html', context)

@login_required
@require_POST
def alternarLiberacaoParte(request, grupo_id, parte_id):
    """View via AJAX para o Tutor liberar/ocultar partes em tempo real."""
    grupo = get_object_or_404(PequenoGrupo, id=grupo_id)
    parte = get_object_or_404(Parte, id=parte_id)
    
    # Validação de segurança
    if not (request.user == grupo.tutor or request.user == grupo.assunto.user):
        return JsonResponse({'status': 'error', 'message': 'Permissão negada'}, status=403)
        
    liberacao, created = LiberacaoParte.objects.get_or_create(
        grupo=grupo, 
        parte=parte,
        defaults={'liberada_por': request.user}
    )
    
    if not created:
        liberacao.delete() # Se já existia, oculta (toggle)
        status = 'ocultada'
    else:
        status = 'liberada'
        
    return JsonResponse({'status': 'success', 'acao': status})


# ==========================================
# VIEWS DO ALUNO
# ==========================================

@login_required
def problemaSessaoAluno(request, grupo_id, problema_id):
    """Interface do aluno onde ele lê apenas o que foi liberado e adiciona perguntas."""
    grupo = get_object_or_404(PequenoGrupo, id=grupo_id)
    problema = get_object_or_404(Problema, id=problema_id)
    
    if request.user not in grupo.alunos.all() and request.user != grupo.tutor:
        return redirect('mimir:acessoNegado')
        
    # Pega apenas as partes que o tutor já liberou para este grupo
    ids_liberados = LiberacaoParte.objects.filter(grupo=grupo).values_list('parte_id', flat=True)
    partes_visiveis = problema.partes.filter(id__in=ids_liberados).order_by('ordem')
    
    perguntas_aprendizado = PerguntaAprendizado.objects.filter(grupo=grupo, parte__problema=problema)
    
    context = {
        'grupo': grupo,
        'problema': problema,
        'partes': partes_visiveis,
        'perguntas': perguntas_aprendizado
    }
    return render(request, 'mimir/pbl/sessaoAluno.html', context)

@login_required
@require_POST
def adicionarPerguntaAprendizado(request, grupo_id, parte_id):
    """View para o aluno submeter uma nova pergunta de aprendizado (AJAX ou Form tradicional)"""
    grupo = get_object_or_404(PequenoGrupo, id=grupo_id)
    parte = get_object_or_404(Parte, id=parte_id)
    texto = request.POST.get('texto')
    
    if texto and request.user in grupo.alunos.all():
        PerguntaAprendizado.objects.create(
            grupo=grupo,
            parte=parte,
            aluno=request.user,
            texto=texto
        )
        messages.success(request, "Pergunta de aprendizado registrada!")
        
    return redirect('mimir:problemaSessaoAluno', grupo_id=grupo.id, problema_id=parte.problema.id)

# ==========================================
# GESTÃO DE GRUPOS (PROFESSOR)
# ==========================================

@login_required
@grupo_requerido('Professor')
def listarPequenosGrupos(request):
    """View para o Professor listar e criar novos pequenos grupos."""
    grupos = PequenoGrupo.objects.filter(assunto__user=request.user).order_by('-criado_em')
    assuntos = Assunto.objects.filter(user=request.user)
    
    if request.method == 'POST':
        nome = request.POST.get('nome')
        assunto_id = request.POST.get('assunto_id')
        if nome and assunto_id:
            assunto = get_object_or_404(Assunto, id=assunto_id, user=request.user)
            PequenoGrupo.objects.create(nome=nome, assunto=assunto)
            messages.success(request, f"Grupo '{nome}' criado com sucesso!")
        return redirect('mimir:listarPequenosGrupos')
        
    return render(request, 'mimir/pbl/listarGrupos.html', {'grupos': grupos, 'assuntos': assuntos})

@login_required
@grupo_requerido('Professor')
def gerenciarPequenoGrupo(request, grupo_id):
    """View para o Professor vincular Tutor e Alunos ao grupo."""
    grupo = get_object_or_404(PequenoGrupo, id=grupo_id, assunto__user=request.user)
    tutores = User.objects.filter(groups__name='Tutor', is_active=True).order_by('first_name')
    alunos = User.objects.filter(groups__name='Aluno', is_active=True).order_by('first_name')
    
    if request.method == 'POST':
        tutor_id = request.POST.get('tutor')
        alunos_selecionados = request.POST.getlist('alunos')
        
        grupo.tutor_id = tutor_id if tutor_id else None
        grupo.alunos.set(alunos_selecionados)
        grupo.save()
        
        messages.success(request, "Vínculos atualizados com sucesso!")
        return redirect('mimir:gerenciarPequenoGrupo', grupo_id=grupo.id)
        
    return render(request, 'mimir/pbl/gerenciarGrupo.html', {
        'grupo': grupo,
        'tutores': tutores,
        'alunos': alunos
    })

'''
# ==========================================
# DASHBOARDS DE ENTRADA (TUTOR E ALUNO)
# ==========================================

@login_required
def dashboardTutor(request):
    """Dashboard de entrada do Tutor."""
    if not request.user.isTutor() and not request.user.is_superuser:
        return redirect('mimir:acessoNegado')
        
    grupos = PequenoGrupo.objects.filter(tutor=request.user).order_by('-criado_em')
    return render(request, 'mimir/pbl/dashboardTutor.html', {'grupos': grupos})
'''
@login_required
def indexPblAluno(request):
    """Tela para o aluno escolher qual sessão de qual grupo ele quer acessar."""
    grupos = PequenoGrupo.objects.filter(alunos=request.user).order_by('-criado_em')
    return render(request, 'mimir/pbl/indexPblAluno.html', {'grupos': grupos})

@login_required
def dashboard_unificado(request):
    user = request.user
    
    # Identifica os papéis do usuário (Superusers têm acesso a tudo por padrão)
    is_superuser = user.is_superuser
    is_professor = is_superuser or user.groups.filter(name='Professor').exists()
    is_tutor = is_superuser or user.groups.filter(name='Tutor').exists()
    is_aluno = is_superuser or user.groups.filter(name='Aluno').exists()
    
    context = {
        'is_professor': is_professor,
        'is_tutor': is_tutor,
        'is_aluno': is_aluno,
    }
    
    # Coleta de dados exclusiva para a Área do PROFESSOR
    if is_professor:
        context['fontes_ativas'] = Fontes.objects.filter(user=user).count()
        context['problemas_criados'] = Problema.objects.filter(assunto__user=user).count()
        context['questoes_geradas'] = Pergunta.objects.filter(assunto__user=user).count()
        context['provas_criadas'] = Prova.objects.filter(assunto__user=user).count()
        context['ultimas_questoes'] = Pergunta.objects.all().order_by('-id')[:5]
        
    # Coleta de dados exclusiva para a Área do TUTOR
    if is_tutor:
        context['grupos_tutorados'] = PequenoGrupo.objects.filter(tutor=user).order_by('-criado_em')
        
    # Coleta de dados exclusiva para a Área do ALUNO
    if is_aluno:
        context['grupos_aluno'] = PequenoGrupo.objects.filter(alunos=user).order_by('-criado_em')
        
    return render(request, 'mimir/dashboard.html', context)

@login_required
@require_POST
def responderPerguntaAprendizado(request, pergunta_id):
    """View para um aluno ou tutor responder uma questão de aprendizado."""
    pergunta = get_object_or_404(PerguntaAprendizado, id=pergunta_id)
    texto_resposta = request.POST.get('resposta')
    
    # Validação: Só quem está no grupo pode responder
    if request.user in pergunta.grupo.alunos.all() or request.user == pergunta.grupo.tutor:
        if texto_resposta:
            pergunta.resposta = texto_resposta
            pergunta.respondida_por = request.user
            pergunta.respondida_em = timezone.now()
            pergunta.resolvida = True
            pergunta.save()
            messages.success(request, "Resposta registrada e compartilhada com o grupo!")
            
    return redirect('mimir:problemaSessaoAluno', grupo_id=pergunta.grupo.id, problema_id=pergunta.parte.problema.id)

@login_required
@require_POST
def gerarSugestaoConteudoCampo(request):
    """
    Aciona o LLM para sugerir/aprimorar o texto do campo atual, 
    usando TODO o restante do projeto como contexto de coerência.
    """
    try:
        data = json.loads(request.body)
        projeto_id = data.get('projeto_id')
        campo_id = data.get('campo_id')
        conteudo_atual = data.get('conteudo_atual', '')

        projeto = get_object_or_404(Projeto, id=projeto_id)
        campo_alvo = get_object_or_404(CampoTemplate, id=campo_id)

        # 1. Monta o Contexto Global (O que já foi escrito no projeto)
        # Busca todos os campos já preenchidos, EXCETO o que estamos editando agora
        outros_preenchimentos = PreenchimentoCampo.objects.filter(
            projeto=projeto
        ).exclude(campo=campo_alvo).select_related('campo').order_by('campo__ordem')
        
        contexto_projeto = ""
        for preenchimento in outros_preenchimentos:
            if preenchimento.valor.strip():
                # strip_tags remove o HTML do TinyMCE para economizar tokens do LLM
                texto_limpo = strip_tags(preenchimento.valor)
                contexto_projeto += f"--- {preenchimento.campo.label} ---\n{texto_limpo}\n\n"

        if not contexto_projeto.strip():
            contexto_projeto = "O projeto está no início. Nenhuma outra seção foi preenchida ainda."

        # 2. Definição do Prompt Contextualizado
        prompt_copiloto = ChatPromptTemplate.from_messages([
            ("system", (
                "Você é um consultor sênior de escrita de projetos científicos e propostas de fomento institucional "
                "para o edital: {titulo_edital}."
            )),
            ("user", """
            Sua tarefa é redigir ou aprimorar de forma altamente profissional o texto para a seção: '{nome_secao}'.
            
            Instruções e exigências do Edital para este campo específico: 
            {instrucoes_campo}
            
            -------------------------------------------------
            CONTEXTO GLOBAL DO PROJETO (Outras seções já escritas):
            {contexto_projeto}
            -------------------------------------------------
            
            Rascunho atual elaborado pela equipe para a seção '{nome_secao}' (pode estar vazio):
            {rascunho_atual}
            
            Diretrizes de geração:
            1. COERÊNCIA: Baseie sua argumentação no Contexto Global do Projeto.
            2. NÃO REPITA o que já foi dito detalhadamente nas outras seções, mas faça conexões inteligentes com elas para mostrar coesão.
            3. Escreva de forma técnica, impessoal e formal.
            4. IMPORTANTE: O sistema utiliza um editor Rich Text. Retorne a sua resposta formatada usando tags HTML básicas (como <p>, <strong>, <em>, <ul>, <li>). NÃO utilize formatação Markdown.
            """)
        ])

        # 3. Execução do LangChain
        cadeia = prompt_copiloto | get_llm() | StrOutputParser()
        
        resposta_ia = cadeia.invoke({
            "titulo_edital": projeto.edital.titulo,
            "nome_secao": campo_alvo.label,
            "instrucoes_campo": campo_alvo.instrucoes_originais,
            "contexto_projeto": contexto_projeto,
            "rascunho_atual": conteudo_atual if conteudo_atual.strip() else "Nenhum rascunho iniciado."
        })

        return JsonResponse({
            'success': True,
            'sugestao': resposta_ia
        })

    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
    
@login_required
def listarEditais(request):
    """Vitrine onde os pesquisadores visualizam as oportunidades e insights da IA."""
    agora = timezone.now()
    
    # Busca editais cujo prazo final é no futuro
    editais_abertos = Edital.objects.filter(data_limite__gte=agora).order_by('data_limite')
    
    # Traz os últimos 5 encerrados apenas para histórico
    editais_encerrados = Edital.objects.filter(data_limite__lt=agora).order_by('-data_limite')[:5]

    context = {
        'editais_abertos': editais_abertos,
        'editais_encerrados': editais_encerrados,
    }
    return render(request, 'mimir/pdi/listarEditais.html', context)

@login_required
@require_POST
def iniciarProjeto(request, edital_id):
    """Cria um rascunho de projeto vinculado ao edital e envia para a área de escrita."""
    edital = get_object_or_404(Edital, id=edital_id)

    # Verifica se o pesquisador já tem um rascunho ativo para este edital (evita duplicatas acidentais)
    projeto_existente = Projeto.objects.filter(edital=edital, proponente=request.user, status='rascunho').first()

    if projeto_existente:
        projeto = projeto_existente
        messages.info(request, "Você já possui um rascunho para este edital. Retomando de onde parou.")
    else:
        projeto = Projeto.objects.create(
            edital=edital,
            proponente=request.user,
            titulo=f"Nova Proposta - {edital.orgao_fomento}"
        )
        messages.success(request, "Rascunho de projeto iniciado! Vamos estruturar a sua proposta.")

    return redirect('mimir:editarProjeto', projeto_id=projeto.id)

@login_required
def editarProjeto(request, projeto_id):
    """Carrega o Workspace de edição do projeto com os campos exigidos."""
    projeto = get_object_or_404(Projeto, id=projeto_id)
    
    # Validação de Segurança: Apenas o proponente ou membros da equipe podem editar
    if request.user != projeto.proponente and request.user not in projeto.equipe.all():
        messages.error(request, "Acesso negado. Você não faz parte da equipe deste projeto.")
        return redirect('mimir:listarEditais')

    # Busca os campos de template exigidos pelo edital
    campos_template = CampoTemplate.objects.filter(documento__edital=projeto.edital).select_related('documento').order_by('documento', 'ordem')
    
    # Busca os documentos estáticos (uploads puros que ele precisará anexar depois)
    documentos_estaticos = DocumentoEdital.objects.filter(edital=projeto.edital, tipo='arquivo')

    # Busca o que já foi preenchido e converte em um dicionário para o template {campo_id: 'texto...'}
    respostas = PreenchimentoCampo.objects.filter(projeto=projeto)
    respostas_dict = {resp.campo_id: resp.valor for resp in respostas}

    referencias = projeto.referencias.all()

    comentarios = projeto.comentarios.filter(resolvido=False)

    context = {
        'projeto': projeto,
        'edital': projeto.edital,
        'campos_template': campos_template,
        'respostas_dict': respostas_dict,
        'documentos_estaticos': documentos_estaticos,
        'referencias': referencias,
        'comentarios': comentarios,
    }
    return render(request, 'mimir/pdi/editarProjeto.html', context)


@login_required
@require_POST
def salvarCampoProjeto(request):
    """View AJAX para salvamento em tempo real (Auto-save) dos campos."""
    try:
        data = json.loads(request.body)
        projeto = get_object_or_404(Projeto, id=data.get('projeto_id'))
        campo = get_object_or_404(CampoTemplate, id=data.get('campo_id'))
        valor = data.get('valor', '')

        # Segurança
        if request.user != projeto.proponente and request.user not in projeto.equipe.all():
            return JsonResponse({'success': False, 'message': 'Acesso negado'}, status=403)

        # Atualiza ou cria o registro do campo
        PreenchimentoCampo.objects.update_or_create(
            projeto=projeto,
            campo=campo,
            defaults={
                'valor': valor,
                'modificado_por': request.user
            }
        )
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

# Adicione esta nova função junto das outras de PD&I
@login_required
def meusProjetos(request):
    """Lista todos os projetos que o pesquisador iniciou ou foi convidado para a equipe."""
    
    projetos = Projeto.objects.filter(
        Q(proponente=request.user) | Q(equipe=request.user)
    ).distinct().order_by('-criado_em')
    
    return render(request, 'mimir/pdi/meusProjetos.html', {'projetos': projetos})

# NOVA VIEW AJAX:
@login_required
@require_POST
def adicionarReferenciaProjeto(request):
    """Salva uma nova referência no repositório do projeto."""
    try:
        data = json.loads(request.body)
        projeto = get_object_or_404(Projeto, id=data.get('projeto_id'))
        
        ref = ReferenciaProjeto.objects.create(
            projeto=projeto,
            citacao_curta=data.get('citacao_curta'),
            referencia_completa=data.get('referencia_completa')
        )
        return JsonResponse({
            'success': True, 
            'id': ref.id, 
            'citacao': ref.citacao_curta, 
            'completa': ref.referencia_completa
        })
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
    
# Adicione junto das outras views de PD&I
@login_required
def exportarProjetoPDF(request, projeto_id):
    """Gera a visualização limpa do projeto para exportação em PDF."""
    projeto = get_object_or_404(Projeto, id=projeto_id)
    
    # Segurança
    if request.user != projeto.proponente and request.user not in projeto.equipe.all():
        messages.error(request, "Acesso negado.")
        return redirect('mimir:listarEditais')

    # 1. Busca os campos ordenados pela estrutura do Edital
    campos_template = CampoTemplate.objects.filter(
        documento__edital=projeto.edital
    ).select_related('documento').order_by('documento', 'ordem')

    # 2. Busca as respostas e cria um dicionário para acesso rápido
    preenchimentos = PreenchimentoCampo.objects.filter(projeto=projeto)
    respostas_dict = {p.campo_id: p.valor for p in preenchimentos}

    # 3. Estrutura a lista final mesclando o Título do Campo com o Texto Salvo
    conteudo_projeto = []
    for campo in campos_template:
        valor = respostas_dict.get(campo.id, '<p class="text-muted fst-italic">Não preenchido.</p>')
        conteudo_projeto.append({
            'titulo': f"{campo.ordem}. {campo.label}",
            'documento': campo.documento.nome,
            'texto': valor
        })

    # 4. Busca as referências em ordem alfabética (Padrão ABNT)
    referencias = None

    context = {
        'projeto': projeto,
        'edital': projeto.edital,
        'conteudo_projeto': conteudo_projeto,
        'referencias': referencias,
    }
    
    return render(request, 'mimir/pdi/exportar_pdf.html', context)

@login_required
def buscarUsuariosAjax(request):
    try:
        termo = request.GET.get('q', '').strip()
        if len(termo) < 3:
            return JsonResponse({'usuarios': []})
            
        # Busca por qualquer usuário (Professor ou Aluno) ignorando o próprio usuário logado
        usuarios = User.objects.filter(
            Q(first_name__icontains=termo) | 
            Q(last_name__icontains=termo) | 
            Q(username__icontains=termo) |
            Q(email__icontains=termo)
        ).exclude(id=request.user.id)[:10]
        
        data = []
        for u in usuarios:
            # Identifica o papel baseado nos booleanos do seu custom user (isProfessor / isAluno)
            papel = 'Pesquisador'
            cor_badge = 'bg-secondary'
            
            if getattr(u, 'isProfessor', False):
                papel = 'Professor'
                cor_badge = 'bg-success'
            elif getattr(u, 'isAluno', False):
                papel = 'Aluno'
                cor_badge = 'bg-info text-dark'
                
            data.append({
                'id': u.id, 
                'nome': u.get_full_name() or u.username, 
                'email': u.email or 'Sem e-mail',
                'papel': papel,
                'cor_badge': cor_badge
            })
            
        return JsonResponse({'usuarios': data})
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'erro_interno': str(e)}, status=500)

@login_required
@require_POST
def gerenciarEquipeProjeto(request):
    """Adiciona ou remove um usuário da equipe do projeto."""
    try:
        data = json.loads(request.body)
        projeto = get_object_or_404(Projeto, id=data.get('projeto_id'))
        
        # Apenas o DONO (proponente) pode alterar a equipe
        if request.user != projeto.proponente:
            return JsonResponse({'success': False, 'message': 'Apenas o proponente pode gerenciar a equipe.'}, status=403)
            
        usuario_alvo = get_object_or_404(User, id=data.get('usuario_id'))
        acao = data.get('acao')

        if acao == 'adicionar':
            projeto.equipe.add(usuario_alvo)
            mensagem = f"{usuario_alvo.get_full_name() or usuario_alvo.username} adicionado(a) à equipe."
        elif acao == 'remover':
            projeto.equipe.remove(usuario_alvo)
            mensagem = "Membro removido da equipe."
        else:
            return JsonResponse({'success': False, 'message': 'Ação inválida.'}, status=400)
            
        return JsonResponse({'success': True, 'message': mensagem})
        
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
    
@login_required
def adicionarComentarioRevisao(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            projeto_id = data.get('projeto_id')
            
            from .models import Projeto, ComentarioRevisao
            projeto = Projeto.objects.get(id=projeto_id)
            
            is_proponente = (request.user == projeto.proponente)
            is_equipe = projeto.equipe.filter(id=request.user.id).exists()
            
            if is_proponente or is_equipe:
                novo_comentario = ComentarioRevisao.objects.create(
                    projeto=projeto,
                    campo_id=data.get('campo_id'),
                    revisor=request.user,
                    marker_id=data.get('marker_id'),
                    texto_selecionado=data.get('texto_selecionado'),
                    texto_comentario=data.get('texto_comentario')
                )
                
                # Identifica o papel para renderizar o card dinamicamente no front
                papel = 'Pesquisador'
                cor_badge = 'bg-secondary'
                if getattr(request.user, 'isProfessor', False):
                    papel = 'Professor'
                    cor_badge = 'bg-success'
                elif getattr(request.user, 'isAluno', False):
                    papel = 'Aluno'
                    cor_badge = 'bg-info text-dark'
                
                return JsonResponse({
                    'success': True,
                    'id': novo_comentario.id,
                    'revisor': request.user.get_full_name() or request.user.username,
                    'data': novo_comentario.criado_em.strftime("%d/%m %H:%M"),
                    'papel': papel,
                    'cor_badge': cor_badge
                })
            else:
                return JsonResponse({'success': False, 'message': 'Acesso negado ao projeto.'})
                
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})
    return JsonResponse({'success': False, 'message': 'Método inválido.'})
    
@login_required
def resolverComentarioRevisao(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            comentario_id = data.get('comentario_id')
            
            from .models import ComentarioRevisao
            comentario = ComentarioRevisao.objects.get(id=comentario_id)
            
            # CORREÇÃO: Pega o projeto diretamente do comentário (e não do campo)
            projeto = comentario.projeto 
            
            # Quem pode arquivar? O Proponente, o Revisor que criou, OU qualquer membro da Equipe
            is_proponente = (request.user == projeto.proponente)
            is_revisor = (request.user == comentario.revisor)
            is_equipe = projeto.equipe.filter(id=request.user.id).exists()
            
            if is_proponente or is_revisor or is_equipe:
                comentario.resolvido = True 
                comentario.save()
                return JsonResponse({'success': True})
            else:
                return JsonResponse({
                    'success': False, 
                    'message': 'Você não tem permissão para arquivar este comentário.'
                })
                
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})
    return JsonResponse({'success': False, 'message': 'Método inválido.'})

@login_required
def editarReferenciaProjeto(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            ref_id = data.get('ref_id')
            citacao_curta = data.get('citacao_curta')
            referencia_completa = data.get('referencia_completa')
            
            # Substitua 'ReferenciaProjeto' pelo nome exato do seu Modelo de Citações do Projeto
            from .models import ReferenciaProjeto 
            ref = ReferenciaProjeto.objects.get(id=ref_id)
            projeto = ref.projeto
            
            # Permissão: Proponente ou Membro da Equipe
            if request.user == projeto.proponente or projeto.equipe.filter(id=request.user.id).exists():
                ref.citacao_curta = citacao_curta
                ref.referencia_completa = referencia_completa
                ref.save()
                return JsonResponse({'success': True, 'citacao': citacao_curta, 'completa': referencia_completa})
            return JsonResponse({'success': False, 'message': 'Acesso negado.'})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})
    return JsonResponse({'success': False, 'message': 'Método inválido.'})

@login_required
def deletarReferenciaProjeto(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            ref_id = data.get('ref_id')
            
            from .models import ReferenciaProjeto
            ref = ReferenciaProjeto.objects.get(id=ref_id)
            projeto = ref.projeto
            
            # Permissão: Proponente ou Membro da Equipe
            if request.user == projeto.proponente or projeto.equipe.filter(id=request.user.id).exists():
                ref.delete()
                return JsonResponse({'success': True})
            return JsonResponse({'success': False, 'message': 'Acesso negado.'})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})
    return JsonResponse({'success': False, 'message': 'Método inválido.'})

@login_required
def exportarCorrecaoPDF(request, prova_aluno_id):
    # 1. Busca a prova com segurança (retorna 404 se não existir)
    prova_aluno = get_object_or_404(ProvaAluno, id=prova_aluno_id)
    
    # 2. Trava de Segurança: Só o dono da prova ou um professor podem exportar
    is_dono = request.user == prova_aluno.aluno
    is_professor = getattr(request.user, 'isProfessor', False)
    
    if not (is_dono or is_professor):
        return HttpResponse("Acesso negado. Você não tem permissão para visualizar esta prova.", status=403)

    # 3. Lógica para cruzar a Pergunta com a Resposta do Aluno
    perguntas_com_respostas = []
    
    # Pega todas as perguntas da prova
    todas_perguntas = prova_aluno.aplicacao_prova.prova.perguntas.all()
    
    for pergunta in todas_perguntas:
        # Tenta achar a resposta específica deste aluno para esta pergunta
        resposta = RespostaAluno.objects.filter(
            prova_aluno=prova_aluno,
            pergunta=pergunta
        ).first()
        
        # Monta o dicionário no exato formato que o template HTML espera
        perguntas_com_respostas.append({
            'pergunta': pergunta,
            'resposta': resposta,
        })
    
    # 4. Monta o contexto para o template
    context = {
        'prova_aluno': prova_aluno,
        'perguntas_com_respostas': perguntas_com_respostas,
    }
    
    # 5. Renderiza o HTML limpo
    html_string = render_to_string('mimir/pdf_template_correcao.html', context)
    
    # 6. Converte para PDF
    html = HTML(string=html_string, base_url=request.build_absolute_uri())
    pdf_file = html.write_pdf()
    
    # 7. Força o download do arquivo no navegador
    response = HttpResponse(pdf_file, content_type='application/pdf')
    nome_arquivo = f"Correcao_Prova_{prova_aluno.aluno.username}.pdf"
    response['Content-Disposition'] = f'inline; filename="{nome_arquivo}"'
    
    return response

@login_required
def importarBibtexProjeto(request, projeto_id):
    # 1. Procura o projeto e valida a existência
    projeto = get_object_or_404(Projeto, id=projeto_id)
    
    # 2. Validação de segurança de acesso da equipa
    if request.user != projeto.proponente and not projeto.equipe.filter(id=request.user.id).exists():
        return HttpResponseForbidden("Não tem permissão para alterar este projeto.")

    if request.method == 'POST' and request.FILES.get('arquivo_bib'):
        ficheiro_bib = request.FILES['arquivo_bib']
        
        # Garante que o ficheiro tem a extensão correta
        if not ficheiro_bib.name.endswith('.bib'):
            messages.error(request, "Por favor, envie um ficheiro válido com a extensão .bib")
            return redirect('mimir:editarProjeto', projeto_id=projeto.id)
            
        try:
            # Descodifica o fluxo de bytes para string texto puro
            conteudo_texto = ficheiro_bib.read().decode('utf-8')
            
            # Carrega o parser do BibTeX
            base_dados_bib = bibtexparser.loads(conteudo_texto)
            
            referencias_criadas = 0
            
            # Dicionário de mapeamento de tipos BibTeX para as opções do Django
            mapa_tipos = {
                'article': 'article',
                'book': 'book',
                'inproceedings': 'inproceedings',
                'conference': 'inproceedings',
                'misc': 'misc',
                'phdthesis': 'misc',
                'mastersthesis': 'misc',
            }
            
            for entry in base_dados_bib.entries:
                chave = entry.get('ID', '').strip()
                tipo_original = entry.get('ENTRYTYPE', 'misc').lower()
                
                # Captura os dados limpando espaços residuais
                autores = entry.get('author', 'Autor Desconhecido').strip()
                titulo = entry.get('title', 'Sem Título').strip()
                ano = entry.get('year', '').strip()[:4]
                
                # Identifica o veículo de publicação de acordo com o tipo de entrada
                revista_evento = entry.get('journal', entry.get('booktitle', entry.get('publisher', '')))
                
                volume = entry.get('volume', '')
                paginas = entry.get('pages', '')
                doi = entry.get('doi', '')
                
                # Evita duplicar referências com a mesma chave dentro do mesmo projeto
                if not ReferenciaProjeto.objects.filter(projeto=projeto, chave_bibtex=chave).exists():
                    ReferenciaProjeto.objects.create(
                        projeto=projeto,
                        chave_bibtex=chave,
                        tipo=mapa_tipos.get(tipo_original, 'misc'),
                        autores=autores,
                        titulo=titulo,
                        ano=ano,
                        revista_evento=revista_evento,
                        volume=volume,
                        paginas=paginas,
                        doi=doi
                    )
                    referencias_criadas += 1
            
            if referencias_criadas > 0:
                messages.success(request, f'Sucesso! {referencias_criadas} referências foram importadas do ficheiro BibTeX.')
            else:
                messages.info(request, 'Nenhuma referência nova foi adicionada (chaves duplicadas detetadas).')
                
        except Exception as e:
            messages.error(request, f"Erro ao processar o ficheiro estruturado: {str(e)}")
            
        return redirect('mimir:editarProjeto', projeto_id=projeto.id)
        
    messages.error(request, "Nenhum ficheiro foi carregado.")
    return redirect('mimir:editarProjeto', projeto_id=projeto.id)

@login_required
def exportarBibtexProjeto(request, projeto_id):
    # 1. Procura o projeto e valida a existência
    projeto = get_object_or_404(Projeto, id=projeto_id)
    
    # 2. Validação de segurança para a equipa do projeto
    if request.user != projeto.proponente and not projeto.equipe.filter(id=request.user.id).exists():
        return HttpResponseForbidden("Não tem permissão para exportar os dados deste projeto.")

    # 3. Procura as referências já estruturadas
    referencias = projeto.referencias.all()
    
    bibtex_content = "% -----------------------------------------------------\n"
    bibtex_content += f"% Repositório de Citações do Projeto: {projeto.titulo}\n"
    bibtex_content += "% Gerado automaticamente pelo Mimir (Formato Estruturado)\n"
    bibtex_content += "% -----------------------------------------------------\n\n"
    
    for ref in referencias:
        # Utiliza a chave guardada ou gera um fallback seguro caso esteja vazia
        chave = ref.chave_bibtex.strip() if ref.chave_bibtex else f"ref_{ref.id}"
        tipo_entrada = ref.tipo if ref.tipo else "misc"
        
        # Inicia a entrada BibTeX estruturada (ex: @article{chave,)
        bibtex_content += f"@{tipo_entrada}{{{chave},\n"
        bibtex_content += f"  author = {{{ref.autores}}},\n"
        bibtex_content += f"  title = {{{ref.titulo}}},\n"
        bibtex_content += f"  year = {{{ref.ano}}},\n"
        
        # Mapeia dinamicamente o veículo de publicação conforme o tipo do BibTeX
        if ref.revista_evento:
            if tipo_entrada == 'article':
                bibtex_content += f"  journal = {{{ref.revista_evento}}},\n"
            elif tipo_entrada == 'inproceedings':
                bibtex_content += f"  booktitle = {{{ref.revista_evento}}},\n"
            else:
                bibtex_content += f"  publisher = {{{ref.revista_evento}}},\n"
                
        # Adiciona os campos opcionais apenas se estiverem preenchidos no banco
        if ref.volume:
            bibtex_content += f"  volume = {{{ref.volume}}},\n"
        if ref.paginas:
            bibtex_content += f"  pages = {{{ref.paginas}}},\n"
        if ref.doi:
            bibtex_content += f"  doi = {{{ref.doi}}},\n"
            
        # Fecha o bloco da referência
        bibtex_content += "}\n\n"

    # 4. Configuração da resposta HTTP para download de ficheiro de dados
    response = HttpResponse(bibtex_content, content_type='application/x-bibtex')
    
    # Normaliza o nome do ficheiro .bib removendo caracteres especiais
    nome_ficheiro = re.sub(r'\W+', '_', projeto.titulo.lower()).strip('_')
    response['Content-Disposition'] = f'attachment; filename="referencias_{nome_ficheiro}.bib"'
    
    return response
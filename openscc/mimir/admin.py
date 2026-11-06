from django.contrib import admin
from django.contrib import messages
from .models import *

# IMPORTANTE: Importe a função diretamente do arquivo onde você a criou 
# (substitua 'commons.services' pelo local correto caso tenha colocado em outro arquivo)
from commons.services import processar_edital_business_logic, get_llm

admin.site.register(Assunto)
admin.site.register(TiposDePergunta)

# ==========================================
# AÇÕES CUSTOMIZADAS DO ADMIN
# ==========================================

@admin.action(description="Reprocessar Edital(is) no motor LLM (IA)")
def reprocessar_editais_ia(modeladmin, request, queryset):
    """Ação para enviar os editais selecionados para processamento síncrono da IA."""
    sucesso_count = 0
    for edital in queryset:
        try:
            # Chama a função de negócio diretamente, aguardando a resposta da IA
            # Observação: se a sua função exige passar o LLM como parâmetro extra, 
            # não se esqueça de importá-lo e passá-lo aqui.
            processar_edital_business_logic(edital.id, user=request.user)
            sucesso_count += 1
        except Exception as e:
            messages.error(request, f"Erro ao processar o edital '{edital.titulo}': {str(e)}")
    
    if sucesso_count > 0:
        messages.success(request, f"{sucesso_count} edital(is) processado(s) com sucesso!")

# ==========================================
# INLINES (Formulários Aninhados)
# ==========================================

class CampoTemplateInline(admin.TabularInline):
    """Permite adicionar os campos diretamente na tela do Documento"""
    model = CampoTemplate
    extra = 1
    classes = ['collapse']
    fields = ('ordem', 'label', 'tipo_campo', 'instrucoes_originais')

class DocumentoEditalInline(admin.StackedInline):
    """Permite adicionar documentos diretamente na tela do Edital"""
    model = DocumentoEdital
    extra = 0
    fields = ('nome', 'tipo', 'arquivo_modelo')

# ==========================================
# REGISTRO DOS MODELOS PRINCIPAIS
# ==========================================

@admin.register(DocumentoEdital)
class DocumentoEditalAdmin(admin.ModelAdmin):
    list_display = ('nome', 'edital', 'tipo')
    list_filter = ('tipo', 'edital__orgao_fomento')
    search_fields = ('nome', 'edital__titulo')
    inlines = [CampoTemplateInline]
    
    fieldsets = (
        ('Informações Básicas', {
            'fields': ('edital', 'nome', 'tipo')
        }),
        ('Upload Físico (Se for tipo Arquivo)', {
            'fields': ('arquivo_modelo',),
            'classes': ('collapse',)
        }),
    )

@admin.register(Edital)
class EditalAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'orgao_fomento', 'data_limite', 'criado_em')
    list_filter = ('orgao_fomento', 'data_publicacao')
    search_fields = ('titulo', 'orgao_fomento')
    readonly_fields = ('resumo_llm', 'insights_llm')
    inlines = [DocumentoEditalInline]
    
    actions = [reprocessar_editais_ia]
    
    fieldsets = (
        ('Dados do Fomento', {
            'fields': ('orgao_fomento', 'titulo', 'arquivo_edital')
        }),
        ('Prazos', {
            'fields': ('data_publicacao', 'data_limite')
        }),
        ('Processamento de IA (Gerado Automaticamente)', {
            'fields': ('resumo_llm', 'insights_llm'),
            'classes': ('collapse',)
        }),
    )

    def save_model(self, request, obj, form, change):
        is_new = obj.pk is None 
        super().save_model(request, obj, form, change) 

        if is_new:
            try:
                # Processamento síncrono no momento da criação
                processar_edital_business_logic(obj.id, user=request.user)
                messages.success(request, "O PDF do edital foi lido e processado pela IA com sucesso!")
            except Exception as e:
                messages.error(request, f"O Edital foi salvo, mas houve uma falha ao processar com a IA: {e}")


# ==========================================
# GESTÃO EM TEMPO REAL DE MODELOS LLM (IA)
# ==========================================

from django.urls import path as admin_path, reverse
from django.shortcuts import redirect as admin_redirect
from django.utils.html import format_html


@admin.action(description="Definir modelo selecionado como ATIVO (desativa os demais)")
def ativar_modelo_llm_action(modeladmin, request, queryset):
    garantir_tabela_configuracao_llm()
    if queryset.count() != 1:
        messages.warning(request, "Selecione exatamente 1 modelo para definir como o único ativo do sistema.")
        return
    escolhido = queryset.first()
    escolhido.ativo = True
    escolhido.save()
    messages.success(
        request,
        f"Modelo '{escolhido.nome_exibicao}' ({escolhido.model_id}) ativado em tempo real! "
        f"Todas as novas requisições ao LLM já estão utilizando este modelo."
    )


@admin.register(ConfiguracaoModeloLLM)
class ConfiguracaoModeloLLMAdmin(admin.ModelAdmin):
    list_display = (
        'nome_exibicao',
        'provedor',
        'model_id',
        'temperatura',
        'status_ativo_badge',
        'botao_ativar_tempo_real',
        'atualizado_em',
    )
    list_filter = ('provedor', 'ativo')
    search_fields = ('nome_exibicao', 'model_id', 'descricao')
    actions = [ativar_modelo_llm_action]

    fieldsets = (
        ('Identificação e Status em Tempo Real', {
            'fields': ('nome_exibicao', 'provedor', 'model_id', 'ativo', 'descricao'),
            'description': 'Ao marcar "Ativo (Em Uso)" neste modelo, todos os demais modelos cadastrados serão automaticamente desativados.',
        }),
        ('Parâmetros de Inferência e Conexão', {
            'fields': ('temperatura', 'max_retries', 'base_url', 'api_key_override'),
        }),
    )

    def get_queryset(self, request):
        garantir_tabela_configuracao_llm()
        return super().get_queryset(request)

    def changelist_view(self, request, extra_context=None):
        garantir_tabela_configuracao_llm()
        return super().changelist_view(request, extra_context=extra_context)

    def add_view(self, request, form_url='', extra_context=None):
        garantir_tabela_configuracao_llm()
        return super().add_view(request, form_url=form_url, extra_context=extra_context)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            admin_path(
                'ativar-agora/<int:modelo_id>/',
                self.admin_site.admin_view(self.ativar_modelo_direto_view),
                name='mimir_configuracaomodelollm_ativar_agora',
            ),
        ]
        return custom_urls + urls

    def ativar_modelo_direto_view(self, request, modelo_id):
        garantir_tabela_configuracao_llm()
        modelo = ConfiguracaoModeloLLM.objects.filter(pk=modelo_id).first()
        if modelo:
            modelo.ativo = True
            modelo.save()
            self.message_user(
                request,
                f"Modelo '{modelo.nome_exibicao}' ({modelo.model_id}) ativado com sucesso em tempo real!",
                level=messages.SUCCESS,
            )
        changelist_url = reverse('admin:mimir_configuracaomodelollm_changelist')
        return admin_redirect(changelist_url)

    @admin.display(description="Status Atual")
    def status_ativo_badge(self, obj):
        if obj.ativo:
            return format_html(
                '<span style="background:#16a34a; color:#fff; padding:4px 10px; border-radius:12px; font-weight:700; font-size:11px;">'
                '● ATIVO EM USO</span>'
            )
        return format_html(
            '<span style="background:#e5e7eb; color:#4b5563; padding:4px 10px; border-radius:12px; font-weight:600; font-size:11px;">'
            'Inativo</span>'
        )

    @admin.display(description="Troca em Tempo Real")
    def botao_ativar_tempo_real(self, obj):
        if obj.ativo:
            return format_html(
                '<span style="color:#16a34a; font-weight:bold; font-size:12px;">✓ Modelo Atual</span>'
            )
        url = reverse('admin:mimir_configuracaomodelollm_ativar_agora', args=[obj.pk])
        return format_html(
            '<a class="button" href="{}" style="background:#2563eb; color:#fff; padding:4px 10px; border-radius:5px; font-weight:600; text-decoration:none;">'
            '⚡ Ativar Este Modelo</a>',
            url,
        )


@admin.register(LLMLog)
class LLMLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'model_used', 'endpoint', 'status', 'duration_ms', 'user')
    list_filter = ('status', 'model_used', 'endpoint')
    search_fields = ('prompt', 'response', 'model_used', 'endpoint')
    readonly_fields = ('user', 'prompt', 'response', 'model_used', 'tokens_input', 'tokens_output', 'duration_ms', 'status', 'error_message', 'endpoint', 'created_at')

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
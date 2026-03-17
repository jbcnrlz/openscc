from django.http import HttpResponseRedirect
from django.contrib import admin, messages
from .models import *
from django.utils.html import format_html
import json
from django import forms

@admin.action(description="Visualizar lista de inscritos")
def visualizeSubscription(modeladmin,request,queryset):
    selected = queryset.values_list("pk",flat=True)
    return HttpResponseRedirect("/inscritos/?ids=%s" % (",".join(str(pk) for pk in selected)))

class ConferenciaAdmin(admin.ModelAdmin):
    prepopulated_fields = {"slug" : ["nome"]}

class AtividadeAdmin(admin.ModelAdmin):
    exclude = ["participantes"]
    actions = [visualizeSubscription]



admin.site.register(Autores)
admin.site.register(Artigo)
admin.site.register(EnderecoInstituicao)
admin.site.register(Instituicoes)
admin.site.register(Conferencia,ConferenciaAdmin)
admin.site.register(Palestrante)
admin.site.register(TipoAtividade)
admin.site.register(Atividade,AtividadeAdmin)

class CertificadoInline(admin.TabularInline):
    model = Certificado
    extra = 0
    fields = ('codigo_validacao', 'participante', 'tipo_certificado', 'data_atividade', 'emitido')
    readonly_fields = ('codigo_validacao',)
    can_delete = False
    show_change_link = True
    
    def has_add_permission(self, request, obj):
        return False


@admin.register(LayoutCertificado)
class LayoutCertificadoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'conferencia', 'padrao', 'ativo', 'instituicoes_count', 'preview_colors','cidade')
    list_filter = ('conferencia', 'padrao', 'ativo', 'layout_logos')
    search_fields = ('nome', 'conferencia__nome', 'conferencia__sigla')
    list_editable = ('padrao', 'ativo')
    filter_horizontal = ('instituicoes',)
    readonly_fields = ['instituicoes_list']
    
    fieldsets = (
        ('Informações Básicas', {
            'fields': ('nome', 'conferencia', 'padrao', 'ativo', 'cidade')
        }),
        
        ('Instituições Associadas', {
            'fields': ('instituicoes', 'instituicoes_list'),
            'description': 'Selecione as instituições cujos logos aparecerão no certificado.'
        }),
        
        ('Configurações de Exibição', {
            'fields': (
                'mostrar_logo_evento', 
                'mostrar_logo_instituicoes', 
                'mostrar_logos_personalizados',
                'layout_logos',
            ),
            'description': 'Controle quais logos serão exibidos e como serão organizados.'
        }),
        
        ('Ordem dos Logos', {
            'fields': ('ordem_exibicao',),
            'description': 'Formato JSON. Exemplo: ["evento", "instituicao_1", "personalizado_0"]'
        }),
        
        ('Design do Certificado', {
            'fields': (
                'imagem_fundo', 
                'cor_fundo', 
                'cor_texto_titulo', 
                'cor_texto_corpo',
                'fonte_titulo', 
                'fonte_corpo'
            )
        }),
        
        ('Conteúdo do Certificado', {
            'fields': ('texto_cabecalho', 'texto_rodape', 'carga_horaria_padrao'),
            'description': 'Use variáveis: {nome}, {atividade}, {conferencia}, {sigla}, {data}, {carga_horaria}, {tipo_atividade}, {tipo_certificado}, {instituicoes}, {instituicoes_siglas}'
        }),
        
        ('Assinaturas', {
            'fields': ('assinaturas',),
            'description': 'Formato JSON. Exemplo: [{"nome": "João Silva", "cargo": "Coordenador", "imagem": "/media/assinaturas/joao.jpg"}]'
        }),
        
        ('Logos Personalizados', {
            'fields': ('logos_personalizados',),
            'description': 'Formato JSON. Exemplo: [{"nome": "Parceiro", "url": "/media/logos/parceiro.jpg", "tamanho": "medio"}]'
        }),       
    )
    
    # Widgets personalizados para campos JSON
    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name in ['assinaturas', 'logos_personalizados', 'ordem_exibicao']:
            kwargs['widget'] = forms.Textarea(attrs={
                'rows': 5, 
                'cols': 80,
                'style': 'font-family: monospace; font-size: 12px;'
            })
        return super().formfield_for_dbfield(db_field, request, **kwargs)
    
    def preview_colors(self, obj):
        """Mostra uma prévia das cores no admin"""
        return format_html(
            '<div style="display: flex; gap: 5px;">'
            '<div style="width: 20px; height: 20px; background-color: {}; border: 1px solid #ccc;" title="Fundo: {}"></div>'
            '<div style="width: 20px; height: 20px; background-color: {}; border: 1px solid #ccc;" title="Texto Título: {}"></div>'
            '<div style="width: 20px; height: 20px; background-color: {}; border: 1px solid #ccc;" title="Texto Corpo: {}"></div>'
            '</div>',
            obj.cor_fundo or '#FFFFFF', 
            obj.cor_fundo or '#FFFFFF',
            obj.cor_texto_titulo or '#000000', 
            obj.cor_texto_titulo or '#000000',
            obj.cor_texto_corpo or '#333333', 
            obj.cor_texto_corpo or '#333333'
        )
    preview_colors.short_description = 'Cores'
    
    def instituicoes_count(self, obj):
        count = obj.instituicoes.count()
        return format_html(
            '<span class="badge" style="background-color: {}; color: white; padding: 2px 8px; border-radius: 10px;">{}</span>',
            '#28a745' if count > 0 else '#6c757d',
            count
        )
    instituicoes_count.short_description = 'Instituições'
    
    def instituicoes_list(self, obj):
        """Lista as instituições selecionadas"""
        if not obj.pk:
            return "Salve o layout para ver a lista de instituições."
        
        instituicoes = obj.instituicoes.all()
        if not instituicoes:
            return "Nenhuma instituição selecionada."
        
        html = '<ul style="margin-left: 20px;">'
        for instituicao in instituicoes:
            has_logo = "✅" if instituicao.logo else "❌"
            html += f'<li>{has_logo} {instituicao.nome}'
            if instituicao.sigla:
                html += f' ({instituicao.sigla})'
            html += '</li>'
        html += '</ul>'
        return format_html(html)
    instituicoes_list.short_description = 'Lista de Instituições'
    
    def json_validator(self, obj):
        """Validador de JSON para ajudar o usuário"""
        return format_html(
            '<div style="background-color: #f8f9fa; padding: 10px; border-radius: 5px; margin-bottom: 10px;">'
            '<strong>Dica:</strong> Use <a href="https://jsonformatter.org" target="_blank">JSON Formatter</a> '
            'para validar seus JSONs antes de colar aqui.'
            '</div>'
        )
    json_validator.short_description = 'Validação de JSON'
    
    def preview_certificado(self, obj):
        """Pré-visualização do layout do certificado"""
        if not obj.pk:
            return "Salve o layout para ver a pré-visualização."
        
        try:
            # Contar elementos de forma segura
            assinaturas = obj.get_assinaturas_formatadas()
            assinaturas_count = len(assinaturas) if isinstance(assinaturas, list) else 0
            
            logos = obj.get_todos_logos_ordenados()
            logos_count = len(logos) if isinstance(logos, list) else 0
            
            instituicoes_count = obj.instituicoes.count()
            
            # HTML de pré-visualização
            html = f"""
            <div style="border: 2px dashed #ccc; padding: 20px; margin: 10px 0; background-color: {obj.cor_fundo or '#FFFFFF'};">
                <h3 style="font-family: {obj.fonte_titulo or "'Times New Roman', serif"}; color: {obj.cor_texto_titulo or '#000000'}; text-align: center;">
                    CERTIFICADO (Pré-visualização)
                </h3>
                
                <div style="font-family: {obj.fonte_corpo or "'Arial', sans-serif"}; color: {obj.cor_texto_corpo or '#333333'}; padding: 20px;">
                    <p><strong>Conteúdo do certificado:</strong></p>
                    <div style="background-color: rgba(255,255,255,0.7); padding: 10px; border-radius: 5px;">
                        {obj.texto_cabecalho[:200] if obj.texto_cabecalho else 'Sem texto configurado'}...
                    </div>
                    
                    <div style="margin-top: 20px;">
                        <p><strong>Elementos configurados:</strong></p>
                        <ul>
                            <li>Instituições: {instituicoes_count}</li>
                            <li>Logos: {logos_count}</li>
                            <li>Assinaturas: {assinaturas_count}</li>
                            <li>Layout dos logos: {obj.get_layout_logos_display() if obj.layout_logos else 'Horizontal'}</li>
                            <li>Carga horária padrão: {obj.carga_horaria_padrao if obj.carga_horaria_padrao else '2.00'} horas</li>
                        </ul>
                    </div>
                    
                    <div style="margin-top: 20px;">
                        <p><strong>Exibição de logos:</strong></p>
                        <ul>
                            <li>Logo do evento: {'✅ Sim' if obj.mostrar_logo_evento else '❌ Não'}</li>
                            <li>Logos das instituições: {'✅ Sim' if obj.mostrar_logo_instituicoes else '❌ Não'}</li>
                            <li>Logos personalizados: {'✅ Sim' if obj.mostrar_logos_personalizados else '❌ Não'}</li>
                        </ul>
                    </div>
                </div>
            </div>
            
            <div style="margin-top: 20px; padding: 10px; background-color: #f8f9fa; border-radius: 5px;">
                <h4>Variáveis disponíveis no texto:</h4>
                <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px;">
                    <code style="background-color: #e9ecef; padding: 2px 5px; border-radius: 3px;">{'nome'}</code>
                    <code style="background-color: #e9ecef; padding: 2px 5px; border-radius: 3px;">{'atividade'}</code>
                    <code style="background-color: #e9ecef; padding: 2px 5px; border-radius: 3px;">{'conferencia'}</code>
                    <code style="background-color: #e9ecef; padding: 2px 5px; border-radius: 3px;">{'sigla'}</code>
                    <code style="background-color: #e9ecef; padding: 2px 5px; border-radius: 3px;">{'data'}</code>
                    <code style="background-color: #e9ecef; padding: 2px 5px; border-radius: 3px;">{'carga_horaria'}</code>
                    <code style="background-color: #e9ecef; padding: 2px 5px; border-radius: 3px;">{'tipo_atividade'}</code>
                    <code style="background-color: #e9ecef; padding: 2px 5px; border-radius: 3px;">{'tipo_certificado'}</code>
                    <code style="background-color: #e9ecef; padding: 2px 5px; border-radius: 3px;">{'instituicoes'}</code>
                    <code style="background-color: #e9ecef; padding: 2px 5px; border-radius: 3px;">{'instituicoes_siglas'}</code>
                </div>
            </div>
            """
            
            return format_html(html)
            
        except Exception as e:
            return format_html(
                '<div style="background-color: #f8d7da; color: #721c24; padding: 15px; border-radius: 5px; border: 1px solid #f5c6cb;">'
                '<strong>Erro na pré-visualização:</strong><br>'
                f'{str(e)}<br><br>'
                '<small>Verifique os campos JSON e tente novamente.</small>'
                '</div>'
            )
    preview_certificado.short_description = 'Pré-visualização do Layout'
    
    # Ações personalizadas
    actions = ['marcar_como_padrao', 'duplicar_layout']
    
    def marcar_como_padrao(self, request, queryset):
        """Marca o layout selecionado como padrão para sua conferência"""
        for layout in queryset:
            # Primeiro desmarca todos os padrões da mesma conferência
            if layout.conferencia:
                LayoutCertificado.objects.filter(
                    conferencia=layout.conferencia,
                    padrao=True
                ).update(padrao=False)
                
                # Marca o selecionado como padrão
                layout.padrao = True
                layout.save()
        
        count = queryset.count()
        self.message_user(request, f"{count} layout(s) marcado(s) como padrão.")
    marcar_como_padrao.short_description = "Marcar como layout padrão"
    
    def duplicar_layout(self, request, queryset):
        """Duplica o layout selecionado"""
        for layout in queryset:
            # Cria uma cópia
            novo_layout = LayoutCertificado.objects.create(
                nome=f"{layout.nome} (Cópia)",
                conferencia=layout.conferencia,
                ativo=layout.ativo,
                padrao=False,  # Cópias não são padrão
                imagem_fundo=layout.imagem_fundo,
                cor_fundo=layout.cor_fundo,
                cor_texto_titulo=layout.cor_texto_titulo,
                cor_texto_corpo=layout.cor_texto_corpo,
                fonte_titulo=layout.fonte_titulo,
                fonte_corpo=layout.fonte_corpo,
                texto_cabecalho=layout.texto_cabecalho,
                texto_rodape=layout.texto_rodape,
                assinaturas=layout.assinaturas,
                logos_personalizados=layout.logos_personalizados,
                ordem_exibicao=layout.ordem_exibicao,
                carga_horaria_padrao=layout.carga_horaria_padrao,
                mostrar_logo_evento=layout.mostrar_logo_evento,
                mostrar_logo_instituicoes=layout.mostrar_logo_instituicoes,
                mostrar_logos_personalizados=layout.mostrar_logos_personalizados,
                layout_logos=layout.layout_logos,
            )
            
            # Copia as instituições
            novo_layout.instituicoes.set(layout.instituicoes.all())
        
        count = queryset.count()
        self.message_user(request, f"{count} layout(s) duplicado(s) com sucesso.")
    duplicar_layout.short_description = "Duplicar layout selecionado"
    
    # Validação antes de salvar
    def save_model(self, request, obj, form, change):
        """Valida e formata os campos JSON antes de salvar"""
        import json
        
        # Helper function para validar JSON
        def validar_json(campo, nome_campo):
            if campo:
                if isinstance(campo, str):
                    try:
                        return json.loads(campo)
                    except json.JSONDecodeError as e:
                        from django.core.exceptions import ValidationError
                        raise ValidationError(
                            f"Formato JSON inválido para {nome_campo}: {str(e)}"
                        )
            return campo
        
        try:
            # Valida e formata o campo assinaturas
            obj.assinaturas = validar_json(obj.assinaturas, "assinaturas")
            
            # Valida e formata o campo logos_personalizados
            obj.logos_personalizados = validar_json(obj.logos_personalizados, "logos_personalizados")
            
            # Valida e formata o campo ordem_exibicao
            obj.ordem_exibicao = validar_json(obj.ordem_exibicao, "ordem_exibicao")
            
        except ValidationError as e:
            from django.contrib import messages
            messages.error(request, str(e))
            return  # Não salva se houver erro de validação
        
        super().save_model(request, obj, form, change)
    
    # Estilos CSS para o admin
    #class Media:
    #    css = {
    #        'all': ('admin/css/layout_admin.css',)
    #    }
# Adicione também o admin para Certificado para facilitar o gerenciamento
@admin.register(Certificado)
class CertificadoAdmin(admin.ModelAdmin):
    list_display = ('codigo_short', 'participante', 'atividade', 'tipo_certificado', 
                   'layout_nome', 'data_atividade', 'emitido', 'publicado')
    list_filter = ('tipo_certificado', 'emitido', 'publicado', 'data_atividade', 'layout')
    search_fields = ('participante__username', 'participante__email',
                    'atividade__nome', 'codigo_validacao', 'layout__nome')
    list_select_related = ('participante', 'atividade', 'layout')
    readonly_fields = ('codigo_validacao', 'hash_validacao', 'data_emissao',
                      'data_impressao', 'impressoes')
    
    fieldsets = (
        ('Informações Básicas', {
            'fields': ('codigo_validacao', 'participante', 'atividade', 'layout')
        }),
        ('Detalhes do Certificado', {
            'fields': ('tipo_certificado', 'data_atividade', 'carga_horaria')
        }),
        ('Status', {
            'fields': ('emitido', 'publicado', 'data_impressao', 'impressoes')
        }),
        ('Validação', {
            'fields': ('hash_validacao', 'data_emissao')
        }),
    )
    
    def codigo_short(self, obj):
        return str(obj.codigo_validacao)[:8] + '...'
    codigo_short.short_description = 'Código'
    
    def layout_nome(self, obj):
        return obj.layout.nome if obj.layout else 'Nenhum'
    layout_nome.short_description = 'Layout'
    
    # Ações rápidas
    actions = ['emitir_certificados', 'publicar_certificados']
    
    def emitir_certificados(self, request, queryset):
        updated = queryset.update(emitido=True)
        self.message_user(request, f"{updated} certificado(s) emitido(s).")
    emitir_certificados.short_description = "Emitir certificados selecionados"
    
    def publicar_certificados(self, request, queryset):
        updated = queryset.update(publicado=True)
        self.message_user(request, f"{updated} certificado(s) publicado(s).")
    publicar_certificados.short_description = "Publicar certificados selecionados"


"""
@admin.register(Certificado)
class CertificadoAdmin(admin.ModelAdmin):
    list_display = ('codigo_short', 'participante', 'atividade', 'tipo_certificado', 
                   'data_atividade', 'emitido', 'publicado', 'acoes')
    list_filter = ('tipo_certificado', 'emitido', 'publicado', 'data_atividade')
    search_fields = ('participante__username', 'participante__email',
                    'atividade__nome', 'codigo_validacao')
    readonly_fields = ('codigo_validacao', 'hash_validacao', 'data_emissao',
                      'data_impressao', 'impressoes')
    
    fieldsets = (
        ('Informações Básicas', {
            'fields': ('codigo_validacao', 'participante', 'atividade', 'layout')
        }),
        ('Tipo e Datas', {
            'fields': ('tipo_certificado', 'data_atividade', 'carga_horaria')
        }),
        ('Status', {
            'fields': ('emitido', 'publicado', 'data_impressao', 'impressoes')
        }),
    )
    
    def codigo_short(self, obj):
        return str(obj.codigo_validacao)[:8] + '...'
    codigo_short.short_description = 'Código'
    
    def acoes(self, obj):
        view_url = reverse('submission:visualizar_certificado', args=[obj.codigo_validacao])
        pdf_url = reverse('submission:gerar_pdf_certificado', args=[obj.codigo_validacao])
        return format_html(
            '<a href="{}" target="_blank" title="Visualizar">👁️</a> '
            '<a href="{}" title="Baixar PDF">📄</a>',
            view_url,
            pdf_url
        )
    acoes.short_description = 'Ações'
"""
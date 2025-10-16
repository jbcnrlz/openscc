from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.shortcuts import get_object_or_404, redirect
from django.contrib.staticfiles import finders
from xhtml2pdf import pisa
from datetime import datetime
from django.views.generic import View
from ..models import Problema, Parte

class ExportarProblemaPDFView(LoginRequiredMixin, View):
    def get(self, request, problema_id):
        problema = get_object_or_404(Problema, id=problema_id)
        partes = Parte.objects.filter(problema=problema).order_by('ordem')
        guia_tutor = getattr(problema, 'guia_tutor', None)
        
        context = {
            'problema': problema,
            'partes': partes,
            'guia_tutor': guia_tutor,
            'data_exportacao': datetime.now().strftime("%d/%m/%Y %H:%M"),
        }
        
        # Renderizar template para HTML
        html_string = render_to_string('mimir/exportarPDF.html', context)
        
        # Criar resposta PDF
        response = HttpResponse(content_type='application/pdf')
        filename = f"problema_{problema.id}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        # Gerar PDF
        pdf_status = pisa.CreatePDF(
            html_string, 
            dest=response,
            encoding='UTF-8'
        )
        
        if pdf_status.err:
            return HttpResponse('Erro ao gerar PDF', status=500)
        
        return response

class ExportarGuiaTutorPDFView(LoginRequiredMixin, View):
    def get(self, request, problema_id):
        problema = get_object_or_404(Problema, id=problema_id)
        guia_tutor = getattr(problema, 'guia_tutor', None)
        
        if not guia_tutor:
            messages.error(request, 'Guia do Tutor não encontrado para este problema.')
            return redirect('mimir:problemaDetail', pk=problema_id)
        
        context = {
            'problema': problema,
            'guia_tutor': guia_tutor,
            'data_exportacao': datetime.now().strftime("%d/%m/%Y %H:%M"),
        }
        
        # Renderizar template para HTML
        html_string = render_to_string('mimir/exportarGuiaPDF.html', context)
        
        # Criar resposta PDF
        response = HttpResponse(content_type='application/pdf')
        filename = f"guia_tutor_{problema.id}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        # Gerar PDF
        pdf_status = pisa.CreatePDF(
            html_string, 
            dest=response,
            encoding='UTF-8'
        )
        
        if pdf_status.err:
            return HttpResponse('Erro ao gerar PDF', status=500)
        
        return response

class ExportarCompletoPDFView(LoginRequiredMixin, View):
    def get(self, request, problema_id):
        problema = get_object_or_404(Problema, id=problema_id)
        partes = Parte.objects.filter(problema=problema).order_by('ordem')
        guia_tutor = getattr(problema, 'guia_tutor', None)
        
        context = {
            'problema': problema,
            'partes': partes,
            'guia_tutor': guia_tutor,
            'data_exportacao': datetime.now().strftime("%d/%m/%Y %H:%M"),
        }
        
        # Renderizar template para HTML
        html_string = render_to_string('mimir/exportarCompletoPDF.html', context)
        
        # Criar resposta PDF
        response = HttpResponse(content_type='application/pdf')
        filename = f"caso_completo_{problema.id}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        # Gerar PDF
        pdf_status = pisa.CreatePDF(
            html_string, 
            dest=response,
            encoding='UTF-8'
        )
        
        if pdf_status.err:
            return HttpResponse('Erro ao gerar PDF', status=500)
        
        return response
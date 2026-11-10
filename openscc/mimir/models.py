from django.db import models
from django.contrib.auth.models import User
from django.core.validators import ValidationError
import datetime
from django.utils import timezone
from django.core.validators import FileExtensionValidator
import re
# Create your models here.
def isTutor(self):
    """Verifica se o usuário pertence ao grupo Tutor"""
    return self.groups.filter(name="Tutor").exists()

User.add_to_class('isTutor', isTutor)

def isProfessor(self):
    """
    Verifica se o usuário pertence a um grupo específico
    """
    return self.groups.filter(name="Professor").exists()

User.add_to_class('isProfessor', isProfessor)

def isAluno(self):
    """
    Verifica se o usuário pertence a um grupo específico
    """
    return self.groups.filter(name="Aluno").exists()

User.add_to_class('isAluno', isAluno)

def isMembroAutorizado(self):
    """
    Verifica se o usuário pertence a um dos grupos autorizados
    """
    return self.groups.filter(name__in=["Professor", "Aluno"]).exists()

User.add_to_class('isMembroAutorizado', isMembroAutorizado)

def get_assuntos_vinculados(self, ano=None, semestre=None):
    """
    Retorna os assuntos vinculados a este aluno
    """
    if not self.isAluno():
        return Assunto.objects.none()
    
    vinculos = self.vinculos_assuntos.filter(ativo=True)
    
    if ano:
        vinculos = vinculos.filter(ano=ano)
    if semestre:
        vinculos = vinculos.filter(semestre=semestre)
    
    return Assunto.objects.filter(
        id__in=vinculos.values_list('assunto_id', flat=True)
    )

def get_vinculos_ativos(self):
    """
    Retorna todos os vínculos ativos do aluno
    """
    if not self.isAluno():
        return VinculoAlunoAssunto.objects.none()
    
    return self.vinculos_assuntos.filter(ativo=True)

User.add_to_class('get_assuntos_vinculados', get_assuntos_vinculados)
User.add_to_class('get_vinculos_ativos', get_vinculos_ativos)

class Assunto(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    nome = models.CharField(max_length=200, blank=False, null=False)
    layoutGuiaTutor = models.TextField(blank=True, null=True)
    # Substituindo layoutProblema (TextField) por um campo de arquivo
    layoutProblema = models.FileField(
        upload_to='layouts_problema/',
        blank=True,
        null=True,
        verbose_name='Layout do Problema (arquivo)',
        help_text='Arquivo contendo o template (ex.: .txt, .md) com placeholders {{...}} para os dados do problema.',
        validators=[FileExtensionValidator(allowed_extensions=['pdf'])]
    )

    def __str__(self):
        return self.nome
    
    def get_alunos_vinculados(self, ano=None, semestre=None):
        """
        Retorna os alunos vinculados a este assunto
        """
        vinculos = self.alunos_vinculados.filter(ativo=True)
        
        if ano:
            vinculos = vinculos.filter(ano=ano)
        if semestre:
            vinculos = vinculos.filter(semestre=semestre)
            
        return User.objects.filter(
            id__in=vinculos.values_list('aluno_id', flat=True)
        )
    
    def get_vinculos_ativos(self):
        """
        Retorna todos os vínculos ativos para este assunto
        """
        return self.alunos_vinculados.filter(ativo=True)
    
    def vincular_aluno(self, aluno, ano, semestre):
        """
        Método para vincular um aluno ao assunto
        """
        if not aluno.isAluno():
            raise ValidationError('Somente alunos podem ser vinculados.')
        
        vinculo, created = VinculoAlunoAssunto.objects.get_or_create(
            aluno=aluno,
            assunto=self,
            ano=ano,
            semestre=semestre,
            defaults={'ativo': True}
        )
        
        if not created and not vinculo.ativo:
            vinculo.ativo = True
            vinculo.save()
        
        return vinculo
    
    def desvincular_aluno(self, aluno, ano=None, semestre=None):
        """
        Método para desvincular um aluno do assunto
        """
        vinculos = self.alunos_vinculados.filter(aluno=aluno, ativo=True)
        
        if ano:
            vinculos = vinculos.filter(ano=ano)
        if semestre:
            vinculos = vinculos.filter(semestre=semestre)
        
        vinculos.update(ativo=False)
        return vinculos.count()
    
    def get_alunos_vinculados_ativos(self):
        """Retorna os alunos vinculados ativos a este assunto"""
        return User.objects.filter(
            vinculos_assuntos__assunto=self,
            vinculos_assuntos__ativo=True
        ).distinct()
    

class TiposDePergunta(models.Model):    
    descricao = models.CharField(max_length=200, blank=False, null=False)
    textoParaLLM = models.TextField(blank=False, null=True)

    def __str__(self):
        return self.descricao

class PapelTimbrado(models.Model):
    nome = models.CharField(max_length=200, blank=False, null=False)
    papelTimbrado = models.FileField(upload_to='papeis/')

class Fontes(models.Model):
    fonte = models.FileField(upload_to='fontes/')
    nome = models.CharField(max_length=200, blank=False, null=False)
    dataCriacao = models.DateTimeField(auto_now_add=True)
    descricao = models.TextField(blank=True, null=True)
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE, default=1)

    def __str__(self):
        return self.nome

class Pergunta(models.Model):
    assunto = models.ForeignKey(Assunto, on_delete=models.CASCADE)
    pergunta = models.TextField(blank=False, null=False)
    gabarito = models.TextField(blank=False, null=False)
    tipoDePergunta = models.ForeignKey(TiposDePergunta, on_delete=models.CASCADE,default=1)
    aceita_upload_resposta = models.BooleanField(
        default=False,
        verbose_name='Aceita upload de arquivo como resposta'
    )
    
    @property
    def imagens(self):
        return self.imagempergunta_set.all()
    
    def get_primeira_prova(self):
        """Retorna a primeira prova associada a esta pergunta"""
        return self.prova_set.first()
    
    def get_primeira_prova_id(self):
        """Retorna o ID da primeira prova ou None"""
        primeira_prova = self.prova_set.first()
        return primeira_prova.id if primeira_prova else None

    def aplicar_feedback(self, feedback):
        """
        Aplica o feedback do especialista sobrepondo a pergunta e gabarito
        """
        if feedback.comentarios:
            # Divide o feedback em pergunta e gabarito (assumindo um formato específico)
            partes = feedback.comentarios.split('---GABARITO---')
            if len(partes) >= 1:
                self.pergunta = partes[0].strip()
            if len(partes) >= 2:
                self.gabarito = partes[1].strip()
            self.save()
    
    def get_texto_com_feedback(self):
        """
        Retorna o texto com feedback aplicado ou o original
        """
        feedback_utilizado = self.feedbacks.filter(status='utilizado').first()
        if feedback_utilizado and feedback_utilizado.comentarios:
            partes = feedback_utilizado.comentarios.split('---GABARITO---')
            return partes[0].strip() if len(partes) >= 1 else self.pergunta
        return self.pergunta
    
    def get_gabarito_com_feedback(self):
        """
        Retorna o gabarito com feedback aplicado ou o original
        """
        feedback_utilizado = self.feedbacks.filter(status='utilizado').first()
        if feedback_utilizado and feedback_utilizado.comentarios:
            partes = feedback_utilizado.comentarios.split('---GABARITO---')
            return partes[1].strip() if len(partes) >= 2 else self.gabarito
        return self.gabarito

    def gerar_html_imagens_impressao(self) -> str:
        from django.utils.html import escape

        try:
            imgs = list(self.imagens.all())
        except Exception:
            imgs = []
        if not imgs:
            return ""

        partes = [
            '<div class="mimir-question-images" '
            'style="margin:10px 0;text-align:center;page-break-inside:avoid;break-inside:avoid;">'
        ]
        for idx, img_obj in enumerate(imgs, 1):
            src = getattr(img_obj, "src_impressao", "")
            if not src:
                continue
            partes.append(
                f'<div style="display:inline-block;max-width:100%;margin:4px 8px;text-align:center;vertical-align:top;">'
                f'<img src="{escape(src)}" alt="Figura {idx} da questão" '
                f'style="max-width:100%;max-height:260px;width:auto;height:auto;border:1px solid #cbd5e1;border-radius:4px;padding:3px;background:#ffffff;object-fit:contain;">'
                f'</div>'
            )
        partes.append("</div>")
        return "".join(partes)

    @property
    def texto_com_syntax_highlight(self):
        from django.utils.safestring import mark_safe
        return mark_safe(formatar_texto_com_syntax_highlight(self.get_texto_com_feedback()))

    @property
    def texto_com_imagens_e_syntax_highlight(self):
        from django.utils.safestring import mark_safe
        return mark_safe(
            formatar_texto_com_syntax_highlight(
                self.get_texto_com_feedback(),
                imagens_html=self.gerar_html_imagens_impressao(),
            )
        )

    @property
    def gabarito_com_syntax_highlight(self):
        from django.utils.safestring import mark_safe
        return mark_safe(formatar_texto_com_syntax_highlight(self.get_gabarito_com_feedback()))


KNOWN_CODE_LANGS = {
    "python", "py", "javascript", "js", "typescript", "ts", "java",
    "c", "cpp", "c++", "csharp", "cs", "c#", "sql", "html", "xml",
    "css", "php", "bash", "sh", "shell", "json", "portugol",
    "pseudocodigo", "plaintext", "text", "txt", "codigo", "código",
    "ruby", "go", "rust", "kotlin", "swift", "r", "dart",
}


def _desachatar_codigo_se_necessario(codigo: str, lang: str) -> str:
    """
    Restaura quebras de linha e indentação caso um bloco de código tenha sido salvo
    em uma única linha (ex.: dentro de uma alternativa ou resposta).
    Se o código já possuir quebras de linha, mantém exatamente como está.
    """
    if not codigo or "\n" in codigo.strip():
        return codigo

    s = codigo.strip()
    lang_norm = (lang or "").lower().strip()

    # Caso 1: Linguagens com chaves/ponto-e-vírgula (C, C++, Java, JS, TS, C#, PHP, CSS...)
    if any(tok in s for tok in ("; ", "{ ", "} ", "};")) or re.search(r"#\s*include\s*[<\"][^>\"]+[>\"]", s):
        s_prep = re.sub(r"(#\s*include\s*(?:<[^>]+>|\"[^\"]+\"))\s+", r"\1\n", s)
        out_chars = []
        in_str = None
        paren_depth = 0
        n = len(s_prep)
        i = 0
        while i < n:
            ch = s_prep[i]
            if in_str:
                out_chars.append(ch)
                if ch == "\\" and i + 1 < n:
                    i += 1
                    out_chars.append(s_prep[i])
                elif ch == in_str:
                    in_str = None
            else:
                if ch in ('"', "'"):
                    in_str = ch
                    out_chars.append(ch)
                elif ch == "(":
                    paren_depth += 1
                    out_chars.append(ch)
                elif ch == ")":
                    paren_depth = max(0, paren_depth - 1)
                    out_chars.append(ch)
                elif ch == "{" and paren_depth == 0:
                    out_chars.append("{\n")
                    while i + 1 < n and s_prep[i + 1] == " ":
                        i += 1
                elif ch == "}" and paren_depth == 0:
                    if out_chars and not "".join(out_chars).endswith("\n"):
                        out_chars.append("\n")
                    out_chars.append("}")
                    if i + 1 < n and s_prep[i + 1] not in (";", ",", ")"):
                        out_chars.append("\n")
                        while i + 1 < n and s_prep[i + 1] == " ":
                            i += 1
                elif ch == ";" and paren_depth == 0:
                    out_chars.append(";\n")
                    while i + 1 < n and s_prep[i + 1] == " ":
                        i += 1
                else:
                    out_chars.append(ch)
            i += 1

        raw_lines = [ln.strip() for ln in "".join(out_chars).splitlines() if ln.strip()]
        if len(raw_lines) > 1:
            indented = []
            indent = 0
            for ln in raw_lines:
                if ln.startswith("}"):
                    indent = max(0, indent - 1)
                indented.append(("    " * indent) + ln)
                if ln.endswith("{"):
                    indent += 1
            return "\n".join(indented)

    # Caso 2: Python / Portugol em linha única
    if lang_norm in ("python", "py", "portugol", "código", "codigo", ""):
        if re.search(r":\s+\S", s) or re.search(r"\b(def|class|for|while|if|elif|else|return|print)\b", s):
            s_py = re.sub(
                r"(?<!^)\s+\b(def |class |for |while |if |elif |else:|try:|except |finally:|return |print\()",
                r"\n\1",
                s,
            )
            s_py = re.sub(r":\s+(?!\n)", ":\n", s_py)
            raw_lines = [ln.strip() for ln in s_py.splitlines() if ln.strip()]
            if len(raw_lines) > 1:
                indented = []
                indent = 0
                for ln in raw_lines:
                    if re.match(r"^(elif |else:|except |finally:)", ln):
                        indent = max(0, indent - 1)
                    elif re.match(r"^(def |class )", ln):
                        indent = 0
                    indented.append(("    " * indent) + ln)
                    if ln.endswith(":"):
                        indent += 1
                    elif re.match(r"^(return\b|break\b|continue\b|pass\b|raise\b)", ln):
                        indent = max(0, indent - 1)
                return "\n".join(indented)

    return codigo


def _colorir_codigo_html_server(codigo_escapado: str) -> str:
    """
    Aplica syntax highlight server-side de alto contraste (compatível com impressão,
    WeasyPrint PDF e visualização em tela).
    Protege strings e diretivas ANTES de comentários para que '&#39;' / '&#x27;' ou '#include'
    nunca sejam confundidos com comentários '#'.
    """
    tokens = []

    def _guardar(html_span):
        idx = len(tokens)
        tokens.append(html_span)
        return f"@@MIMIR_SRV_TOK_{idx}@@"

    out = codigo_escapado

    # 1. Comentários de bloco /* ... */ e <!-- ... -->
    out = re.sub(
        r"(?:/\*[\s\S]*?\*/|&lt;!--[\s\S]*?--&gt;)",
        lambda m: _guardar(f'<span style="color:#116329;font-style:italic;">{m.group(0)}</span>'),
        out,
    )

    # 2. Strings "..." ou '...' (escapadas como &quot; ou &#39; / &#x27;) ANTES de comentários!
    out = re.sub(
        r"(?:&quot;(?:\\.|(?!&quot;).)*?&quot;|&#(?:39|x27);(?:\\.|(?!&#(?:39|x27);).)*?&#(?:39|x27);)",
        lambda m: _guardar(f'<span style="color:#a31515;">{m.group(0)}</span>'),
        out,
    )

    # 3. Diretivas de pré-processador C/C++ (#include <...>, #define, etc.)
    out = re.sub(
        r"(?m)^(\s*#\s*(?:include|define|ifdef|ifndef|endif|elif|else|pragma|undef)\b.*)$",
        lambda m: _guardar(f'<span style="color:#6f42c1;font-weight:700;">{m.group(0)}</span>'),
        out,
    )

    # 4. Comentários de linha: //..., #... (sem preceder por '&' de entidade HTML), ou -- (SQL/Lua)
    out = re.sub(
        r"(?m)(?://.*$|(?<!&)#.*$|(?<!\w)--(?=\s|$).*$)",
        lambda m: _guardar(f'<span style="color:#116329;font-style:italic;">{m.group(0)}</span>'),
        out,
    )

    # 5. Tags HTML/XML (&lt;div, &lt;/div&gt;, /&gt;) e atributos HTML (class=, id=, etc.)
    out = re.sub(
        r"(&lt;/?[a-zA-Z][\w:-]*|/?&gt;)",
        lambda m: _guardar(f'<span style="color:#0550ae;font-weight:700;">{m.group(0)}</span>'),
        out,
    )

    # 6. Palavras-chave (usando _guardar para nunca expor números/atributos do style="" às próximas regexes!)
    kw_pattern = (
        r"\b(def|class|return|if|elif|else|for|while|do|switch|case|break|continue|try|except|catch|"
        r"finally|raise|throw|import|from|as|pass|lambda|yield|with|async|await|True|False|None|and|or|"
        r"not|in|is|function|const|let|var|new|this|super|extends|implements|public|private|protected|"
        r"static|final|void|int|float|double|char|boolean|bool|string|String|long|short|unsigned|struct|"
        r"enum|interface|package|namespace|using|include|printf|scanf|cout|cin|System|out|println|console|"
        r"log|SELECT|FROM|WHERE|INSERT|INTO|VALUES|UPDATE|SET|DELETE|JOIN|INNER|LEFT|RIGHT|ON|GROUP|BY|"
        r"ORDER|HAVING|LIMIT|CREATE|TABLE|ALTER|DROP|PRIMARY|KEY|FOREIGN|REFERENCES|AND|OR|NOT|NULL|AS|"
        r"DISTINCT|COUNT|SUM|AVG|MIN|MAX|algoritmo|inicio|fimalgoritmo|escreva|escreval|leia|se|entao|"
        r"senao|fimse|para|de|ate|passo|faca|fimpara|enquanto|fimenquanto|repita|procedimento|funcao|"
        r"retorne|inteiro|real|caractere|logico|verdadeiro|falso)\b"
    )
    out = re.sub(
        kw_pattern,
        lambda m: _guardar(f'<span style="color:#0550ae;font-weight:700;">{m.group(1)}</span>'),
        out,
    )

    # 7. Chamadas de função (usando _guardar)
    out = re.sub(
        r"\b([a-zA-Z_]\w*)(?=\s*\()",
        lambda m: _guardar(f'<span style="color:#6f42c1;font-weight:600;">{m.group(1)}</span>'),
        out,
    )

    # 8. Números (ignorando entidades HTML e placeholders)
    out = re.sub(
        r"(?<![\w&#])(\d+(?:\.\d+)?)(?![\w;])",
        lambda m: _guardar(f'<span style="color:#953800;font-weight:600;">{m.group(1)}</span>'),
        out,
    )

    # 9. Restaura todos os tokens protegidos
    out = re.sub(r"@@MIMIR_SRV_TOK_(\d+)@@", lambda m: tokens[int(m.group(1))], out)
    return out


def formatar_texto_com_syntax_highlight(texto: str, imagens_html: str = "") -> str:
    """
    Converte blocos de código cercados por ```lang ... ``` e código inline `...`
    em HTML estilizado com syntax highlight de alto contraste (funciona no navegador,
    window.print() e WeasyPrint PDF), além de estruturar alternativas A)-E) e imagens.
    """
    from django.utils.html import escape

    if not texto:
        return imagens_html or ""
    raw = str(texto)
    blocos = []

    def _substituir_bloco(match):
        cand_lang = (match.group(1) or "").strip()
        corpo = match.group(2) or ""
        if cand_lang and cand_lang.lower() in KNOWN_CODE_LANGS:
            lang = cand_lang
            codigo = corpo.strip("\r\n")
        else:
            lang = "código"
            codigo = (f"{cand_lang} {corpo}" if cand_lang else corpo).strip("\r\n")

        codigo = _desachatar_codigo_se_necessario(codigo, lang)
        linhas = codigo.splitlines() or [""]
        escaped_lines = []
        for idx, l in enumerate(linhas, 1):
            l_expanded = l.replace("\t", "    ")
            leading_spaces = len(l_expanded) - len(l_expanded.lstrip(" "))
            conteudo_linha = l_expanded.lstrip(" ")
            esc = (
                escape(conteudo_linha)
                .replace('"', "&quot;")
                .replace("'", "&#39;")
            )
            colored = _colorir_codigo_html_server(esc)
            indent_html = "&nbsp;" * leading_spaces
            linha_html = (
                f'<div style="display:flex;align-items:baseline;line-height:1.45;font-family:\'Consolas\',\'Courier New\',monospace;font-size:9pt;">'
                f'<span style="color:#64748b;user-select:none;display:inline-block;min-width:24px;text-align:right;margin-right:10px;padding-right:6px;border-right:1px solid #cbd5e1;font-size:8pt;flex-shrink:0;">{idx}</span>'
                f'<span style="white-space:pre-wrap;word-break:break-word;flex:1;">{indent_html}{colored if colored else "&nbsp;"}</span>'
                f'</div>'
            )
            escaped_lines.append(linha_html)

        codigo_html = "".join(escaped_lines)
        lang_label = lang.upper() if lang else "CÓDIGO FONTE"
        html_bloco = (
            f'<div class="mimir-code-block" data-mimir-code-enhanced="1" '
            f'style="background:#f8fafc;color:#0f172a;border:1px solid #cbd5e1;border-left:4px solid #2563eb;border-radius:6px;margin:6px 0;overflow:hidden;white-space:normal;page-break-inside:avoid;break-inside:avoid;-webkit-print-color-adjust:exact;print-color-adjust:exact;">'
            f'<div style="background:#e2e8f0;color:#1e293b;padding:3px 10px;font-size:8pt;font-weight:700;font-family:\'Consolas\',\'Courier New\',monospace;border-bottom:1px solid #cbd5e1;letter-spacing:0.3px;">'
            f'&lt;/&gt; {escape(lang_label)}'
            f'</div>'
            f'<div style="margin:0;padding:6px 10px;background:#f8fafc;color:#0f172a;">'
            f'{codigo_html}'
            f'</div>'
            f'</div>'
        )
        idx_b = len(blocos)
        blocos.append(html_bloco)
        return f"@@MIMIR_BLOCK_{idx_b}@@"

    processado = re.sub(r"```([a-zA-Z0-9_+\-#]*)(?:\r?\n|[ \t]+)?([\s\S]*?)```", _substituir_bloco, raw)

    def _formatar_trecho_Final(trecho: str) -> str:
        t = escape(trecho)
        t = re.sub(
            r"`([^`\r\n]+)`",
            r'<code style="background:#f1f5f9;color:#be123c;border:1px solid #cbd5e1;padding:1px 5px;border-radius:4px;font-family:\'Consolas\',\'Courier New\',monospace;font-size:0.92em;-webkit-print-color-adjust:exact;print-color-adjust:exact;">\1</code>',
            t,
        )
        t = t.replace("\r\n", "\n").replace("\n", "<br>")
        t = re.sub(r"@@MIMIR_BLOCK_(\d+)@@", lambda m: blocos[int(m.group(1))], t)
        return t

    # Verifica se o texto possui alternativas estruturadas (A), B), C)...)
    linhas_proc = processado.splitlines()
    linhas_enunciado = []
    alternativas_extraidas = []
    for linha in linhas_proc:
        m_alt = re.match(r"^\s*\(?([A-Ha-h])[\)\.\-]\s*(.*)$", linha)
        if m_alt:
            alternativas_extraidas.append([m_alt.group(1).upper(), [m_alt.group(2)]])
        elif not alternativas_extraidas:
            linhas_enunciado.append(linha)
        else:
            alternativas_extraidas[-1][1].append(linha)

    if len(alternativas_extraidas) >= 2:
        enunciado_html = _formatar_trecho_Final("\n".join(linhas_enunciado).strip())
        alts_html_list = []
        for letra, alt_lines in alternativas_extraidas:
            alt_conteudo = _formatar_trecho_Final("\n".join(alt_lines).strip())
            alts_html_list.append(
                f'<div class="mimir-alt-item" style="display:flex;align-items:flex-start;gap:8px;margin-top:6px;page-break-inside:avoid;break-inside:avoid;">'
                f'<span style="font-weight:700;min-width:22px;display:inline-block;">{letra})</span>'
                f'<div style="flex:1;min-width:0;">{alt_conteudo}</div>'
                f'</div>'
            )
        alts_block = '<div class="mimir-alts-list" style="margin-top:8px;">' + "".join(alts_html_list) + "</div>"
        return f"{enunciado_html}{imagens_html or ''}{alts_block}"

    corpo_final = _formatar_trecho_Final(processado)
    if imagens_html:
        return f"{corpo_final}{imagens_html}"
    return corpo_final

class Prova(models.Model):
    titulo = models.CharField(max_length=200, blank=False, null=False)
    descricao = models.TextField(blank=False, null=False)
    dataCriacao = models.DateTimeField(auto_now_add=True)
    dataAtualizacao = models.DateTimeField(auto_now=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    assunto = models.ForeignKey(Assunto, on_delete=models.CASCADE)
    perguntas = models.ManyToManyField(Pergunta)

    def __str__(self):
        return self.titulo

    @property
    def is_unificada(self):
        from .avaliacao_unificada import extrair_meta_unificada
        _, meta = extrair_meta_unificada(self.descricao)
        return bool(meta and meta.get('is_unificada'))

    @property
    def descricao_limpa(self):
        from .avaliacao_unificada import extrair_meta_unificada
        limpa, _ = extrair_meta_unificada(self.descricao)
        return limpa

    @property
    def unificada_meta(self):
        from .avaliacao_unificada import extrair_meta_unificada
        _, meta = extrair_meta_unificada(self.descricao)
        return meta or {}

    @property
    def estrutura_unificada(self):
        from .avaliacao_unificada import construir_estrutura_unificada
        return construir_estrutura_unificada(self)

    @property
    def assuntos_modulo(self):
        meta = self.unificada_meta
        ids = meta.get('assuntos_ids', [])
        if ids:
            return Assunto.objects.filter(id__in=ids)
        return Assunto.objects.filter(id=self.assunto_id)

class ImagemPergunta(models.Model):
    pergunta = models.ForeignKey(Pergunta, on_delete=models.CASCADE, related_name='imagens')
    imagem = models.ImageField(upload_to='perguntas/')
    criado_em = models.DateTimeField(auto_now_add=True)

    @property
    def src_impressao(self):
        """
        Retorna a imagem codificada em Data URI base64 quando o arquivo existe no disco
        (garantindo impressão imediata no navegador e no WeasyPrint PDF), com fallback para URL.
        """
        import base64
        import mimetypes
        import os

        try:
            if self.imagem and hasattr(self.imagem, "path") and os.path.exists(self.imagem.path):
                mime_type, _ = mimetypes.guess_type(self.imagem.path)
                if not mime_type:
                    mime_type = "image/png"
                with open(self.imagem.path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("ascii")
                return f"data:{mime_type};base64,{b64}"
        except Exception:
            pass
        try:
            return self.imagem.url
        except Exception:
            return ""

class ObjetivosAprendizagem(models.Model):
    descricao = models.CharField(max_length=200, blank=False, null=False)

    def __str__(self):
        return self.descricao

class Tema(models.Model):
    nome = models.CharField(max_length=200, blank=False, null=False)
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, default=1)

    def __str__(self):
        return self.nome

class Problema(models.Model):
    titulo = models.CharField(max_length=200, blank=False, null=False)
    assunto = models.ForeignKey(Assunto, on_delete=models.CASCADE)
    criado_em = models.DateTimeField(auto_now_add=True)
    dataAplicacao = models.DateTimeField()
    objetivos = models.ManyToManyField(ObjetivosAprendizagem)
    tema = models.ForeignKey(Tema, on_delete=models.CASCADE)
    fontes = models.ManyToManyField('Fontes', blank=True)
    titulo_apresentacao = models.CharField(
            max_length=200, 
            verbose_name="Título para Alunos (Anti-Spoiler)", 
            null=True, 
            blank=True, 
            help_text="Nome fantasia para o caso. Ex: 'Dor na barriga' em vez de 'Apendicite'."
    )

    def get_feedbacks_pendentes(self):
        """Retorna feedbacks pendentes para este problema"""
        return self.feedbacks.filter(status='pendente')
    
    def get_feedbacks_utilizados(self):
        """Retorna feedbacks utilizados para este problema"""
        return self.feedbacks.filter(status='utilizado')
    
    def tem_feedbacks_pendentes(self):
        """Verifica se há feedbacks pendentes"""
        return self.feedbacks.filter(status='pendente').exists()


class Parte(models.Model):
    problema = models.ForeignKey(Problema, on_delete=models.CASCADE, related_name='partes')
    enunciado = models.TextField(blank=False, null=False)    
    ordem = models.IntegerField(default=1)

    @property
    def midias(self):
        """Property para acessar as mídias da parte"""
        return self.midiaparte_set.all()

    @property
    def midias(self):
        """Property para acessar as mídias da parte"""
        return self.midiaparte_set.all()

class MidiaParte(models.Model):
    """
    Model para armazenar mídias (imagens, áudios, PDFs) associadas a partes do problema
    """
    TIPO_MIDIA_CHOICES = [
        ('imagem', 'Imagem'),
        ('audio', 'Áudio'),
        ('pdf', 'PDF'),
        ('video', 'Vídeo'),
        ('documento', 'Documento'),
    ]
    
    parte = models.ForeignKey(Parte, on_delete=models.CASCADE, related_name='midias')
    arquivo = models.FileField(
        upload_to='partes_midia/%Y/%m/%d/',
        help_text="Faça upload de imagens, áudios, PDFs ou outros documentos"
    )
    tipo = models.CharField(max_length=20, choices=TIPO_MIDIA_CHOICES, default='imagem')
    descricao = models.CharField(max_length=255, blank=True, null=True, help_text="Descrição opcional da mídia")
    criado_em = models.DateTimeField(auto_now_add=True)
    ordem = models.IntegerField(default=1, help_text="Ordem de exibição da mídia")
    
    class Meta:
        verbose_name = 'Mídia da Parte'
        verbose_name_plural = 'Mídias das Partes'
        ordering = ['parte', 'ordem', 'criado_em']
    
    def __str__(self):
        return f"Mídia {self.id} - Parte {self.parte.ordem} - {self.get_tipo_display()}"
    
    def get_icone_tipo(self):
        """Retorna o ícone correspondente ao tipo de mídia"""
        icones = {
            'imagem': 'fas fa-image',
            'audio': 'fas fa-music',
            'pdf': 'fas fa-file-pdf',
            'video': 'fas fa-video',
            'documento': 'fas fa-file-alt',
        }
        return icones.get(self.tipo, 'fas fa-file')
    
    def is_imagem(self):
        return self.tipo == 'imagem'
    
    def is_audio(self):
        return self.tipo == 'audio'
    
    def is_pdf(self):
        return self.tipo == 'pdf'
    
    def is_video(self):
        return self.tipo == 'video'

class GuiaTutor(models.Model):
    problema = models.OneToOneField(Problema, on_delete=models.CASCADE, related_name='guia_tutor')
    conteudo = models.TextField(blank=True, null=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Guia do Tutor"
        verbose_name_plural = "Guias do Tutor"
    
    def __str__(self):
        return f"Guia do Tutor - {self.problema.titulo}"

class FeedbackEspecialista(models.Model):
    """
    Model para armazenar feedbacks de especialistas sobre problemas inteiros OU perguntas de provas
    """
    STATUS_CHOICES = [
        ('pendente', 'Pendente'),
        ('respondido', 'Respondido'),
        ('utilizado', 'Utilizado'),
    ]

    TIPO_CHOICES = [
        ('problema', 'Problema'),
        ('pergunta', 'Pergunta'),
    ]

    # Campos para problemas (Atualizado de 'parte' para 'problema')
    problema = models.ForeignKey(
        Problema, 
        on_delete=models.CASCADE, 
        related_name='feedbacks',
        null=True,
        blank=True
    )
    
    # Campos para perguntas
    pergunta = models.ForeignKey(
        Pergunta,
        on_delete=models.CASCADE,
        related_name='feedbacks', 
        null=True,
        blank=True
    )
    
    tipo = models.CharField(
        max_length=20,
        choices=TIPO_CHOICES,
        default='problema'
    )

    especialista = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='feedbacks_enviados'
    )
    solicitante = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='feedbacks_solicitados'
    )
    
    comentarios = models.TextField(
        verbose_name='Comentários do Especialista',
        help_text='Feedback detalhado',
        blank=True
    )
    resposta_autor = models.TextField(
        blank=True, 
        null=True,
        verbose_name='Resposta do Autor'
    )
    
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='pendente'
    )
    
    mensagem_solicitacao = models.TextField(
        blank=True, 
        null=True,
        verbose_name='Mensagem da Solicitação'
    )
    
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    respondido_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Feedback de Especialista'
        verbose_name_plural = 'Feedbacks de Especialistas'
        ordering = ['-criado_em']

    def __str__(self):
        if self.tipo == 'problema':
            return f"Feedback para Problema '{self.problema.titulo}' - {self.especialista.get_full_name()}"
        else:
            return f"Feedback para Pergunta - {self.especialista.get_full_name()}"

    def marcar_como_utilizado(self):
        self.status = 'utilizado'
        self.save()

    def responder(self, resposta):
        self.resposta_autor = resposta
        self.status = 'respondido'
        self.respondido_em = timezone.now()
        self.save()

    @property
    def utilizado(self):
        return self.status == 'utilizado'

    @property
    def pendente(self):
        return self.status == 'pendente'

    def clean(self):
        if not self.problema and not self.pergunta:
            raise ValidationError('Deve ser associado a um problema ou uma pergunta.')
        if self.problema and self.pergunta:
            raise ValidationError('Não pode estar associado a um problema e uma pergunta simultaneamente.')
        
    def aceitar_feedback(self, texto_final_resolvido=""):
        """
        Aplica o feedback do especialista utilizando o texto já revisado e resolvido pelo usuário no Frontend.
        """
        import re
        from django.utils.html import strip_tags
        
        texto_para_processar = texto_final_resolvido if texto_final_resolvido else self.comentarios

        if self.tipo == 'pergunta' and self.pergunta:
            # O fornecerFeedback.html formata os dados com os prefixos "Pergunta:" e "Gabarito:"
            # Precisamos extraí-los do texto limpo que veio do Frontend
            match = re.search(r'Pergunta:\s*(.*?)\s*Gabarito:\s*(.*)', texto_para_processar, re.IGNORECASE | re.DOTALL)
            
            if match:
                self.pergunta.pergunta = match.group(1).strip()
                self.pergunta.gabarito = match.group(2).strip()
                self.pergunta.save()
            else:
                # Fallback caso o especialista tenha apagado as palavras chave do editor
                self.pergunta.pergunta = texto_para_processar
                self.pergunta.save()
                
        elif self.tipo == 'problema' and self.problema:
            # FATIAMENTO DAS PARTES DO PROBLEMA
            partes_split = re.split(r'(?im)(?:<[^>]+>)*\s*parte\s+\d+[\:\-\.]?\s*(?:</[^>]+>)*', texto_para_processar)
            partes_limpas = [p.strip() for p in partes_split if p.strip()]
            
            # Apaga as partes antigas e recria com o texto aceito
            self.problema.partes.all().delete()
            
            if len(partes_limpas) > 1:
                for i, texto in enumerate(partes_limpas, 1):
                    self.problema.partes.create(
                        enunciado=texto,
                        ordem=i
                    )
            else:
                self.problema.partes.create(
                    enunciado=texto_para_processar,
                    ordem=1
                )

        self.status = 'utilizado'
        self.respondido_em = timezone.now()
        self.save()

    def rejeitar_feedback(self, resposta_autor=None):
        self.resposta_autor = resposta_autor
        self.status = 'respondido'
        self.respondido_em = timezone.now()
        self.save()
class ProvaAluno(models.Model):
    """
    Model para gerenciar a relação aluno-prova (modelo intermediário)
    """
    STATUS_CHOICES = [
        ('pendente', 'Pendente'),
        ('em_andamento', 'Em Andamento'),
        ('concluida', 'Concluída'),
        ('corrigida', 'Corrigida'),
    ]

    # ForeignKeys para os dois modelos relacionados
    aplicacao_prova = models.ForeignKey(
        'AplicacaoProva', 
        on_delete=models.CASCADE,
        related_name='provas_alunos'
    )
    aluno = models.ForeignKey(User, on_delete=models.CASCADE)
    
    # Removemos a FK direta para Prova, pois já temos através de aplicacao_prova
    data_inicio = models.DateTimeField(auto_now_add=True)
    data_conclusao = models.DateTimeField(null=True, blank=True)
    data_entrega = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pendente')
    tempo_decorrido = models.DurationField(default=datetime.timedelta(0))
    nota_final = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    class Meta:
        unique_together = ['aplicacao_prova', 'aluno']
        verbose_name = 'Prova do Aluno'
        verbose_name_plural = 'Provas dos Alunos'

    def __str__(self):
        return f"{self.aluno.username} - {self.aplicacao_prova.prova.titulo}"

    @property
    def prova(self):
        """Property para acessar a prova através da aplicação"""
        return self.aplicacao_prova.prova

    def iniciar_prova(self):
        """Marca a prova como iniciada"""
        self.status = 'em_andamento'
        self.data_inicio = timezone.now()
        self.save()

    def finalizar_prova(self):
        """Marca a prova como concluída"""
        self.status = 'concluida'
        self.data_conclusao = timezone.now()
        self.save()

    def calcular_nota(self):
        """Calcula a nota automaticamente baseada nas respostas corretas"""
        if self.aplicacao_prova.prova.is_unificada:
            from .avaliacao_unificada import calcular_diagnostico_prova_aluno_unificada
            diag = calcular_diagnostico_prova_aluno_unificada(self)
            self.nota_final = diag['nota_academica_final']
            self.save()
            return self.nota_final

        respostas = self.respostas.all()
        total_perguntas = self.aplicacao_prova.prova.perguntas.count()
        if total_perguntas == 0:
            return 0
        
        corretas = 0
        for resposta in respostas:
            if resposta.resposta_texto and resposta.pergunta.gabarito:
                # Comparação simples - em um sistema real você teria lógica mais complexa
                if resposta.resposta_texto.strip().lower() == resposta.pergunta.gabarito.strip().lower():
                    corretas += 1
        
        self.nota_final = (corretas / total_perguntas) * 10
        self.save()
        return self.nota_final

class RespostaAluno(models.Model):
    """
    Model para armazenar as respostas dos alunos às perguntas
    """
    aluno = models.ForeignKey(User, on_delete=models.CASCADE)
    pergunta = models.ForeignKey(Pergunta, on_delete=models.CASCADE)
    prova_aluno = models.ForeignKey(ProvaAluno, on_delete=models.CASCADE, related_name='respostas')
    resposta_texto = models.TextField(blank=True, null=True)
    resposta_arquivo = models.FileField(upload_to='respostas_alunos/', blank=True, null=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    nota = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    feedback_professor = models.TextField(blank=True, null=True)
    peso = models.IntegerField(default=1)
    arquivo_resposta = models.FileField(
        upload_to='respostas_alunos/%Y/%m/%d/',
        blank=True,
        null=True,
        verbose_name='Arquivo de Resposta'
    )

    class Meta:
        unique_together = ['aluno', 'pergunta', 'prova_aluno']
        verbose_name = 'Resposta do Aluno'
        verbose_name_plural = 'Respostas dos Alunos'

    def __str__(self):
        return f"Resposta de {self.aluno.username} para {self.pergunta.id}"
    
    @property
    def tipo_resposta(self):
        if self.arquivo_resposta:
            return 'arquivo'
        elif self.resposta_texto:
            return 'texto'
        else:
            return 'vazia'

class AplicacaoProva(models.Model):
    """
    Model para gerenciar a aplicação de provas para turmas/alunos
    """
    prova = models.ForeignKey(Prova, on_delete=models.CASCADE)
    alunos = models.ManyToManyField(
        User, 
        through=ProvaAluno,
        related_name='aplicacoes_prova'
    )
    data_disponivel = models.DateTimeField()
    data_limite = models.DateTimeField()
    tempo_limite = models.DurationField(help_text="Tempo limite para realização da prova")
    disponivel = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = 'Aplicação de Prova'
        verbose_name_plural = 'Aplicações de Provas'

    def __str__(self):
        return f"Aplicação: {self.prova.titulo}"

    def esta_disponivel(self):
        """Verifica se a prova está disponível para realização"""
        agora = timezone.now()
        return (self.disponivel and 
                self.data_disponivel <= agora <= self.data_limite)

    def adicionar_aluno(self, aluno):
        """Adiciona um aluno à aplicação da prova"""
        ProvaAluno.objects.get_or_create(
            aplicacao_prova=self,
            aluno=aluno,
            defaults={'status': 'pendente'}
        )

    def remover_aluno(self, aluno):
        """Remove um aluno da aplicação da prova"""
        ProvaAluno.objects.filter(aplicacao_prova=self, aluno=aluno).delete()

class VinculoAlunoAssunto(models.Model):
    """
    Model para vincular alunos a assuntos com ano e semestre
    """
    ANO_CHOICES = [ (year, str(year)) for year in range(2000, int(datetime.date.today().year) + 1) ]
    
    SEMESTRE_CHOICES = [
        (1, '1º Semestre'),
        (2, '2º Semestre'),
    ]
    
    aluno = models.ForeignKey(
        User, 
        on_delete=models.CASCADE,
        related_name='vinculos_assuntos',
        limit_choices_to={'groups__name': 'Aluno'}  # Só permite alunos
    )
    assunto = models.ForeignKey(
        Assunto, 
        on_delete=models.CASCADE,
        related_name='alunos_vinculados'
    )
    ano = models.IntegerField(choices=ANO_CHOICES, default=int(datetime.date.today().year))
    semestre = models.IntegerField(choices=SEMESTRE_CHOICES, default=1)
    data_vinculo = models.DateTimeField(auto_now_add=True)
    ativo = models.BooleanField(default=True)
    
    class Meta:
        verbose_name = 'Vínculo Aluno-Assunto'
        verbose_name_plural = 'Vínculos Aluno-Assunto'
        unique_together = ['aluno', 'assunto', 'ano', 'semestre']
        ordering = ['-ano', '-semestre', 'assunto__nome']
    
    def __str__(self):
        return f"{self.aluno.get_full_name()} - {self.assunto.nome} ({self.ano}/{self.semestre}º)"
    
    def clean(self):
        """
        Validação para garantir que o usuário é um aluno
        """
        if not self.aluno.isAluno():
            raise ValidationError('Somente alunos podem ser vinculados a assuntos.')
    
    @property
    def periodo(self):
        """Property para obter o período formatado"""
        return f"{self.ano}/{self.semestre}º"
    
class LLMLog(models.Model):
    """
    Registra todas as chamadas aos modelos de linguagem.
    """
    user = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='llm_logs'
    )
    prompt = models.TextField()
    response = models.TextField(blank=True, null=True)
    model_used = models.CharField(max_length=100, blank=True, null=True)
    tokens_input = models.IntegerField(null=True, blank=True)
    tokens_output = models.IntegerField(null=True, blank=True)
    duration_ms = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, default='success')  # success, error
    error_message = models.TextField(blank=True, null=True)
    endpoint = models.CharField(max_length=200, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Log de LLM'
        verbose_name_plural = 'Logs de LLM'

    def __str__(self):
        return f"{self.created_at} - {self.model_used} - {self.status}"
    
class TemplateContexto(models.Model):
    titulo = models.CharField(max_length=200, verbose_name="Título do Template")
    texto = models.TextField(verbose_name="Texto do Contexto Inicial")
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='templates_contexto')
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Template de Contexto'
        verbose_name_plural = 'Templates de Contexto'
        ordering = ['-criado_em']

    def __str__(self):
        return self.titulo
    
class PequenoGrupo(models.Model):
    nome = models.CharField(max_length=100, verbose_name="Nome do Grupo (Ex: Turma A - Grupo 1)")
    assunto = models.ForeignKey('Assunto', on_delete=models.CASCADE, related_name='pequenos_grupos')
    tutor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='grupos_tutorados', limit_choices_to={'groups__name': 'Tutor'})
    alunos = models.ManyToManyField(User, related_name='meus_pequenos_grupos', limit_choices_to={'groups__name': 'Aluno'})
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Pequeno Grupo"
        verbose_name_plural = "Pequenos Grupos"

    def __str__(self):
        return f"{self.nome} ({self.assunto.nome})"

class LiberacaoParte(models.Model):
    """Controla quais partes de um problema estão visíveis para um grupo específico."""
    grupo = models.ForeignKey(PequenoGrupo, on_delete=models.CASCADE, related_name='partes_liberadas')
    parte = models.ForeignKey('Parte', on_delete=models.CASCADE, related_name='liberacoes_grupos')
    liberada_em = models.DateTimeField(auto_now_add=True)
    liberada_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    class Meta:
        unique_together = ('grupo', 'parte') # Evita duplicidade de liberação

class PerguntaAprendizado(models.Model):
    """Perguntas (Learning Issues) levantadas pelos alunos em cada parte."""
    grupo = models.ForeignKey(PequenoGrupo, on_delete=models.CASCADE, related_name='perguntas_aprendizado')
    parte = models.ForeignKey('Parte', on_delete=models.CASCADE, related_name='perguntas_aprendizado')
    aluno = models.ForeignKey(User, on_delete=models.CASCADE)
    texto = models.TextField(verbose_name="Pergunta de Aprendizado")
    resposta = models.TextField(verbose_name="Resposta da Dúvida", null=True, blank=True)
    respondida_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='respostas_pbl')
    respondida_em = models.DateTimeField(null=True, blank=True)
    resolvida = models.BooleanField(default=False)
    criada_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['criada_em']

class Edital(models.Model):
    titulo = models.CharField(max_length=255, verbose_name="Título do Edital")
    orgao_fomento = models.CharField(max_length=100, verbose_name="Órgão de Fomento (Ex: FAPESP, FINEP)")
    arquivo_edital = models.FileField(upload_to='editais/pdfs/', verbose_name="PDF Completo do Edital")
    
    # Armazenamento dos processamentos automáticos do LLM
    resumo_llm = models.TextField(verbose_name="Resumo Estruturado (IA)", null=True, blank=True)
    insights_llm = models.TextField(verbose_name="Insights de Elegibilidade (IA)", null=True, blank=True)
    
    data_publicacao = models.DateField(verbose_name="Data de Publicação")
    data_limite = models.DateTimeField(verbose_name="Prazo Final de Submissão")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Edital"
        verbose_name_plural = "Editais"

    def __str__(self):
        return f"{self.orgao_fomento} - {self.titulo}"


class DocumentoEdital(models.Model):
    """Documentos exigidos pelo edital. Podem ser PDFs estáticos ou templates fatiados."""
    TIPO_CHOICES = (
        ('arquivo', 'Arquivo Estático (Upload Comum)'),
        ('template', 'Template Estruturado (Preenchimento em Tela)'),
    )
    edital = models.ForeignKey(Edital, on_delete=models.CASCADE, related_name='documentos_exigidos')
    nome = models.CharField(max_length=150, verbose_name="Nome do Documento (Ex: Projeto de Pesquisa)")
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, default='arquivo')
    
    # Se for arquivo estático, o admin faz o upload do modelo (ex: PDF/Word de instrução)
    arquivo_modelo = models.FileField(upload_to='editais/modelos/', null=True, blank=True, verbose_name="Modelo de Arquivo")

    def __str__(self):
        return f"{self.nome} ({self.get_tipo_display()})"


class CampoTemplate(models.Model):
    """Se o documento for do tipo 'template', aqui definimos os campos/seções dele."""
    TIPO_CAMPO_CHOICES = (
        ('texto_curto', 'Texto Curto (CharField)'),
        ('texto_longo', 'Texto Longo / Parágrafos (TextField)'),
    )
    documento = models.ForeignKey(DocumentoEdital, on_delete=models.CASCADE, related_name='campos_template')
    label = models.CharField(max_length=150, verbose_name="Nome do Campo (Ex: Justificativa, Cronograma)")
    tipo_campo = models.CharField(max_length=20, choices=TIPO_CAMPO_CHOICES, default='texto_longo')
    ordem = models.IntegerField(default=1, verbose_name="Ordem de Exibição")
    instrucoes_originais = models.TextField(verbose_name="Instruções de preenchimento do Edital para este campo")

    class Meta:
        ordering = ['ordem']

class PerfilCurriculo(models.Model):
    """Armazena o resumo do currículo do pesquisador (Texto puro do Lattes ou extraído)"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='curriculo')
    texto_lattes = models.TextField(verbose_name="Resumo Estruturado do Currículo Lattes / C.V.")
    atualizado_em = models.DateTimeField(auto_now=True)


class Projeto(models.Model):
    STATUS_CHOICES = (
        ('rascunho', 'Em Elaboração'),
        ('revisao', 'Em Revisão por Pares'),
        ('submetido', 'Submetido'),
    )
    edital = models.ForeignKey(Edital, on_delete=models.PROTECT, related_name='projetos_submetidos')
    titulo = models.CharField(max_length=255, verbose_name="Título da Proposta de Projeto")
    proponente = models.ForeignKey(User, on_delete=models.CASCADE, related_name='meus_projetos_criados')
    
    # Compartilhamento / Trabalho em Equipe
    equipe = models.ManyToManyField(User, related_name='projetos_coautoria', blank=True)
    
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='rascunho')
    criado_em = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.titulo


class PreenchimentoCampo(models.Model):
    """Armazena o conteúdo atual escrito pela equipe para cada campo de um template."""
    projeto = models.ForeignKey(Projeto, on_delete=models.CASCADE, related_name='respostas_campos')
    campo = models.ForeignKey(CampoTemplate, on_delete=models.CASCADE)
    valor = models.TextField(blank=True, null=True, verbose_name="Conteúdo Redigido")
    modificado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    modificado_em = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('projeto', 'campo')

class RevisaoPares(models.Model):
    """Controle de solicitações de revisão cega ou aberta de parceiros externos."""
    projeto = models.ForeignKey(Projeto, on_delete=models.CASCADE, related_name='revisoes_recebidas')
    revisor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='projetos_para_revisar')
    comentarios = models.TextField(verbose_name="Parecer / Críticas do Revisor", null=True, blank=True)
    concluida = models.BooleanField(default=False)
    solicitada_em = models.DateTimeField(auto_now_add=True)
    concluida_em = models.DateTimeField(null=True, blank=True)

class ReferenciaProjeto(models.Model):
    # Tipos básicos mapeados do BibTeX
    TIPO_PUBLICACAO_CHOICES = [
        ('article', 'Artigo em Periódico (Journal)'),
        ('inproceedings', 'Anais de Conferência (Conference)'),
        ('book', 'Livro'),
        ('misc', 'Outros / Site'),
    ]

    projeto = models.ForeignKey(Projeto, on_delete=models.CASCADE, related_name='referencias')
    
    # A chave de citação usada no LaTeX (Ex: silva2026). Pode ser gerada automaticamente no `save()`
    chave_bibtex = models.CharField(max_length=100, blank=True, help_text="Ex: silva2026")
    
    # Metadados Estruturados
    tipo = models.CharField(max_length=20, choices=TIPO_PUBLICACAO_CHOICES, default='article')
    autores = models.CharField(max_length=500, help_text="Formato: Sobrenome, Nome and Sobrenome, Nome")
    titulo = models.CharField(max_length=300)
    ano = models.CharField(max_length=4)
    revista_evento = models.CharField(max_length=200, blank=True, null=True, verbose_name="Revista ou Nome do Evento")
    volume = models.CharField(max_length=50, blank=True, null=True)
    paginas = models.CharField(max_length=50, blank=True, null=True)
    doi = models.CharField(max_length=100, blank=True, null=True)

    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['autores', 'ano']

    def __str__(self):
        return f"{self.chave_bibtex} - {self.titulo}"

class ComentarioRevisao(models.Model):
    projeto = models.ForeignKey(Projeto, on_delete=models.CASCADE, related_name='comentarios')
    campo = models.ForeignKey(CampoTemplate, on_delete=models.CASCADE)
    revisor = models.ForeignKey(User, on_delete=models.CASCADE)
    
    # Este ID é crucial: ele vai ligar o banco de dados à tag <span> no texto do TinyMCE
    marker_id = models.CharField(max_length=50, unique=True) 
    
    texto_selecionado = models.TextField(help_text="O trecho que o professor grifou")
    texto_comentario = models.TextField(help_text="O comentário/orientação em si")
    resolvido = models.BooleanField(default=False)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-criado_em']

class ParecerHistorico(models.Model):
    titulo = models.CharField(max_length=255, help_text="Ex: Parecer FAPESP - Auxílio Regular 2024 (Reprovado)")
    orgao_fomento = models.CharField(max_length=100, blank=True, null=True, help_text="Ex: FAPESP, FINEP, CNPq")
    texto_parecer = models.TextField(help_text="Texto completo do feedback recebido dos avaliadores.")
    cadastrado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.titulo

class HistoricoParte(models.Model):
    """Guarda as versões anteriores do enunciado de uma parte antes dela ser editada ou regerada pela IA."""
    parte = models.ForeignKey(Parte, on_delete=models.CASCADE, related_name='historico')
    enunciado = models.TextField(verbose_name="Texto da Versão Anterior")
    salvo_em = models.DateTimeField(auto_now_add=True)
    salvo_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = "Histórico de Parte"
        verbose_name_plural = "Históricos de Partes"
        ordering = ['-salvo_em']

    def __str__(self):
        return f"Versão da Parte {self.parte.ordem} - {self.salvo_em.strftime('%d/%m/%Y %H:%M')}"


class ConfiguracaoModeloLLM(models.Model):
    """
    Permite cadastrar vários modelos de LLM no Django Admin e manter apenas UM ativo em tempo real.
    Todas as chamadas ao LLM no sistema consultam dinamicamente o modelo ativo.
    """
    PROVEDOR_CHOICES = [
        ('gemini', 'Google Gemini (API)'),
        ('ollama', 'Ollama (Local / Self-Hosted)'),
    ]

    nome_exibicao = models.CharField(
        max_length=120,
        verbose_name="Nome de Exibição",
        help_text="Ex: Gemini 3.1 Flash Lite, Gemini 2.5 Pro, Ollama Gemma 3 12B"
    )
    provedor = models.CharField(
        max_length=30,
        choices=PROVEDOR_CHOICES,
        default='gemini',
        verbose_name="Provedor"
    )
    model_id = models.CharField(
        max_length=120,
        verbose_name="ID do Modelo (Model Name)",
        help_text="Ex: gemini-3.1-flash-lite, gemini-2.5-flash, gemini-2.5-pro, gemma3:12b"
    )
    temperatura = models.FloatField(
        default=0.7,
        verbose_name="Temperatura",
        help_text="Valor entre 0.0 (mais determinístico) e 1.5 (mais criativo)."
    )
    max_retries = models.IntegerField(
        default=2,
        verbose_name="Máximo de Retentativas"
    )
    base_url = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="URL Base (Ollama / Endpoint Customizado)",
        help_text="Opcional. Ex: http://localhost:11434 ou http://192.168.86.20:11434 para Ollama."
    )
    api_key_override = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Chave de API Específica (Opcional)",
        help_text="Se deixado em branco, utilizará a GEMINI_API_KEY padrão do settings.py."
    )
    ativo = models.BooleanField(
        default=False,
        verbose_name="Ativo (Em Uso)"
    )
    descricao = models.TextField(
        blank=True,
        null=True,
        verbose_name="Descrição / Observações"
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Modelo de IA (LLM)"
        verbose_name_plural = "Modelos de IA (LLMs)"
        ordering = ['-ativo', 'nome_exibicao']

    def __str__(self):
        status_str = " [ATIVO]" if self.ativo else ""
        return f"{self.nome_exibicao} ({self.get_provedor_display()}: {self.model_id}){status_str}"

    def save(self, *args, **kwargs):
        garantir_tabela_configuracao_llm()
        super().save(*args, **kwargs)
        if self.ativo:
            ConfiguracaoModeloLLM.objects.exclude(pk=self.pk).update(ativo=False)
        elif not ConfiguracaoModeloLLM.objects.filter(ativo=True).exists():
            ConfiguracaoModeloLLM.objects.filter(pk=self.pk).update(ativo=True)
            self.ativo = True

    @classmethod
    def get_modelo_ativo(cls):
        """Retorna a instância ativa de ConfiguracaoModeloLLM (criando os padrões se a tabela estiver vazia)."""
        garantir_tabela_configuracao_llm()
        ativo = cls.objects.filter(ativo=True).first()
        if not ativo:
            ativo = cls.objects.first()
            if ativo:
                ativo.ativo = True
                ativo.save()
        return ativo


def garantir_tabela_configuracao_llm():
    """
    Garante que a tabela `mimir_configuracaomodelollm` exista no banco de dados SQLite/relacional
    mesmo sem necessidade de rodar migrations manuais e popula modelos iniciais caso esteja vazia.
    """
    from django.db import connection

    try:
        tabelas = connection.introspection.table_names()
        if 'mimir_configuracaomodelollm' not in tabelas:
            with connection.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS "mimir_configuracaomodelollm" (
                        "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
                        "nome_exibicao" varchar(120) NOT NULL,
                        "provedor" varchar(30) NOT NULL,
                        "model_id" varchar(120) NOT NULL,
                        "temperatura" real NOT NULL,
                        "max_retries" integer NOT NULL,
                        "base_url" varchar(255) NULL,
                        "api_key_override" varchar(255) NULL,
                        "ativo" bool NOT NULL,
                        "descricao" text NULL,
                        "criado_em" datetime NOT NULL,
                        "atualizado_em" datetime NOT NULL
                    )
                """)

        if ConfiguracaoModeloLLM.objects.count() == 0:
            agora = timezone.now()
            modelos_iniciais = [
                {
                    "nome_exibicao": "Gemini 3.1 Flash Lite (Padrão Rápido)",
                    "provedor": "gemini",
                    "model_id": "gemini-3.1-flash-lite",
                    "temperatura": 0.7,
                    "max_retries": 2,
                    "ativo": True,
                    "descricao": "Modelo padrão de alta velocidade e baixo custo para geração de questões, PBL e análises.",
                },
                {
                    "nome_exibicao": "Gemini 2.5 Flash (Multimodal & Equilibrado)",
                    "provedor": "gemini",
                    "model_id": "gemini-2.5-flash",
                    "temperatura": 0.5,
                    "max_retries": 2,
                    "ativo": False,
                    "descricao": "Excelente para leitura óptica de provas por foto, geração de questões complexas e correções.",
                },
                {
                    "nome_exibicao": "Gemini 2.5 Pro (Raciocínio Profundo)",
                    "provedor": "gemini",
                    "model_id": "gemini-2.5-pro",
                    "temperatura": 0.6,
                    "max_retries": 2,
                    "ativo": False,
                    "descricao": "Indicado para elaboração de problemas PBL avançados, avaliação de projetos PD&I e editais extensos.",
                },
                {
                    "nome_exibicao": "Gemini 2.0 Flash",
                    "provedor": "gemini",
                    "model_id": "gemini-2.0-flash",
                    "temperatura": 0.7,
                    "max_retries": 2,
                    "ativo": False,
                    "descricao": "Alternativa estável da família Gemini 2.0.",
                },
                {
                    "nome_exibicao": "Ollama Gemma 3 12B (Execução Local)",
                    "provedor": "ollama",
                    "model_id": "gemma3:12b",
                    "temperatura": 0.7,
                    "max_retries": 2,
                    "base_url": "http://localhost:11434",
                    "ativo": False,
                    "descricao": "Modelo local via Ollama para operação sem consumo de API externa.",
                },
            ]
            for item in modelos_iniciais:
                ConfiguracaoModeloLLM.objects.create(
                    nome_exibicao=item["nome_exibicao"],
                    provedor=item["provedor"],
                    model_id=item["model_id"],
                    temperatura=item["temperatura"],
                    max_retries=item["max_retries"],
                    base_url=item.get("base_url"),
                    ativo=item["ativo"],
                    descricao=item["descricao"],
                    criado_em=agora,
                    atualizado_em=agora,
                )
    except Exception as e:
        print(f"Aviso ao verificar tabela ConfiguracaoModeloLLM: {e}")

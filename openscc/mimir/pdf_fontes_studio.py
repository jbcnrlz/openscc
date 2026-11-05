import html
import io
import os
import re
from typing import Dict, List, Optional, Tuple, Union

import pdfplumber


def parse_intervalo_paginas(
    expressao: str,
    total_paginas: int,
    pagina_inicio: Optional[int] = None,
    pagina_fim: Optional[int] = None,
) -> List[int]:
    """
    Converte uma expressão de intervalo de páginas (ex: '10-24', '1-5, 8, 12-18')
    ou par (pagina_inicio, pagina_fim) em uma lista ordenada de páginas 1-based válidas.
    """
    paginas = set()
    if expressao and str(expressao).strip():
        partes = re.split(r"[,;]+", str(expressao).strip())
        for parte in partes:
            parte = parte.strip()
            if not parte:
                continue
            m_range = re.match(r"^(\d+)\s*[\-\–\—aà:]\s*(\d+)$", parte, re.IGNORECASE)
            if m_range:
                ini = int(m_range.group(1))
                fim = int(m_range.group(2))
                if ini > fim:
                    ini, fim = fim, ini
                for p in range(max(1, ini), min(total_paginas, fim) + 1):
                    paginas.add(p)
            elif parte.isdigit():
                p = int(parte)
                if 1 <= p <= total_paginas:
                    paginas.add(p)

    if not paginas and pagina_inicio is not None:
        ini = max(1, int(pagina_inicio))
        fim = int(pagina_fim) if pagina_fim is not None else ini
        if ini > fim:
            ini, fim = fim, ini
        fim = min(total_paginas, fim)
        for p in range(ini, fim + 1):
            paginas.add(p)

    return sorted(paginas)


def _ler_bytes_pdf(fonte_bytes_ou_path: Union[bytes, str, io.BytesIO]) -> bytes:
    if isinstance(fonte_bytes_ou_path, bytes):
        return fonte_bytes_ou_path
    if isinstance(fonte_bytes_ou_path, str):
        with open(fonte_bytes_ou_path, "rb") as f:
            return f.read()
    if hasattr(fonte_bytes_ou_path, "seek"):
        fonte_bytes_ou_path.seek(0)
    return fonte_bytes_ou_path.read()


def _extrair_sumario_bookmarks(pdf_bytes: bytes, total_paginas: int) -> List[Dict]:
    """
    Tenta extrair o sumário nativo (Bookmarks / Outlines / ToC) embutido no PDF.
    """
    capitulos = []

    # Tentativa 1: pypdfium2 (instalado junto com pdfplumber)
    try:
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(pdf_bytes)
        toc = doc.get_toc()
        itens_brutos = []
        for item in toc:
            titulo = (getattr(item, "title", "") or "").strip()
            page_idx = getattr(item, "page_index", None)
            level = getattr(item, "level", 0)
            if titulo and page_idx is not None and 0 <= page_idx < total_paginas and level <= 1:
                itens_brutos.append({"titulo": titulo, "pagina_inicio": int(page_idx) + 1})
        doc.close()

        if itens_brutos:
            for idx, it in enumerate(itens_brutos):
                prox_ini = (
                    itens_brutos[idx + 1]["pagina_inicio"] - 1
                    if idx + 1 < len(itens_brutos)
                    else total_paginas
                )
                fim = max(it["pagina_inicio"], min(total_paginas, prox_ini))
                capitulos.append({
                    "titulo": it["titulo"][:120],
                    "pagina_inicio": it["pagina_inicio"],
                    "pagina_fim": fim,
                    "origem": "Sumário Digital (Bookmark PDF)",
                })
            return capitulos
    except Exception:
        pass

    # Tentativa 2: pypdf / PyPDF2
    for mod_name in ("pypdf", "PyPDF2"):
        try:
            mod = __import__(mod_name)
            reader = mod.PdfReader(io.BytesIO(pdf_bytes))
            outline = getattr(reader, "outline", None) or getattr(reader, "outlines", None)
            if not outline:
                continue
            itens_brutos = []

            def _percorrer(nos, nivel=0):
                if nivel > 1:
                    return
                for no in nos:
                    if isinstance(no, list):
                        _percorrer(no, nivel + 1)
                    else:
                        titulo = (getattr(no, "title", "") or "").strip()
                        try:
                            p_num = reader.get_destination_page_number(no) + 1
                        except Exception:
                            p_num = None
                        if titulo and p_num and 1 <= p_num <= total_paginas:
                            itens_brutos.append({"titulo": titulo, "pagina_inicio": p_num})

            _percorrer(outline)
            if itens_brutos:
                for idx, it in enumerate(itens_brutos):
                    prox_ini = (
                        itens_brutos[idx + 1]["pagina_inicio"] - 1
                        if idx + 1 < len(itens_brutos)
                        else total_paginas
                    )
                    fim = max(it["pagina_inicio"], min(total_paginas, prox_ini))
                    capitulos.append({
                        "titulo": it["titulo"][:120],
                        "pagina_inicio": it["pagina_inicio"],
                        "pagina_fim": fim,
                        "origem": "Sumário Digital (Outline PDF)",
                    })
                return capitulos
        except Exception:
            continue

    return capitulos


def inspecionar_pdf_estrutura(
    fonte_bytes_ou_path: Union[bytes, str, io.BytesIO],
    max_paginas_detalhe: int = 250,
) -> dict:
    """
    Analisa um arquivo PDF e retorna:
    - total_paginas
    - capitulos_detectados (via Bookmarks nativos ou detecção heurística de títulos de capítulos)
    - paginas_resumo (lista com número, primeira linha/título e prévia do conteúdo de cada página)
    """
    pdf_bytes = _ler_bytes_pdf(fonte_bytes_ou_path)
    paginas_resumo = []
    candidatos_heuristica = []

    padrao_capitulo = re.compile(
        r"^(?:CAP[IÍ]TULO|CHAPTER|UNIDADE|PARTE|M[OÓ]DULO|SE[CÇ][AÃ]O)\s+([0-9IVXLCDM]+)(?:[\s\:\-\–\—\.]+(.*))?$",
        re.IGNORECASE,
    )

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        total_paginas = len(pdf.pages)
        limite = min(total_paginas, max_paginas_detalhe)

        for idx in range(limite):
            num_pag = idx + 1
            pagina = pdf.pages[idx]
            try:
                txt = (pagina.extract_text() or "").strip()
            except Exception:
                txt = ""

            linhas = [ln.strip() for ln in txt.splitlines() if ln.strip()]
            primeira_linha = linhas[0][:100] if linhas else f"Página {num_pag} (sem camada de texto / imagem)"
            segunda_linha = linhas[1][:100] if len(linhas) > 1 else ""
            previa = " ".join(linhas[:5])[:260] if linhas else ""

            # Verifica nas 4 primeiras linhas da página se há início de Capítulo / Unidade
            for pos_l, ln in enumerate(linhas[:4]):
                m_cap = padrao_capitulo.match(ln)
                if m_cap:
                    complemento = (m_cap.group(2) or "").strip()
                    if not complemento and pos_l + 1 < len(linhas):
                        complemento = linhas[pos_l + 1][:80]
                    titulo_cap = ln if len(ln) > 12 else f"{ln} - {complemento}".strip(" -")
                    candidatos_heuristica.append({
                        "titulo": titulo_cap[:110],
                        "pagina_inicio": num_pag,
                    })
                    primeira_linha = titulo_cap[:100]
                    break

            paginas_resumo.append({
                "numero": num_pag,
                "titulo_sugerido": primeira_linha,
                "subtitulo": segunda_linha,
                "previa": previa,
                "caracteres": len(txt),
            })

    # 1. Tenta sumário nativo do PDF
    capitulos_detectados = _extrair_sumario_bookmarks(pdf_bytes, total_paginas)

    # 2. Se não houver bookmarks no PDF, usa os capítulos detectados nas páginas pelo texto
    if not capitulos_detectados and candidatos_heuristica:
        # Remove duplicatas na mesma página ou páginas consecutivas idênticas
        filtrados = []
        for cand in candidatos_heuristica:
            if not filtrados or cand["pagina_inicio"] > filtrados[-1]["pagina_inicio"]:
                filtrados.append(cand)

        for idx, it in enumerate(filtrados):
            prox_ini = (
                filtrados[idx + 1]["pagina_inicio"] - 1
                if idx + 1 < len(filtrados)
                else total_paginas
            )
            fim = max(it["pagina_inicio"], min(total_paginas, prox_ini))
            capitulos_detectados.append({
                "titulo": it["titulo"],
                "pagina_inicio": it["pagina_inicio"],
                "pagina_fim": fim,
                "origem": "Detectado no cabeçalho da página",
            })

    # 3. Se ainda não houver capítulos e o PDF tiver mais de 15 páginas, sugere divisões lógicas
    if not capitulos_detectados and total_paginas > 1:
        passo = 20 if total_paginas > 40 else max(5, (total_paginas + 2) // 3)
        bloco_num = 1
        for p_ini in range(1, total_paginas + 1, passo):
            p_fim = min(total_paginas, p_ini + passo - 1)
            titulo_p = f"Parte {bloco_num} (Páginas {p_ini} a {p_fim})"
            if p_ini <= len(paginas_resumo):
                lin = paginas_resumo[p_ini - 1]["titulo_sugerido"]
                if lin and not lin.startswith("Página "):
                    titulo_p = f"Parte {bloco_num} — {lin[:60]}"
            capitulos_detectados.append({
                "titulo": titulo_p,
                "pagina_inicio": p_ini,
                "pagina_fim": p_fim,
                "origem": "Sugestão por blocos de páginas",
            })
            bloco_num += 1

    return {
        "total_paginas": total_paginas,
        "paginas_inspecionadas": len(paginas_resumo),
        "capitulos_detectados": capitulos_detectados,
        "paginas_resumo": paginas_resumo,
    }


def extrair_texto_pagina_especifica(
    fonte_bytes_ou_path: Union[bytes, str, io.BytesIO],
    pagina_num: int,
) -> dict:
    """
    Retorna o texto completo e a imagem renderizada (base64) de uma página específica (1-based) do PDF.
    """
    pdf_bytes = _ler_bytes_pdf(fonte_bytes_ou_path)
    imagem_b64 = renderizar_pagina_pdf_base64(pdf_bytes, pagina_num, escala=1.6)

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        total = len(pdf.pages)
        if pagina_num < 1 or pagina_num > total:
            return {
                "success": False,
                "message": f"Página {pagina_num} fora do limite (1 a {total}).",
            }
        pagina = pdf.pages[pagina_num - 1]
        texto = (pagina.extract_text() or "").strip()
        return {
            "success": True,
            "pagina": pagina_num,
            "total_paginas": total,
            "texto": texto or "[Página sem camada de texto selecionável]",
            "imagem_base64": imagem_b64,
        }


def renderizar_pagina_pdf_base64(
    fonte_bytes_ou_path: Union[bytes, str, io.BytesIO],
    pagina_num: int,
    escala: float = 1.5,
) -> str:
    """
    Renderiza visualmente uma página 1-based do PDF em JPEG Base64 (via pypdfium2 ou pdfplumber)
    para exibição direta no navegador mesmo sem depender de plugins externos de PDF.
    """
    pdf_bytes = _ler_bytes_pdf(fonte_bytes_ou_path)

    # Tentativa 1: pypdfium2 (rápido e fiel)
    try:
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(pdf_bytes)
        total = len(doc)
        if 1 <= pagina_num <= total:
            page = doc[pagina_num - 1]
            bitmap = page.render(scale=escala)
            pil_image = bitmap.to_pil()
            if pil_image.mode != "RGB":
                pil_image = pil_image.convert("RGB")
            buf = io.BytesIO()
            pil_image.save(buf, format="JPEG", quality=85)
            doc.close()
            import base64
            return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")
        doc.close()
    except Exception:
        pass

    # Tentativa 2: pdfplumber page.to_image()
    try:
        import base64

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            total = len(pdf.pages)
            if 1 <= pagina_num <= total:
                im = pdf.pages[pagina_num - 1].to_image(resolution=int(72 * escala)).original
                if im.mode != "RGB":
                    im = im.convert("RGB")
                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=85)
                return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception:
        pass

    return ""


def gerar_pdf_fatiado_bytes(
    fonte_bytes_ou_path: Union[bytes, str, io.BytesIO],
    paginas_1based: List[int],
    titulo_fatia: str = "Capítulo Extraído",
) -> Tuple[bytes, str]:
    """
    Gera um novo arquivo PDF contendo exclusivamente as páginas 1-based informadas.
    Tenta cópia nativa lossless de páginas (pypdfium2, pypdf, PyPDF2, PyMuPDF) e
    possui fallback com pdfplumber + WeasyPrint para garantir que sempre retorne um PDF válido.
    """
    pdf_bytes = _ler_bytes_pdf(fonte_bytes_ou_path)
    indices_0based = [p - 1 for p in paginas_1based if p >= 1]

    # 1. Tentativa nativa lossless via pypdfium2 (presente no ambiente via pdfplumber)
    try:
        import pypdfium2 as pdfium

        src_doc = pdfium.PdfDocument(pdf_bytes)
        total = len(src_doc)
        indices_validos = [idx for idx in indices_0based if 0 <= idx < total]
        if indices_validos:
            novo_doc = pdfium.PdfDocument.new()
            novo_doc.import_pages(src_doc, indices_validos)
            out_buf = io.BytesIO()
            novo_doc.save(out_buf)
            novo_doc.close()
            src_doc.close()
            return out_buf.getvalue(), ".pdf"
        src_doc.close()
    except Exception:
        pass

    # 2. Tentativa nativa lossless via pypdf ou PyPDF2
    for mod_name in ("pypdf", "PyPDF2"):
        try:
            mod = __import__(mod_name)
            reader = mod.PdfReader(io.BytesIO(pdf_bytes))
            writer = mod.PdfWriter()
            total = len(reader.pages)
            adicionou = False
            for idx in indices_0based:
                if 0 <= idx < total:
                    writer.add_page(reader.pages[idx])
                    adicionou = True
            if adicionou:
                out_buf = io.BytesIO()
                writer.write(out_buf)
                return out_buf.getvalue(), ".pdf"
        except Exception:
            continue

    # 3. Tentativa via PyMuPDF (fitz)
    try:
        import fitz

        src_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        novo_doc = fitz.open()
        total = len(src_doc)
        for idx in indices_0based:
            if 0 <= idx < total:
                novo_doc.insert_pdf(src_doc, from_page=idx, to_page=idx)
        if len(novo_doc) > 0:
            out_bytes = novo_doc.tobytes()
            novo_doc.close()
            src_doc.close()
            return out_bytes, ".pdf"
    except Exception:
        pass

    # 4. Fallback via pdfplumber + WeasyPrint (gera um PDF limpo com o conteúdo das páginas selecionadas)
    blocos_html = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        total = len(pdf.pages)
        for idx in indices_0based:
            if 0 <= idx < total:
                pag_num = idx + 1
                txt = (pdf.pages[idx].extract_text() or "").strip()
                txt_escaped = html.escape(txt)
                blocos_html.append(
                    f"<div class='page-slice'>"
                    f"<div class='page-header'>Página original {pag_num} • {html.escape(titulo_fatia)}</div>"
                    f"<pre>{txt_escaped}</pre>"
                    f"</div>"
                )

    from weasyprint import HTML

    html_doc = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
@page {{ size: A4; margin: 15mm; }}
body {{ font-family: sans-serif; font-size: 10pt; color: #111; }}
.page-slice {{ page-break-after: always; }}
.page-slice:last-child {{ page-break-after: auto; }}
.page-header {{ font-size: 8.5pt; color: #555; border-bottom: 1px solid #ccc; margin-bottom: 8px; padding-bottom: 4px; font-weight: bold; }}
pre {{ white-space: pre-wrap; word-wrap: break-word; font-family: sans-serif; line-height: 1.45; }}
</style>
</head>
<body>{"".join(blocos_html)}</body>
</html>"""
    pdf_gerado = HTML(string=html_doc).write_pdf()
    return pdf_gerado, ".pdf"


# -*- coding: utf-8 -*-
import re
import unicodedata
from urllib.parse import quote

from odoo import http
from odoo.http import request


def _content_disposition_filename(nombre_archivo):
    """`nombre_periodo` (usado en el nombre del archivo) sale de
    `partner_id.name` de la aseguradora — texto libre que puede traer
    tildes/ñ (ej. "Compañía de Seguros..."). Un Content-Disposition con
    bytes no-ASCII crudos viola la codificación de headers HTTP y puede
    romper la descarga o mostrar el nombre corrupto en algunos
    navegadores. Se manda un fallback ASCII (`filename=`) más la versión
    real en UTF-8 (`filename*=`, RFC 5987), que es lo que usan los
    navegadores modernos para mostrar el nombre correcto."""
    ascii_fallback = unicodedata.normalize('NFKD', nombre_archivo)
    ascii_fallback = ascii_fallback.encode('ascii', 'ignore').decode('ascii')
    ascii_fallback = re.sub(r'[^A-Za-z0-9._-]', '_', ascii_fallback) or 'Notas_Conformidad.xlsx'
    return 'attachment; filename="%s"; filename*=UTF-8\'\'%s' % (
        ascii_fallback, quote(nombre_archivo),
    )


class RehalifeSegurosNotaConformidadExportController(http.Controller):

    @http.route(
        '/rehalife_seguros/nota_conformidad/export_excel',
        type='http',
        auth='user',
        methods=['GET'],
        csrf=False,
    )
    def export_excel(self, ids='', **kwargs):
        """Genera el .xlsx de las NC pedidas y lo transmite directo —
        sin pasar por un ir.attachment. `auth='user'` deja que el ORM
        aplique el ACL normal de lectura de rehalife.nota.conformidad
        (cualquier usuario interno puede leerlas, ver ir.model.access.csv)."""
        try:
            nc_ids = [int(i) for i in ids.split(',') if i]
        except ValueError:
            return request.not_found()

        notas = request.env['rehalife.nota.conformidad'].browse(nc_ids).exists()
        if not notas:
            return request.not_found()

        contenido = notas._generar_excel()
        nombre_archivo = notas._nombre_archivo_excel()

        return request.make_response(
            contenido,
            headers=[
                ('Content-Type',
                 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', _content_disposition_filename(nombre_archivo)),
            ],
        )

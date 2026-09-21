# -*- coding: utf-8 -*-
import base64
import io
import logging

from odoo import models, fields
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:
    import xlsxwriter
except ImportError:  # pragma: no cover
    xlsxwriter = None
    _logger.warning('xlsxwriter no esta instalado: no se podra generar la '
                    'plantilla de servicios.')


class RehalifeServicesTemplateWizard(models.TransientModel):
    _name = 'rehalife.services.template.wizard'
    _description = 'Plantilla Excel de Servicios Rehalife'

    _COLUMNAS = [
        ('name', 'Nombre del servicio. Obligatorio, maximo 100 caracteres.'),
        ('default_code', 'Referencia interna (= reference del backend). Maximo 100.'),
        ('reservas_rehalife', '1 siempre. Es lo que lo hace aparecer en Rehalife > Servicios.'),
        ('type', 'service (fijo).'),
        ('categ_id', 'Categoria de producto, ruta completa. Debe existir en Odoo.'),
        ('uom_id', 'Unidad de medida. Si se deja vacio, Odoo usa "Unidades".'),
        ('list_price', 'Precio de venta. Punto decimal, sin simbolo de moneda.'),
        ('sale_ok', '1 = vendible.'),
        ('available_in_pos', '1 = cobrable desde el POS.'),
        ('taxes_id', 'Impuestos de venta, por nombre exacto. Varios separados por coma.'),
        ('rehalife_service_description', 'Descripcion del servicio en el backend.'),
        ('rehalife_requires_evaluation', '1 / 0. Requiere evaluacion previa.'),
        ('rehalife_cancel_window_hours', 'Horas limite de cancelacion.'),
        ('rehalife_open_window_hours', 'Horas de apertura de agenda. Debe ser > 0 o vacio.'),
        ('rehalife_reminder_hours_before', 'Horas de recordatorio. Debe ser > 0 o vacio.'),
        ('rehalife_max_advance_days', 'Dias max. de anticipacion. Debe ser > 0 o vacio.'),
        ('rehalife_siat_actividad_codigo', 'Codigo CAEB. Ver hoja "Actividades SIAT".'),
        ('rehalife_siat_producto_codigo', 'Codigo de producto SIAT. Ver hoja "Productos SIAT".'),
        ('rehalife_siat_unidad_codigo', 'Codigo clasificador. Ver hoja "Unidades SIAT".'),
    ]

    _EJEMPLOS = [
        [
            'servicio-dereserva', 'RESR_V01', 1, 'service', '[CATEGORIA]',
            'Unidades', 1000, 1, 1, '[NOMBRE DEL IMPUESTO]',
            'Descripcion del servicio tal como se ve en el backend', 1,
            10, 4, 1, 20,
            '[LLENAR EN BASE A ACTIVIDADES]',
            '[LLENAR EN BASE A PRODUCTOS SIAT]',
            '[LLENAR EN BASE A UNIDADES SIAT]',
        ],
        [
            'consulta-evaluacion', 'EVAL_V01', 1, 'service', '[CATEGORIA]',
            'Unidades', 250, 1, 1, '[NOMBRE DEL IMPUESTO]',
            'Primera evaluacion del paciente, con informe', 0,
            24, 2, 2, 30,
            '[LLENAR EN BASE A ACTIVIDADES]',
            '[LLENAR EN BASE A PRODUCTOS SIAT]',
            '[LLENAR EN BASE A UNIDADES SIAT]',
        ],
    ]

    file_data = fields.Binary(string='Plantilla', readonly=True, attachment=False)
    file_name = fields.Char(string='Nombre del Archivo', readonly=True)
    state = fields.Selection(
        [('draft', 'Generar'), ('done', 'Lista')],
        default='draft',
    )

    def action_generate(self):
        self.ensure_one()
        if xlsxwriter is None:
            raise UserError(
                'Falta la libreria xlsxwriter en el servidor de Odoo. '
                'Instalala con: pip install xlsxwriter'
            )

        company = self.env.company
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})

        fmt_header = workbook.add_format({
            'bold': True, 'bg_color': '#1F4E79', 'font_color': 'white',
            'border': 1, 'text_wrap': True, 'valign': 'vcenter',
        })
        fmt_title = workbook.add_format({'bold': True, 'font_size': 13})
        fmt_wrap = workbook.add_format({'text_wrap': True, 'valign': 'top'})
        fmt_code = workbook.add_format({'num_format': '@'})   # texto, no numero
        fmt_ejemplo = workbook.add_format({
            'italic': True, 'font_color': '#808080', 'bg_color': '#F2F2F2',
        })
        fmt_aviso = workbook.add_format({
            'bold': True, 'font_color': '#C00000',
        })

        self._hoja_servicios(workbook, fmt_header, fmt_ejemplo, fmt_aviso)
        self._hoja_instrucciones(workbook, fmt_title, fmt_header, fmt_wrap)
        self._hoja_actividades(workbook, fmt_header, fmt_code, company)
        self._hoja_productos(workbook, fmt_header, fmt_code, company)
        self._hoja_unidades(workbook, fmt_header, fmt_code, company)

        workbook.close()
        output.seek(0)

        self.write({
            'file_data': base64.b64encode(output.read()),
            'file_name': 'plantilla_servicios_rehalife.xlsx',
            'state': 'done',
        })
        output.close()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _hoja_servicios(self, workbook, fmt_header, fmt_ejemplo, fmt_aviso):
        """Hoja de carga: encabezados + 2 filas de ejemplo. Va primera para que
        el importador de Odoo la tome por defecto."""
        sheet = workbook.add_worksheet('Servicios')
        sheet.freeze_panes(1, 0)

        for col, (nombre, _ayuda) in enumerate(self._COLUMNAS):
            sheet.write(0, col, nombre, fmt_header)
            sheet.set_column(col, col, max(len(nombre) + 2, 14))

        for fila, ejemplo in enumerate(self._EJEMPLOS, start=1):
            for col, valor in enumerate(ejemplo):
                sheet.write(fila, col, valor, fmt_ejemplo)

        # El aviso va en una columna vacia a la derecha: no lo lee el
        # importador (solo mapea las columnas con encabezado) pero se ve al
        # abrir el archivo.
        sheet.write(
            1, len(self._COLUMNAS) + 1,
            '<<< BORRAR ESTAS 2 FILAS DE EJEMPLO ANTES DE IMPORTAR',
            fmt_aviso,
        )

    def _hoja_instrucciones(self, workbook, fmt_title, fmt_header, fmt_wrap):
        sheet = workbook.add_worksheet('Instrucciones')
        sheet.set_column(0, 0, 36)
        sheet.set_column(1, 1, 80)

        fila = 0
        sheet.write(fila, 0, 'Plantilla de Servicios Rehalife', fmt_title)
        fila += 2

        for texto in [
            'La hoja "Servicios" trae 2 filas de ejemplo en gris: BORRALAS antes '
            'de importar. Si te las olvidas, fallan solas (los codigos SIAT entre '
            'corchetes no existen), pero mejor no depender de eso.',
            'Como importar: Rehalife > Servicios > boton de engranaje > Importar '
            'registros > subir este archivo > Probar > Importar.',
            'Probá siempre con 3 o 4 filas antes de cargar el catalogo completo.',
            'No hacen falta columnas para la unidad de compra, la compra, el '
            'estado activo ni el ID externo: Odoo los resuelve solo.',
            'Los encabezados son nombres tecnicos de campos: no los cambies ni '
            'los traduzcas, o Odoo no los va a reconocer.',
            'Los codigos SIAT de las otras hojas salen de esta misma base de '
            'datos, asi que son los validos para esta compania.',
            'Un servicio importado existe SOLO en Odoo. Para crearlo tambien en '
            'el backend: Rehalife > Sincronizacion > Sincronizar Servicios > '
            'Enviar al backend.',
        ]:
            sheet.write(fila, 1, texto, fmt_wrap)
            fila += 1

        fila += 1
        sheet.write(fila, 0, 'Columna', fmt_header)
        sheet.write(fila, 1, 'Descripcion', fmt_header)
        fila += 1
        for nombre, ayuda in self._COLUMNAS:
            sheet.write(fila, 0, nombre)
            sheet.write(fila, 1, ayuda, fmt_wrap)
            fila += 1

    def _hoja_actividades(self, workbook, fmt_header, fmt_code, company):
        sheet = workbook.add_worksheet('Actividades SIAT')
        sheet.freeze_panes(1, 0)
        sheet.set_column(0, 0, 18)
        sheet.set_column(1, 1, 90)
        sheet.write(0, 0, 'rehalife_siat_actividad_codigo', fmt_header)
        sheet.write(0, 1, 'Descripcion (referencia)', fmt_header)

        actividades = self.env['alpha.siat.actividad'].search([
            ('company_id', '=', company.id),
            ('active', '=', True),
        ])
        for fila, actividad in enumerate(actividades, start=1):
            sheet.write_string(fila, 0, actividad.codigo_caeb or '', fmt_code)
            sheet.write_string(fila, 1, actividad.descripcion or '')

    def _hoja_productos(self, workbook, fmt_header, fmt_code, company):
        sheet = workbook.add_worksheet('Productos SIAT')
        sheet.freeze_panes(1, 0)
        sheet.set_column(0, 1, 30)
        sheet.set_column(2, 2, 90)
        sheet.write(0, 0, 'rehalife_siat_actividad_codigo', fmt_header)
        sheet.write(0, 1, 'rehalife_siat_producto_codigo', fmt_header)
        sheet.write(0, 2, 'Descripcion (referencia)', fmt_header)

        productos = self.env['alpha.siat.producto.servicio'].search([
            ('company_id', '=', company.id),
            ('active', '=', True),
        ])
        for fila, producto in enumerate(productos, start=1):
            sheet.write_string(fila, 0, producto.codigo_actividad or '', fmt_code)
            sheet.write_string(fila, 1, producto.codigo_producto or '', fmt_code)
            sheet.write_string(fila, 2, producto.descripcion_producto or '')

    def _hoja_unidades(self, workbook, fmt_header, fmt_code, company):
        sheet = workbook.add_worksheet('Unidades SIAT')
        sheet.freeze_panes(1, 0)
        sheet.set_column(0, 0, 28)
        sheet.set_column(1, 1, 60)
        sheet.write(0, 0, 'rehalife_siat_unidad_codigo', fmt_header)
        sheet.write(0, 1, 'Descripcion (referencia)', fmt_header)

        unidades = self.env['alpha.siat.unidad.medida'].search([
            ('company_id', '=', company.id),
            ('active', '=', True),
        ])
        for fila, unidad in enumerate(unidades, start=1):
            sheet.write_string(fila, 0, str(unidad.codigo_clasificador or ''), fmt_code)
            sheet.write_string(fila, 1, unidad.descripcion or '')
# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.osv import expression

_logger = logging.getLogger(__name__)

_MESES_ES = {
    1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril', 5: 'Mayo', 6: 'Junio',
    7: 'Julio', 8: 'Agosto', 9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre',
    12: 'Diciembre',
}


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # NOTA (2026-09-12): antes existía un campo `aseguradora_id` aparte,
    # redundante con el "Customer" (`partner_id`) nativo — el pedido
    # de venta marco siempre se factura al mismo partner que ya era su
    # Customer. Decisión confirmada con el usuario: se borró ese campo;
    # ahora `partner_id` ES la aseguradora (relabeled a "Aseguradora" y
    # con domain a is_aseguradora=True, solo en la vista de formulario
    # dedicada a Pedidos de Venta Marco — ver
    # view_order_form_rehalife_seguros_pedido_marco en
    # rehalife_seguros_sale_order_views.xml, no se toca el campo nativo
    # para el resto de Sales Orders/Quotations de Odoo).
    es_pedido_marco = fields.Boolean(string='Es Pedido de Venta Marco', default=False)
    periodo = fields.Date(
        string='Periodo',
        help='Día 1 del mes que representa este pedido marco.',
    )
    nombre_periodo = fields.Char(
        string='Nombre del Periodo', compute='_compute_nombre_periodo', store=True,
    )

    # NOTA (2026-09-11, corregida 2026-09-12 — HU-18): el Pedido de Venta
    # Marco sigue sin ser el trigger AUTOMÁTICO de facturación (documento de
    # estimación/seguimiento, HU-6/HU-7) — pero ahora sí es desde donde se
    # dispara la facturación EN LOTE: botón "Facturar NC"
    # (action_facturar_notas_conformidad) toma todas las NC en estado
    # 'aprobada' sin factura de este pedido y genera UNA sola factura para
    # todas (una línea por NC — ver
    # rehalife.nota.conformidad._generar_factura_agrupada). También existe
    # un botón individual "Generar Factura" en cada NC. Para ver TODAS las
    # facturas generadas a partir de las líneas de este pedido, usa el
    # smart button nativo "Facturas" del formulario (funciona solo porque
    # cada línea de factura lleva `sale_line_ids` apuntando a la línea del
    # pedido marco).
    nota_conformidad_ids = fields.One2many(
        'rehalife.nota.conformidad', 'pedido_marco_id', string='Notas de Conformidad',
    )
    nota_conformidad_count = fields.Integer(
        string='Cant. Notas de Conformidad', compute='_compute_nota_conformidad_count',
    )

    @api.depends('partner_id', 'periodo')
    def _compute_nombre_periodo(self):
        for order in self:
            if order.partner_id and order.periodo:
                mes = _MESES_ES.get(order.periodo.month, '')
                anio = str(order.periodo.year)[-2:]
                order.nombre_periodo = f'{order.partner_id.name}-{mes}{anio}'
            else:
                order.nombre_periodo = False

    def _compute_nota_conformidad_count(self):
        for order in self:
            order.nota_conformidad_count = len(order.nota_conformidad_ids)

    @api.constrains('es_pedido_marco', 'partner_id')
    def _check_pedido_marco_aseguradora(self):
        for order in self:
            if not order.es_pedido_marco:
                continue
            if not order.partner_id:
                raise ValidationError(
                    'Un Pedido de Venta Marco requiere una Aseguradora (Customer).'
                )
            if not order.partner_id.is_aseguradora:
                raise ValidationError(
                    'El Customer de un Pedido de Venta Marco debe ser una '
                    'Aseguradora — marca "Es Aseguradora" en el contacto de '
                    '"%s" primero.' % order.partner_id.name
                )

    # No duplicar Pedido de Venta Marco por aseguradora+período (pedido
    # explícito del usuario, 2026-09-10). Un pedido Cancelado no cuenta —
    # si se cancela uno, debe poder crearse otro para el mismo
    # aseguradora/período. Se valida en Python (no _sql_constraints) para
    # dar un mensaje claro y porque solo aplica cuando es_pedido_marco=True
    # (una constraint SQL UNIQUE(partner_id, periodo) aplicaría a nivel
    # de toda la tabla sale.order, no solo a los pedidos marco).
    @api.constrains('es_pedido_marco', 'partner_id', 'periodo', 'state')
    def _check_pedido_marco_periodo_unico(self):
        for order in self:
            if not order.es_pedido_marco or not order.partner_id or not order.periodo:
                continue
            duplicado = self.search([
                ('id', '!=', order.id),
                ('es_pedido_marco', '=', True),
                ('partner_id', '=', order.partner_id.id),
                ('periodo', '=', order.periodo),
                ('state', '!=', 'cancel'),
            ], limit=1)
            if duplicado:
                raise ValidationError(
                    'Ya existe un Pedido de Venta Marco ("%s") para "%s" en '
                    'el período %s. No se puede duplicar — edita el '
                    'existente en vez de crear uno nuevo (o cancélalo '
                    'primero si de verdad necesitas reemplazarlo).' % (
                        duplicado.name, order.partner_id.name,
                        order.nombre_periodo or order.periodo,
                    )
                )

    # Buscar un Pedido de Venta Marco por su "Nombre del Periodo" (ej.
    # "ClinicaXYZ-Sep25"), no solo por su número de pedido (ej. "S00023") —
    # una misma aseguradora tiene un Pedido de Venta Marco distinto por cada
    # período (ya garantizado único por `_check_pedido_marco_periodo_unico`
    # más arriba), así que hoy cualquier Many2one a sale.order en el módulo
    # (rehalife.nota.conformidad.pedido_marco_id, rehalife.reservation.
    # pedido_marco_id, el wizard de Reportes, etc.) solo dejaba buscar
    # escribiendo el número de pedido, que el usuario no tiene motivo para
    # memorizar. Se hace UNA sola vez a nivel de modelo, en vez de tocar cada
    # vista, para que aplique automáticamente a todos esos campos.
    # No afecta sale.order normales: nombre_periodo solo se computa cuando
    # es_pedido_marco=True (_compute_nombre_periodo más arriba), así que en
    # el resto de Sales Orders/Quotations el OR de abajo simplemente no
    # matchea nada.
    def _search_display_name(self, operator, value):
        domain = super()._search_display_name(operator, value)
        if value:
            domain = expression.OR([domain, [('nombre_periodo', operator, value)]])
        return domain

    # El desplegable Many2one (y cualquier breadcrumb/tag) muestra
    # `display_name` — sin esto, buscar "Sep25" encontraría el pedido
    # correcto pero el resultado listado seguiría mostrando solo su número
    # ("S00023"), sin pista de a qué período corresponde. Ojo: esto NO toca
    # `name` (el número de pedido sigue igual en reportes/breadcrumbs que
    # usan `name` directamente) — solo el `display_name` calculado.
    def _compute_display_name(self):
        super()._compute_display_name()
        for order in self:
            if order.es_pedido_marco and order.nombre_periodo:
                order.display_name = '%s (%s)' % (order.display_name, order.nombre_periodo)

    def action_view_notas_conformidad(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Notas de Conformidad',
            'res_model': 'rehalife.nota.conformidad',
            'view_mode': 'list,form',
            'domain': [('pedido_marco_id', '=', self.id)],
            'context': {'default_pedido_marco_id': self.id},
        }

    def action_facturar_notas_conformidad(self):
        """Botón "Facturar NC" (HU-18): agrupa TODAS las Notas de
        Conformidad en estado 'aprobada' sin factura de este Pedido de
        Venta Marco en UNA sola factura (una línea por NC, no se pierde de
        qué paciente es cada una). No incluye 'pendiente'/'rechazada'/
        'regularizada'/'facturada' — solo 'aprobada' sin `factura_id` aún."""
        self.ensure_one()
        notas = self.nota_conformidad_ids.filtered(
            lambda n: n.estado == 'aprobada' and not n.factura_id
        )
        if not notas:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Facturar Notas de Conformidad',
                    'message': 'No hay Notas de Conformidad pendientes de '
                               'facturar en este Pedido de Venta Marco — o no '
                               'hay ninguna Aprobada todavía, o las Aprobadas '
                               'ya tienen su propia factura individual '
                               '(generada con el botón "Generar Factura" de '
                               'cada NC).',
                    'type': 'warning',
                    'sticky': True,
                },
            }
        invoice = notas._generar_factura_agrupada()
        return notas._action_factura_generada_notification(invoice)

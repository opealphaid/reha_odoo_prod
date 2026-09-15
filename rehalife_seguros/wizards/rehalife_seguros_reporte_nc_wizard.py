# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models


class RehalifeSegurosReporteNotasConformidadWizard(models.TransientModel):
    """Wizard de SOLO CONSULTA (no crea/modifica ninguna Nota de
    Conformidad): genera un PDF con el listado de Notas de Conformidad de un
    Pedido de Venta Marco, opcionalmente filtrado por estado — para revisar
    rápidamente en qué va ese pedido (pendientes, aprobadas, facturadas,
    etc.) sin entrar a Notas de Conformidad y filtrar a mano."""

    _name = 'rehalife.seguros.reporte.nc.wizard'
    _description = 'Reporte de Notas de Conformidad por Pedido de Venta Marco'

    pedido_marco_id = fields.Many2one(
        'sale.order', string='Pedido de Venta Marco', required=True,
        domain="[('es_pedido_marco', '=', True)]",
    )
    estado = fields.Selection(
        selection=lambda self: self.env['rehalife.nota.conformidad']._fields['estado'].selection,
        string='Filtrar por Estado',
        help='Dejar vacío para incluir Notas de Conformidad en cualquier estado.',
    )
    fecha_desde = fields.Date(
        string='Fecha de Emisión Desde',
        compute='_compute_rango_fechas',
        readonly=True,
        help='Se calcula automáticamente: primer día del mes del Pedido de Venta Marco seleccionado.',
    )
    fecha_hasta = fields.Date(
        string='Fecha de Emisión Hasta',
        compute='_compute_rango_fechas',
        readonly=True,
        help='Se calcula automáticamente: último día del mes del Pedido de Venta Marco seleccionado.',
    )

    @api.depends('pedido_marco_id', 'pedido_marco_id.periodo')
    def _compute_rango_fechas(self):
        # El Pedido de Venta Marco representa un mes calendario completo
        # (ver 'periodo' y 'nombre_periodo' en sale.order). El reporte de
        # Notas de Conformidad siempre debe limitarse a ese mes, así que
        # el rango de fechas ya no se pide a mano: se deriva del PVM
        # elegido para evitar que alguien filtre por error un rango que
        # no corresponde a ese período.
        for wizard in self:
            periodo = wizard.pedido_marco_id.periodo
            if periodo:
                primer_dia = periodo.replace(day=1)
                ultimo_dia = primer_dia + relativedelta(months=1, days=-1)
                wizard.fecha_desde = primer_dia
                wizard.fecha_hasta = ultimo_dia
            else:
                wizard.fecha_desde = False
                wizard.fecha_hasta = False

    def _get_notas_conformidad(self):
        self.ensure_one()
        domain = [('pedido_marco_id', '=', self.pedido_marco_id.id)]
        if self.estado:
            domain.append(('estado', '=', self.estado))
        if self.fecha_desde:
            domain.append(('fecha_emision', '>=', self.fecha_desde))
        if self.fecha_hasta:
            domain.append(('fecha_emision', '<=', self.fecha_hasta))
        return self.env['rehalife.nota.conformidad'].search(domain, order='fecha_emision')

    def action_generar_pdf(self):
        self.ensure_one()
        return self.env.ref('rehalife_seguros.action_report_reporte_nc').report_action(self)

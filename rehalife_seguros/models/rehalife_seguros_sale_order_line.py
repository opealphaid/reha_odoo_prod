# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    qty_conformidad = fields.Float(
        string='Cant. en Notas de Conformidad',
        default=0.0,
        readonly=True,
        help='Suma de "cantidad" de todas las Notas de Conformidad generadas contra '
             'esta línea (en cualquier estado excepto regularizada). Se actualiza '
             'solo por código, no por compute.',
    )
    qty_confirmada = fields.Float(
        string='Cant. Confirmada por Aseguradora',
        default=0.0,
        readonly=True,
        help='Suma de "cantidad" de las Notas de Conformidad aprobadas por la '
             'aseguradora contra esta línea. Se actualiza solo por código.',
    )

    # El "Precio Unitario" (price_unit, campo nativo) de una línea de Pedido
    # de Venta Marco representa el % (0-100) que la aseguradora cubre de ese
    # servicio — NO un monto en Bs. (decisión confirmada con el usuario,
    # 2026-09-12). No se toca el campo/label nativo (para no afectar el
    # resto de Sales Orders del sistema, que no son Pedidos de Venta Marco)
    # — solo se valida el rango aquí. Ver rehalife_seguros_nota_conformidad.py
    # (`monto_cubierto`) para el cálculo del monto real a partir de este %.
    @api.constrains('price_unit', 'order_id', 'display_type')
    def _check_price_unit_porcentaje_cobertura(self):
        for line in self:
            if line.display_type or not line.order_id.es_pedido_marco:
                continue
            if line.price_unit < 0 or line.price_unit > 100:
                raise ValidationError(
                    'El "Precio Unitario" de "%s" es %.2f, pero en un Pedido '
                    'de Venta Marco representa el %% que la aseguradora '
                    'cubre de ese servicio — debe estar entre 0 y 100 (una '
                    'aseguradora puede cubrir hasta el 100%%, nunca más).'
                    % (line.product_id.display_name or line.name, line.price_unit)
                )

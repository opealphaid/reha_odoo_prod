# -*- coding: utf-8 -*-
from markupsafe import Markup, escape

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


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

    # ── % de cobertura y monto (Fase 6, punto 3 — 2026-11-06) ────────────────
    # Antes el "Precio Unitario" (price_unit) de una línea de Pedido de Venta
    # Marco ERA el % de cobertura (decisión del 2026-09-12). Desde la versión
    # 18.0.1.0.3:
    # - porcentaje_cobertura: % (0-100) que la aseguradora cubre del servicio.
    #   Es el único dato de origen: copago del POS, congelamiento, NC, clonado
    #   y lectura para Next lo leen de aquí.
    # - precio_servicio_pvm: precio del servicio (product.lst_price) tomado al
    #   poner el % o el producto. NO sigue los cambios de precio posteriores
    #   (decisión del usuario: no recalcular PVM existentes).
    # - price_unit: MONTO en Bs. que cubre la aseguradora por sesión =
    #   precio_servicio_pvm × % / 100, calculado y readonly en el PVM. Así el
    #   total del pedido es lo esperado a facturar a la aseguradora.
    porcentaje_cobertura = fields.Float(
        string='% Cobertura Aseguradora', default=0.0, copy=True,
        help='Porcentaje (0 a 100) del precio del servicio que cubre la aseguradora. '
             'Solo se usa en Pedidos de Venta Marco.',
    )
    precio_servicio_pvm = fields.Float(
        string='Precio servicio', compute='_compute_precio_servicio_pvm', store=True,
        readonly=True, digits='Product Price',
        help='Precio del servicio cuando se fijó el % o el producto de la línea. '
             'Cambiar después el precio del servicio no modifica el Pedido Marco.',
    )

    def _es_linea_pvm(self):
        self.ensure_one()
        return bool(self.order_id.es_pedido_marco and not self.display_type)

    @api.depends('product_id', 'porcentaje_cobertura')
    def _compute_precio_servicio_pvm(self):
        # Sin product_id.lst_price en las dependencias a propósito: un cambio
        # de precio del servicio no recalcula PVM existentes.
        for line in self:
            if line._es_linea_pvm() and line.product_id:
                line.precio_servicio_pvm = line.product_id.lst_price
            else:
                line.precio_servicio_pvm = 0.0

    def _monto_cobertura_pvm(self):
        """Monto en Bs. que cubre la aseguradora por sesión, redondeado como
        la Nota de Conformidad (currency.round)."""
        self.ensure_one()
        currency = self.currency_id or self.order_id.currency_id or self.env.company.currency_id
        return currency.round(
            (self.precio_servicio_pvm or 0.0) * (self.porcentaje_cobertura or 0.0) / 100.0
        )

    @api.depends('porcentaje_cobertura', 'precio_servicio_pvm')
    def _compute_price_unit(self):
        # Las líneas de PVM nunca pasan por la lista de precios: su price_unit
        # es el monto de la aseguradora. Un cambio de cantidad estimada
        # vuelve a dar el mismo monto (usa precio_servicio_pvm, no el precio
        # actual). El resto de pedidos de venta sigue el cálculo nativo.
        pvm_lines = self.filtered(lambda l: l.order_id and l._es_linea_pvm())
        super(SaleOrderLine, self - pvm_lines)._compute_price_unit()
        for line in pvm_lines:
            monto = line._monto_cobertura_pvm()
            line.price_unit = monto
            line.technical_price_unit = monto

    @api.constrains('porcentaje_cobertura', 'order_id', 'display_type')
    def _check_porcentaje_cobertura(self):
        for line in self:
            if not line._es_linea_pvm():
                continue
            if line.porcentaje_cobertura < 0 or line.porcentaje_cobertura > 100:
                raise ValidationError(
                    'El "%% Cobertura Aseguradora" de "%s" es %.2f: debe estar entre '
                    '0 y 100 (una aseguradora puede cubrir hasta el 100%%, nunca más).'
                    % (line.product_id.display_name or line.name, line.porcentaje_cobertura)
                )

    def write(self, vals):
        if 'porcentaje_cobertura' not in vals:
            return super().write(vals)
        # El % se puede editar aunque la línea ya tenga facturas (decisión del
        # usuario): solo afecta reservas no pagadas y sin NC. No en un PVM
        # cancelado. Cada cambio queda en el chatter del PVM.
        nuevo = vals['porcentaje_cobertura'] or 0.0
        anteriores = {}
        for line in self:
            if not line._es_linea_pvm():
                continue
            if line.order_id.state == 'cancel':
                raise UserError(
                    'El Pedido de Venta Marco %s está cancelado: no se puede cambiar '
                    'el %% de cobertura.' % line.order_id.name
                )
            if abs((line.porcentaje_cobertura or 0.0) - nuevo) > 1e-6:
                anteriores[line.id] = line.porcentaje_cobertura or 0.0
        result = super().write(vals)
        for line in self.filtered(lambda l: l.id in anteriores):
            line.order_id.message_post(body=Markup(
                '%% Cobertura Aseguradora de <b>%s</b>: %.2f %% → %.2f %% '
                '(monto aseguradora por sesión: %.2f).'
            ) % (
                escape(line.product_id.display_name or line.name or ''),
                anteriores[line.id], line.porcentaje_cobertura, line.price_unit,
            ))
        return result

# -*- coding: utf-8 -*-
from odoo import models, fields


class SiatSucursal(models.Model):
    """Vincula la Sucursal SIAT (sucursal + punto de venta de Impuestos) con
    la sucursal Rehalife. Varias Sucursales SIAT (varios PDV) pueden apuntar a
    la misma rehalife.branch.

    Cadena de la regla de recepción: usuario → siat_sucursal_id →
    rehalife_branch_id → reservas de esa sucursal.
    """
    _inherit = 'alpha.siat.sucursal'

    rehalife_branch_id = fields.Many2one(
        'rehalife.branch',
        string='Sucursal Rehalife',
        ondelete='restrict',
        index=True,
    )

    def write(self, vals):
        result = super().write(vals)
        if 'rehalife_branch_id' in vals:
            # El dominio de ir.rule queda cacheado por usuario: sin esto, la
            # regla de recepción seguiría usando la sucursal anterior.
            self.env.registry.clear_cache()
        return result

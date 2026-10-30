# -*- coding: utf-8 -*-
from odoo import models, fields


class ResUsers(models.Model):
    """Sucursal Rehalife del usuario, derivada de su Sucursal SIAT.

    No se guarda nada propio: la fuente es siat_sucursal_id (alpha_siat), la
    misma desde la que factura el usuario, para que ver, cobrar y facturar
    queden siempre en la misma sucursal.
    """
    _inherit = 'res.users'

    rehalife_branch_id = fields.Many2one(
        related='siat_sucursal_id.rehalife_branch_id',
        string='Sucursal Rehalife',
        readonly=True,
    )

    def write(self, vals):
        result = super().write(vals)
        if 'siat_sucursal_id' in vals:
            # El dominio de ir.rule queda cacheado por usuario: sin esto, el
            # recepcionista seguiría viendo las reservas de su sucursal anterior.
            self.env.registry.clear_cache()
        return result

# alpha_siat/models/res_users.py
from odoo import models, fields


class ResUsers(models.Model):
    _inherit = 'res.users'

    siat_sucursal_id = fields.Many2one(
        'alpha.siat.sucursal',
        string='Sucursal SIAT',
        domain="[('company_id', 'in', company_ids), ('active', '=', True)]",
        help='Sucursal y punto de venta SIAT desde el cual este usuario emite facturas.'
    )

from odoo import fields, models


class AccountPaymentMethod(models.Model):
    _inherit = 'account.payment.method'

    banking_code = fields.Char(
        string="Banking Report Code",
        help="Code used to identify this payment method in the banking report.",
    )

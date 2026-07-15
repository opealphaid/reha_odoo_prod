from odoo import models, fields, api


class AccountMovePurchaseBolivianInfo(models.Model):
    _inherit = 'account.move'

    with_tax = fields.Boolean(
        string='With Tax',
        default=True,
        help='Indicates if the invoice includes taxes'
    )

    dui = fields.Char(
        string='DUI',
        help='Documento Único de Identidad (for imports)'
    )

    auth_number = fields.Char(
        string='Authorization Number',
        help='Authorization number issued by SIN'
    )

    control_code = fields.Char(
        string='Control Code',
        help='Control code from supplier invoice'
    )

    invoice_number = fields.Char(
        string='Invoice Number',
        help='Invoice number from supplier'
    )

    @api.onchange('invoice_line_ids', 'invoice_line_ids.tax_ids')
    def _onchange_invoice_lines_taxes(self):
        """Automatically set with_tax based on invoice lines"""
        has_tax = False
        for line in self.invoice_line_ids:
            if line.tax_ids:
                has_tax = True
                break
        self.with_tax = has_tax
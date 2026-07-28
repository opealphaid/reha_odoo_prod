import logging
from odoo import fields, models

_logger = logging.getLogger(__name__)


class BankbookWizard(models.TransientModel):
    _name = 'accounting_community.bankbook.wizard'
    _description = 'Bankbook Report Wizard'

    start_date = fields.Date(string='Start Date', required=True)
    end_date = fields.Date(string='End Date', required=True)
    account = fields.Many2one(
        comodel_name='account.account',
        string='Account',
        required=True,
        domain=[('account_type', 'like', 'asset_cash')],
    )

    def action_print_bankbook(self):
        data = {
            'start_date': str(self.start_date),
            'end_date': str(self.end_date),
            'account_id': self.account.id,
        }
        return self.env.ref('accounting_community.action_report_bankbook').report_action(self, data=data)

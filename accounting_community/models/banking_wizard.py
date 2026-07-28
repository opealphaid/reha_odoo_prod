from odoo import fields, models


class BankingWizard(models.TransientModel):
    _name = 'accounting_community.banking.wizard'
    _description = 'Banking Report Wizard'

    start_date = fields.Date(string="Start Date", required=True)
    end_date = fields.Date(string="End Date", required=True)

    def action_print_sales_banking(self):
        data = {'start_date': str(self.start_date), 'end_date': str(self.end_date)}
        return self.env.ref(
            'accounting_community.action_report_sales_banking'
        ).report_action(self, data=data)

    def action_print_purchase_banking(self):
        data = {'start_date': str(self.start_date), 'end_date': str(self.end_date)}
        return self.env.ref(
            'accounting_community.action_report_purchase_banking'
        ).report_action(self, data=data)

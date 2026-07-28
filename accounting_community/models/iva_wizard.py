from odoo import fields, models


class IvaReportWizard(models.TransientModel):
    _name = 'accounting_community.iva.wizard'
    _description = 'Libro de Compras y Ventas IVA Wizard'

    start_date = fields.Date(string='Start Date', required=True)
    end_date = fields.Date(string='End Date', required=True)

    def action_print_sales_iva(self):
        data = {'start_date': str(self.start_date), 'end_date': str(self.end_date)}
        return self.env.ref('accounting_community.action_report_sales_iva').report_action(self, data=data)

    def action_print_purchase_iva(self):
        data = {'start_date': str(self.start_date), 'end_date': str(self.end_date)}
        return self.env.ref('accounting_community.action_report_purchase_iva').report_action(self, data=data)

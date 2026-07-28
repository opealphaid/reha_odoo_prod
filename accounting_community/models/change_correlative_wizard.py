from odoo import models, fields


class ChangeCorrelativeWizard(models.TransientModel):
    _name = 'change.correlative.wizard'
    _description = 'Cambio de Correlativo'

    move_ids = fields.Many2many('account.move', string='Asientos Contables')
    unique_code = fields.Char(string='Nuevo Correlativo')

    def action_apply(self):
        for move in self.move_ids:
            move.unique_code = self.unique_code

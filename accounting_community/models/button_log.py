from odoo import models, fields


class ButtonLog(models.Model):
    _name = 'button.log'
    _description = 'Button Log'

    user_id = fields.Many2one('res.users', string='Usuario')
    date = fields.Datetime(string='Fecha')
    button_type = fields.Char(string='Tipo')

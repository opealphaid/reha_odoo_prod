from odoo import fields, models, api


class ButtonList(models.Model):
    _name = 'interactive.button'
    _description = 'Button for interactive components'

    title = fields.Char(string="Title" ,size=20)
    component_id = fields.Many2one(comodel_name="components")

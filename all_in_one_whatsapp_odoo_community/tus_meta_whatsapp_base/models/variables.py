from odoo import api, fields, models, _


class Variables(models.Model):
    _name = "variables"
    _description = 'Whatsapp Variables'

    field_id = fields.Many2one('ir.model.fields', 'Field')
    free_text = fields.Char("Free Text", default="Sample Text")
    component_id = fields.Many2one('components')
    component_type = fields.Selection([('body', 'BODY'), ('button', 'BUTTON')])
    model_id = fields.Many2one('ir.model', related="component_id.model_id")
    sequence = fields.Integer('Sequence')
    carousel_id = fields.Many2one('wa.carousel.component')

    @api.onchange('component_id', 'carousel_id')
    def _onchange_update_variable_sequence(self):
        for rec in self:
            variables = rec.component_id.variables_ids or rec.carousel_id.variables_ids or []
            for i, var in enumerate(variables):
                var.sequence = i + 1
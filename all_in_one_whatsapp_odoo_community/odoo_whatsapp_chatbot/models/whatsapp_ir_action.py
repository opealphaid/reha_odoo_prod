# Part of Odoo. See COPYRIGHT & LICENSE files for full copyright and licensing details.
from odoo import fields, models


class WhatsAppIrAction(models.Model):
    _name = "whatsapp.ir.actions"
    _description = "Action perform through whatsapp chatbot"

    name = fields.Char(string="Action Name", required=True, translate=True)
    binding_model_id = fields.Many2one("ir.model", ondelete="cascade")
    chatbot_id = fields.Many2one(comodel_name="whatsapp.chatbot", string="Chatbot")
    last_message_conf = fields.Selection([('message', 'Message'),
                                          ('template', 'Template')], string="Last Message")
    message = fields.Text(string="Message")
    wa_template_id = fields.Many2one(comodel_name="wa.template")
    no_operator_conf = fields.Selection([('message', 'Message'),
                                         ('template', 'Template')], string="No Operator Conf")
    no_operator_template = fields.Many2one(comodel_name="wa.template", string="No Operator Template")
    no_operator_message = fields.Text(string="No operator Message")
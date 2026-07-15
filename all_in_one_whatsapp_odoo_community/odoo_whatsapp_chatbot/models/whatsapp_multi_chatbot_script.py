# Part of Odoo. See COPYRIGHT & LICENSE files for full copyright and licensing details.
from odoo import api, fields, models


class WhatsappMultiChatbotScript(models.Model):
    _name = "whatsapp.multi.chatbot.script"
    _description = "Multi Script based automatic messages"

    step_call_type = fields.Selection(
        [
            ("message", "Message"),
            ("template", "Template"),
            ("interactive", "Interactive"),
            ("action", "Action"),
        ],
        string="Step Type",
    )
    message_for_multi_script = fields.Text(string="Message", translate=True)
    whatsapp_chatbot_id = fields.Many2one(
        comodel_name="whatsapp.chatbot", string="WA Chatbot"
    )
    wa_chatbot_script_id = fields.Many2one(comodel_name='whatsapp.chatbot.script',string='Chatbot Script')
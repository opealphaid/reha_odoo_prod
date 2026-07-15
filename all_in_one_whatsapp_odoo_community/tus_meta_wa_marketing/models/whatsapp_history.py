from odoo import fields, models


class WhatsappHistory(models.Model):
    _inherit = "whatsapp.history"

    whatsapp_messaging_id = fields.Many2one("whatsapp.messaging")

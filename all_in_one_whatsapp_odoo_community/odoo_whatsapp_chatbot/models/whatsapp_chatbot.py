# Part of Odoo. See COPYRIGHT & LICENSE files for full copyright and licensing details.
from odoo import api, fields, models
import random

class WhatsAppChatbot(models.Model):
    _name = "whatsapp.chatbot"
    _description = "Odoo Whatsapp Chatbot Automation"
    _rec_name = "title"
    _order = "title"

    title = fields.Char("Title", required=True, translate=True)
    active = fields.Boolean(default=True)
    image_1920 = fields.Image(readonly=False)
    step_type = fields.Selection(
        [
            ("message", "Message"),
            ("template", "Template"),
            ("interactive", "Interactive"),
        ],
        string="Step Type",
    )
    step_type_ids = fields.One2many(
        comodel_name="whatsapp.chatbot.script",
        inverse_name="whatsapp_chatbot_id",
        string="Message",
    )
    template_id = fields.Many2one(comodel_name="wa.template", string="WA Template")
    action_ids = fields.One2many(
        comodel_name="whatsapp.ir.actions", inverse_name="chatbot_id", string="Actions"
    )
    channel_ids = fields.One2many(
        comodel_name="discuss.channel", inverse_name="wa_chatbot_id", string="Channels"
    )
    wa_conversation_count = fields.Integer(
        "Number of conversation",
        compute="_compute_wa_conversation",
        store=False,
        readonly=True,
    )
    sequence = fields.Integer(string="Sequence")
    user_ids = fields.Many2many("res.users", string="Operators")


    @api.depends("channel_ids")
    def _compute_wa_conversation(self):
        data = self.env["discuss.channel"].read_group(
            [("wa_chatbot_id", "in", self._ids)],
            ["__count"],
            ["wa_chatbot_id"],
            lazy=False,
        )
        channel_count = {x["wa_chatbot_id"][0]: x["__count"] for x in data}
        for record in self:
            record.wa_conversation_count = channel_count.get(record.id, 0)

    def _assign_active_operator(self, provider, channel):
        available_operator = False
        active_operator = provider.company_id.wa_chatbot_id.mapped("user_ids").filtered(
            lambda user: user.im_status == "online")
        if active_operator:
            wa_chatbot_channels = provider.company_id.wa_chatbot_id.mapped("channel_ids")
            for wa_channel in wa_chatbot_channels:
                operators = active_operator.filtered(lambda av_user: av_user.partner_id not in wa_channel.channel_member_ids.partner_id)
                if operators:
                    for operator in operators:
                        available_operator = operator.partner_id
                else:
                    available_operator = random.choice(active_operator).partner_id

            if available_operator:
                if channel.whatsapp_channel:
                    channel.write({
                            "channel_partner_ids": [(4, available_operator.id)],
                            "is_chatbot_ended": True,
                        })
                    mail_channel_partner = self.env["discuss.channel.member"].sudo().search([
                        ("channel_id", "=", channel.id), ("partner_id", "=", available_operator.id)])
                    if not mail_channel_partner.is_pinned:
                        mail_channel_partner.write(
                            {"is_pinned": True}
                        )
            return available_operator

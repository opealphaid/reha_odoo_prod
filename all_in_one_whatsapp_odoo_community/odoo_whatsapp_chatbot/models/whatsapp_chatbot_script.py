# Part of Odoo. See COPYRIGHT & LICENSE files for full copyright and licensing details.
from odoo import api, fields, models


class WhatsappChatbotScript(models.Model):
    _name = "whatsapp.chatbot.script"
    _description = "Script based automatic messages"
    _order = "sequence"
    _rec_name = "message"

    whatsapp_chatbot_id = fields.Many2one(
        comodel_name="whatsapp.chatbot", string="WA Chatbot"
    )
    sequence = fields.Integer(string="Sequence")
    template_id = fields.Many2one(comodel_name="wa.template", string="WA Template")
    step_call_type = fields.Selection(
        [
            ("message", "Message"),
            ("template", "Template"),
            ("interactive", "Interactive"),
            ("action", "Action"),
        ],
        string="Step Type",
    )
    message = fields.Text(string="Message", translate=True,compute='_compute_message')
    answer = fields.Text(string="Answer", translate=True)
    action_id = fields.Many2one(comodel_name="whatsapp.ir.actions", string="Actions")
    parent_id = fields.Many2one(
        "whatsapp.chatbot.script", string="Parent ChatBot Script"
    )
    # new fields for multi chatbot script
    multi_script_chatbot_ids = fields.One2many(comodel_name='whatsapp.multi.chatbot.script', inverse_name='wa_chatbot_script_id',
                                               string='Multi Script Chatbot')

    @api.depends('multi_script_chatbot_ids.message_for_multi_script')
    def _compute_message(self):
        for multi_message in self:
            messages = multi_message.multi_script_chatbot_ids.mapped('message_for_multi_script')
            multi_message.message = ', '.join(filter(None, messages))

    @api.model_create_multi
    def create(self, vals_list):
        """Sequence Added"""
        vals_by_chatbot_id = {}
        for vals in vals_list:
            chatbot_id = vals.get("whatsapp_chatbot_id")
            if chatbot_id:
                step_values = vals_by_chatbot_id.get(chatbot_id, [])
                step_values.append(vals)
                vals_by_chatbot_id[chatbot_id] = step_values
        if vals_by_chatbot_id:
            read_group_results = self.env["whatsapp.chatbot.script"].read_group(
                [("whatsapp_chatbot_id", "=", vals.get("whatsapp_chatbot_id", 0))],
                ["sequence:max"],
                ["whatsapp_chatbot_id"],
            )
            if len(read_group_results) > 0:
                max_sequence_by_chatbot = {
                    read_group_result["whatsapp_chatbot_id"][0]: read_group_result[
                        "sequence"
                    ]
                    for read_group_result in read_group_results
                }
            else:
                max_sequence_by_chatbot = {}
            current_sequence = (
                max_sequence_by_chatbot
                and max_sequence_by_chatbot.get(
                    read_group_results[0]["whatsapp_chatbot_id"][0], 0
                )
                or 0
            )
            for vals in vals_list:
                if "sequence" in vals:
                    # current_sequence = vals.get('sequence')
                    vals["sequence"] = current_sequence + 1
                    current_sequence += 1
        return super().create(vals_list)

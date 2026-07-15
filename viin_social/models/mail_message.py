from odoo import models, fields


class Message(models.Model):
    _inherit = 'mail.message'

    social_message_id = fields.Char(string='Social Message ID', help='ID of social message')

    def _send_social_message(self):
        social_conversations = self.env['discuss.channel'].search([('id', 'in', self.mapped('res_id'))])
        for r in self:
            social_conversation = social_conversations.filtered_domain([('id', '=', r.res_id)])
            if social_conversation:
                social_page = social_conversation.social_page_id
                social_participant_id = social_conversation.social_participant_id
                if social_page and social_page.media_id.social_provider != 'none':
                    custom_send_social_message_method = '_send_social_message_%s' % social_page.media_id.social_provider
                    if hasattr(self, custom_send_social_message_method):
                        getattr(r, custom_send_social_message_method)(social_page, social_participant_id)

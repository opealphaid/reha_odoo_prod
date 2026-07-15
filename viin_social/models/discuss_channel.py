from odoo import fields, api, models, _
from odoo.exceptions import UserError


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    active = fields.Boolean(string='Active', default=True)
    channel_type = fields.Selection(selection_add=[('social_chat', 'Social Conversation')], ondelete={'social_chat': 'cascade'})
    social_conversation_id = fields.Char(string='Social Conversation ID', help='ID of social conversation')
    # TODO: change social_page_id to page_id from 17++
    social_page_id = fields.Many2one('social.page', string="Social Page ID", ondelete='cascade')
    social_participant_id = fields.Char(string='Social Participant ID', help='ID of participant in social conversation')
    social_user_name = fields.Char(string='Social User Name')

    @api.returns('mail.message', lambda value: value.id)
    def message_post(self, **kwargs):
        self.ensure_one()
        if self.social_conversation_id and self.channel_type == 'social_chat':
            if 'attachment_ids' in kwargs and kwargs['attachment_ids']:
                raise UserError(_("File attachments are not supported yet."))

            message = super(DiscussChannel, self).message_post(**kwargs)

            body = kwargs['body']
            social_page = self.social_page_id
            social_participant_id = self.social_participant_id

            custom_method = '_send_social_message_%s' % social_page.media_id.social_provider
            if hasattr(message, custom_method):
                getattr(message, custom_method)(body, social_page, social_participant_id)
            return message
        return super(DiscussChannel, self).message_post(**kwargs)

    def _compute_is_chat(self):
        super(DiscussChannel, self)._compute_is_chat()
        for record in self:
            if record.channel_type == 'social_chat':
                record.is_chat = True

    def channel_info(self):
        channel_infos = super(DiscussChannel, self).channel_info()
        channel_infos_dict = dict((c['id'], c) for c in channel_infos)
        for r in self:
            if r.channel_type == 'social_chat':
                channel_infos_dict[r.id]['social_page_id'] = r.social_page_id.id
        return list(channel_infos_dict.values())

    def add_members(self, partner_ids=None, guest_ids=None, invite_to_rtc_call=False, open_chat_window=False, post_joined_message=True):
        if isinstance(partner_ids, int):
            partner_ids = [partner_ids]
        if partner_ids:
            users = self.env['res.users'].search([('partner_id', 'in', partner_ids)]).filtered(lambda u: not u.has_group('viin_social.viin_social_group_admin'))
            for r in self:
                if r.social_page_id:
                    allowed_users = r.social_page_id.assign_id | r.social_page_id.member_ids
                    not_allowed_users = users.filtered(lambda u: u not in allowed_users)
                    if not_allowed_users:
                        raise UserError(_("Can not add the user '%s' to this conversation.\n"
                                          "Only approver or members of the Page are allowed to join this conversation.") % not_allowed_users.name)
        return super(DiscussChannel, self).add_members(partner_ids, guest_ids, invite_to_rtc_call, open_chat_window, post_joined_message)

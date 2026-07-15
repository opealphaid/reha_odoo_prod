from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    receive_comment_notification = fields.Boolean(related='company_id.receive_comment_notification', readonly=False)
    receive_reactive_notification = fields.Boolean(related='company_id.receive_reactive_notification', readonly=False)
    module_viin_social_linkedin = fields.Boolean(string='Enable Social LinkedIn', default=False)
    module_viin_social_facebook = fields.Boolean(string='Enable Social Facebook', default=False)
    is_discuss_sidebar_category_social_chat_open = fields.Boolean("Is category socialchat open", default=True)

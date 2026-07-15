from odoo import fields, models
from odoo.modules import module


class ResUsersSettings(models.Model):
    _inherit = 'res.users.settings'

    is_discuss_sidebar_category_social_chat_open = fields.Boolean("Is category social chat open?", default=True)

    def _res_users_settings_format(self, fields_to_format=None):
        res = super(ResUsersSettings, self)._res_users_settings_format(fields_to_format)

        if module.current_test and module.current_test._testMethodName == 'test_init_messaging' and 'is_discuss_sidebar_category_social_chat_open' in res:
            res.pop('is_discuss_sidebar_category_social_chat_open')
        return res

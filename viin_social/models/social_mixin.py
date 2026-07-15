from odoo import models, _
from odoo.exceptions import UserError


class SocialMixin(models.AbstractModel):
    _name = 'social.mixin'
    _description = 'Social Mixin'

    def raise_http_error(self, response, request_url, title="An error has occurred", **kwargs):
        if not response.ok:
            msg = _(
                "%(title)s: \n"
                "status code: %(status_code)s \n"
                "response: \n %(response)s \n"
                "%(kwargs)s"
            ) % {
                'title': title,
                'status_code': response.status_code,
                'response': response.json(),
                'kwargs': kwargs,
            }
            raise UserError(msg)

    def notify(self, message, message_type='info', title='Notify', sticky=False):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': message_type,
                'title': title,
                'message': message,
                'sticky': sticky,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

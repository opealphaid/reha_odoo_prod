import requests
import re

from odoo import models

host = "https://graph.facebook.com"


class Message(models.Model):
    _inherit = 'mail.message'

    def _send_social_message_facebook(self, body, social_page, social_particiapant_id):
        page_access_token = social_page.facebook_page_access_token
        message = re.sub(r'<.*?>', '', body)
        url = host + "/me/messages?access_token=%s" % (page_access_token)
        request_data = {
            "messaging_type": "MESSAGE_TAG",
            "tag": "ACCOUNT_UPDATE",
            "recipient": {
                "id": social_particiapant_id
            },
            "message": {
                "text": message
            }
        }
        res = requests.post(url, json=request_data)
        self.env['social.mixin'].raise_http_error(res, url)
        data = res.json()
        if data.get('message_id', False):
            self.write({'social_message_id': data.get('message_id', False)})
